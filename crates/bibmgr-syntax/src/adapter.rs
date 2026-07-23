//! The only module allowed to mention `bibtex_parser` types.

use crate::value_lexer::lex_value;
use crate::{
    CommentKind, CommentNode, DocumentParts, EntryDelimiter, EntryNode, EntryStatus, FailedBlock,
    FieldNode, ParseMode, ParseOptions, ParseStatus, PreambleNode, StringNode, SyntaxBlock,
    SyntaxDocument, SyntaxSummary, SyntaxToken, TextNode,
};
use bibmgr_model::{
    Diagnostic, DiagnosticId, RuleCode, Severity, SourceId, SourceLocation, TextRange,
};
use bibtex_parser::{
    DiagnosticSeverity as BackendSeverity, EntryDelimiter as BackendEntryDelimiter, ParsedBlock,
    ParsedDocument, ParsedEntry, ParsedEntryStatus, Parser,
};
use std::borrow::Cow;
use std::collections::BTreeSet;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::Arc;

pub(crate) fn parse(source: &str, options: ParseOptions) -> SyntaxDocument {
    let owned: Arc<str> = Arc::from(source);
    let guarded = catch_unwind(AssertUnwindSafe(|| {
        parse_guarded(owned.clone(), options.clone())
    }));
    match guarded {
        Ok(document) => document,
        Err(_) => panic_fallback(owned, options),
    }
}

fn parse_guarded(source: Arc<str>, options: ParseOptions) -> SyntaxDocument {
    // bibtex-parser 0.4 can calculate a character index where its source-map
    // API expects a UTF-8 byte offset while source capture is enabled. Parse a
    // byte-length-preserving ASCII shadow to isolate that backend defect. All
    // public text and spans are mapped back onto the untouched original below.
    let parser_source = ascii_shadow(&source);
    let tolerant = Parser::new()
        .tolerant()
        .capture_source()
        .preserve_raw()
        .parse_document(parser_source.as_ref());

    let document = match tolerant {
        Ok(document) => document,
        Err(error) => return error_fallback(source, options, error.to_string()),
    };

    let strict_diagnostics = if options.mode == ParseMode::Strict {
        Parser::new()
            .capture_source()
            .preserve_raw()
            .parse_document(parser_source.as_ref())
            .ok()
            .map(|strict| strict.diagnostics().to_vec())
            .unwrap_or_default()
    } else {
        Vec::new()
    };

    let Some(masked) = mask_inline_entry_comments(parser_source.as_ref()) else {
        return from_backend(
            source.clone(),
            options,
            &document,
            &[&strict_diagnostics],
            &[],
        );
    };

    // bibtex-parser 0.4 stops tolerant field recovery when it reaches a `%`
    // comment inside an entry. Reparse a byte-length-preserving view where
    // only those comments are whitespace. Structure and ranges come from the
    // recovered view; diagnostics still come from the untouched parser view.
    let recovered = Parser::new()
        .tolerant()
        .capture_source()
        .preserve_raw()
        .parse_document(&masked.source);
    let Ok(recovered) = recovered else {
        return from_backend(
            source.clone(),
            options,
            &document,
            &[&strict_diagnostics],
            &[],
        );
    };

    from_backend(
        source.clone(),
        options,
        &recovered,
        &[document.diagnostics(), &strict_diagnostics],
        &masked.comment_ranges,
    )
}

fn ascii_shadow(source: &str) -> Cow<'_, str> {
    if source.is_ascii() {
        return Cow::Borrowed(source);
    }

    let mut shadow = String::with_capacity(source.len());
    for character in source.chars() {
        if character.is_ascii() {
            shadow.push(character);
        } else {
            shadow.extend(std::iter::repeat_n('x', character.len_utf8()));
        }
    }
    debug_assert_eq!(shadow.len(), source.len());
    Cow::Owned(shadow)
}

#[derive(Debug)]
struct MaskedSource {
    source: String,
    comment_ranges: Vec<TextRange>,
}

/// Replace percent comments nested directly in regular entry bodies with
/// spaces while retaining every byte offset. Percent signs in braced/quoted
/// values, escaped percent signs, and comments outside entries are untouched.
fn mask_inline_entry_comments(source: &str) -> Option<MaskedSource> {
    let bytes = source.as_bytes();
    let mut masked = bytes.to_vec();
    let mut comment_ranges = Vec::new();
    let mut cursor = 0;

    while cursor < bytes.len() {
        let Some(relative_at) = bytes[cursor..].iter().position(|byte| *byte == b'@') else {
            break;
        };
        let at = cursor + relative_at;
        if is_inside_percent_comment(bytes, at) {
            cursor = at + 1;
            continue;
        }
        let type_start = at + 1;
        let mut type_end = type_start;
        while type_end < bytes.len() && is_identifier_byte(bytes[type_end]) {
            type_end += 1;
        }
        if type_end == type_start {
            cursor = type_start;
            continue;
        }

        let mut open = type_end;
        while open < bytes.len() && bytes[open].is_ascii_whitespace() {
            open += 1;
        }
        let Some(&opening) = bytes.get(open) else {
            break;
        };
        if !matches!(opening, b'{' | b'(') {
            cursor = type_end;
            continue;
        }

        let entry_type = &source[type_start..type_end];
        let regular_entry = !entry_type.eq_ignore_ascii_case("comment")
            && !entry_type.eq_ignore_ascii_case("preamble")
            && !entry_type.eq_ignore_ascii_case("string");
        cursor = scan_directive(
            bytes,
            &mut masked,
            open,
            opening,
            regular_entry,
            &mut comment_ranges,
        );
    }

    if comment_ranges.is_empty() {
        None
    } else {
        Some(MaskedSource {
            // `source` is already ASCII (possibly an ASCII shadow), and only
            // ASCII spaces were written above.
            source: String::from_utf8(masked).expect("masked parser source remains ASCII"),
            comment_ranges,
        })
    }
}

fn scan_directive(
    bytes: &[u8],
    masked: &mut [u8],
    open: usize,
    opening: u8,
    recover_comments: bool,
    comment_ranges: &mut Vec<TextRange>,
) -> usize {
    let closing = if opening == b'{' { b'}' } else { b')' };
    let mut brace_depth = usize::from(opening == b'{');
    let mut quoted = false;
    let mut cursor = open + 1;

    while cursor < bytes.len() {
        let byte = bytes[cursor];
        if quoted {
            if byte == b'"' && !is_escaped_byte(bytes, cursor) {
                quoted = false;
            }
            cursor += 1;
            continue;
        }

        let at_body_level = if opening == b'{' {
            brace_depth == 1
        } else {
            brace_depth == 0
        };
        if recover_comments && at_body_level && byte == b'%' && !is_escaped_byte(bytes, cursor) {
            let comment_end = bytes[cursor..]
                .iter()
                .position(|candidate| matches!(*candidate, b'\n' | b'\r'))
                .map_or(bytes.len(), |offset| cursor + offset);
            masked[cursor..comment_end].fill(b' ');
            comment_ranges.push(text_range(cursor, comment_end));
            cursor = comment_end;
            continue;
        }

        if at_body_level && byte == b'"' && !is_escaped_byte(bytes, cursor) {
            quoted = true;
            cursor += 1;
            continue;
        }

        match byte {
            b'{' if !is_escaped_byte(bytes, cursor) => {
                brace_depth = brace_depth.saturating_add(1);
            }
            b'}' if !is_escaped_byte(bytes, cursor) => {
                brace_depth = brace_depth.saturating_sub(1);
                if closing == b'}' && brace_depth == 0 {
                    return cursor + 1;
                }
            }
            b')' if closing == b')' && brace_depth == 0 => return cursor + 1,
            _ => {}
        }
        cursor += 1;
    }

    bytes.len()
}

fn is_escaped_byte(bytes: &[u8], offset: usize) -> bool {
    let mut backslashes = 0;
    let mut cursor = offset;
    while cursor > 0 && bytes[cursor - 1] == b'\\' {
        backslashes += 1;
        cursor -= 1;
    }
    backslashes % 2 == 1
}

fn is_inside_percent_comment(bytes: &[u8], offset: usize) -> bool {
    let line_start = bytes[..offset]
        .iter()
        .rposition(|byte| matches!(*byte, b'\n' | b'\r'))
        .map_or(0, |line_break| line_break + 1);
    (line_start..offset)
        .any(|candidate| bytes[candidate] == b'%' && !is_escaped_byte(bytes, candidate))
}

#[allow(clippy::too_many_lines)]
fn from_backend(
    source: Arc<str>,
    options: ParseOptions,
    backend: &ParsedDocument<'_>,
    supplemental_diagnostics: &[&[bibtex_parser::Diagnostic]],
    inline_comment_ranges: &[TextRange],
) -> SyntaxDocument {
    let entries = backend
        .entries()
        .iter()
        .map(|entry| map_entry(&source, entry, inline_comment_ranges))
        .collect::<Vec<_>>();
    let strings = backend
        .strings()
        .iter()
        .map(|node| map_string(&source, span_range(node.source), &node.name))
        .collect::<Vec<_>>();
    let preambles = backend
        .preambles()
        .iter()
        .map(|node| map_preamble(&source, span_range(node.source)))
        .collect::<Vec<_>>();
    let mut comments = Vec::new();
    let failed_blocks = backend
        .failed_blocks()
        .iter()
        .map(|node| FailedBlock {
            range: span_range(node.source),
            message: node.error.clone(),
        })
        .collect::<Vec<_>>();

    let mut diagnostics = Vec::new();
    let mut seen = BTreeSet::new();
    for diagnostic in backend.diagnostics().iter().chain(
        supplemental_diagnostics
            .iter()
            .flat_map(|diagnostics| diagnostics.iter()),
    ) {
        let mapped = map_diagnostic(diagnostic, &options.source_id, diagnostics.len());
        let key = (
            mapped.code.0.clone(),
            mapped
                .primary_location
                .as_ref()
                .map_or(TextRange::default(), |location| location.range),
            mapped.message.clone(),
        );
        if seen.insert(key) {
            diagnostics.push(mapped);
        }
    }

    let mut blocks = Vec::new();
    let mut text = Vec::new();
    let mut cursor = 0_usize;
    for block in backend.blocks() {
        if let ParsedBlock::Comment(index) = *block {
            let range = backend
                .comments()
                .get(index)
                .map_or(TextRange::default(), |node| span_range(node.source));
            let start = range.start as usize;
            if start > cursor {
                append_gap(
                    &source,
                    cursor,
                    start.min(source.len()),
                    &mut text,
                    &mut comments,
                    &mut blocks,
                );
            }
            if is_explicit_comment(&source, range) {
                let mapped_index = comments.len();
                comments.push(map_comment(&source, range));
                blocks.push(SyntaxBlock::Comment(mapped_index));
            } else {
                append_gap(
                    &source,
                    start.min(source.len()),
                    (range.end as usize).min(source.len()),
                    &mut text,
                    &mut comments,
                    &mut blocks,
                );
            }
            cursor = cursor.max(range.end as usize).min(source.len());
            continue;
        }
        let (range, mapped) = match *block {
            ParsedBlock::Entry(index) => (
                entries
                    .get(index)
                    .map_or(TextRange::default(), |node| node.range),
                SyntaxBlock::Entry(index),
            ),
            ParsedBlock::String(index) => (
                strings
                    .get(index)
                    .map_or(TextRange::default(), |node| node.range),
                SyntaxBlock::String(index),
            ),
            ParsedBlock::Preamble(index) => (
                preambles
                    .get(index)
                    .map_or(TextRange::default(), |node| node.range),
                SyntaxBlock::Preamble(index),
            ),
            ParsedBlock::Comment(_) => unreachable!("comments are handled above"),
            ParsedBlock::Failed(index) => (
                failed_blocks
                    .get(index)
                    .map_or(TextRange::default(), |node| node.range),
                SyntaxBlock::Failed(index),
            ),
        };
        let start = range.start as usize;
        if start > cursor {
            append_gap(
                &source,
                cursor,
                start.min(source.len()),
                &mut text,
                &mut comments,
                &mut blocks,
            );
        }
        blocks.push(mapped);
        cursor = cursor.max(range.end as usize).min(source.len());
    }
    if cursor < source.len() {
        append_gap(
            &source,
            cursor,
            source.len(),
            &mut text,
            &mut comments,
            &mut blocks,
        );
    }

    let errors = diagnostics
        .iter()
        .filter(|diagnostic| diagnostic.severity == Severity::Error)
        .count();
    let warnings = diagnostics
        .iter()
        .filter(|diagnostic| diagnostic.severity == Severity::Warning)
        .count();
    let recovered_entries = entries
        .iter()
        .filter(|entry| entry.status == EntryStatus::Recovered)
        .count();
    let status = if errors == 0 && failed_blocks.is_empty() && recovered_entries == 0 {
        ParseStatus::Ok
    } else if entries.is_empty() && strings.is_empty() && preambles.is_empty() {
        ParseStatus::Failed
    } else {
        ParseStatus::Partial
    };
    let summary = SyntaxSummary {
        status,
        entries: entries.len(),
        strings: strings.len(),
        preambles: preambles.len(),
        comments: comments.len(),
        failed_blocks: failed_blocks.len(),
        recovered_entries,
        errors,
        warnings,
    };

    SyntaxDocument::from_parts(DocumentParts {
        source,
        source_id: options.source_id,
        mode: options.mode,
        blocks,
        text,
        entries,
        strings,
        preambles,
        comments,
        failed_blocks,
        diagnostics,
        summary,
    })
}

fn map_entry(
    source: &str,
    entry: &ParsedEntry<'_>,
    inline_comment_ranges: &[TextRange],
) -> EntryNode {
    let range = span_range(entry.source);
    let entry_type_range = span_range(entry.entry_type_source);
    let key_range = span_range(entry.key_source);
    let delimiter = match entry.delimiter {
        Some(BackendEntryDelimiter::Braces) => EntryDelimiter::Braces,
        Some(BackendEntryDelimiter::Parentheses) => EntryDelimiter::Parentheses,
        None => EntryDelimiter::Unknown,
    };
    let open_delimiter_range = find_open_delimiter(source, range, entry_type_range);
    let close_delimiter_range = find_close_delimiter(source, range, delimiter);
    let fields = entry
        .fields
        .iter()
        .map(|field| {
            let field_range = span_range(field.source);
            let name_range = span_range(field.name_source);
            let value_range = span_range(field.value_source.or(field.value.source));
            let equals_range = find_byte_between(source, name_range.end, value_range.start, b'=');
            let comma_range = find_byte_between(source, value_range.end, field_range.end, b',');
            FieldNode {
                range: field_range,
                name: SyntaxToken::new(slice_or(source, name_range, &field.name), name_range),
                equals_range,
                value: lex_value(source, value_range),
                comma_range,
            }
        })
        .collect::<Vec<_>>();
    let trailing_comma = fields.last().and_then(|field| field.comma_range).is_some();
    let inline_comments = inline_comment_ranges
        .iter()
        .copied()
        .filter(|comment| range.contains(comment.start) && comment.end <= range.end)
        .map(|comment| map_comment(source, comment))
        .collect::<Vec<_>>();
    let recovered_inline_comment = !inline_comments.is_empty();

    EntryNode {
        range,
        at_range: TextRange::new(range.start, range.start.saturating_add(1).min(range.end)),
        entry_type: SyntaxToken::new(
            slice_or(source, entry_type_range, &entry.ty.to_string()),
            entry_type_range,
        ),
        citation_key: SyntaxToken::new(slice_or(source, key_range, &entry.key), key_range),
        delimiter,
        open_delimiter_range,
        close_delimiter_range,
        fields,
        inline_comments,
        trailing_comma,
        status: if entry.status == ParsedEntryStatus::Partial || recovered_inline_comment {
            EntryStatus::Recovered
        } else {
            EntryStatus::Complete
        },
    }
}

fn map_string(source: &str, range: TextRange, fallback_name: &str) -> StringNode {
    let shape = directive_shape(source, range, true);
    StringNode {
        range,
        name: shape.name.unwrap_or_else(|| {
            SyntaxToken::new(fallback_name, TextRange::new(range.start, range.start))
        }),
        value: lex_value(source, shape.value_range),
        delimiter: shape.delimiter,
        trailing_comma: shape.trailing_comma,
    }
}

fn map_preamble(source: &str, range: TextRange) -> PreambleNode {
    let shape = directive_shape(source, range, false);
    PreambleNode {
        range,
        value: lex_value(source, shape.value_range),
        delimiter: shape.delimiter,
    }
}

fn map_comment(source: &str, range: TextRange) -> CommentNode {
    let raw = source_slice(source, range).unwrap_or_default();
    if raw.starts_with('%') {
        CommentNode {
            range,
            content_range: TextRange::new(range.start.saturating_add(1), range.end),
            kind: CommentKind::Percent,
        }
    } else {
        let open = raw.find(['{', '(']);
        let content_start = open.map_or(range.start, |offset| {
            range.start.saturating_add(saturating_u32(offset + 1))
        });
        let content_end = raw.rfind(['}', ')']).map_or(range.end, |offset| {
            range.start.saturating_add(saturating_u32(offset))
        });
        CommentNode {
            range,
            content_range: TextRange::new(content_start.min(content_end), content_end),
            kind: CommentKind::Explicit,
        }
    }
}

fn is_explicit_comment(source: &str, range: TextRange) -> bool {
    let raw = source_slice(source, range).unwrap_or_default().trim_start();
    raw.get(..8)
        .is_some_and(|prefix| prefix.eq_ignore_ascii_case("@comment"))
}

#[derive(Debug)]
struct DirectiveShape {
    name: Option<SyntaxToken>,
    value_range: TextRange,
    delimiter: EntryDelimiter,
    trailing_comma: bool,
}

fn directive_shape(source: &str, range: TextRange, has_name: bool) -> DirectiveShape {
    let Some(raw) = source_slice(source, range) else {
        return DirectiveShape {
            name: None,
            value_range: TextRange::new(range.start, range.start),
            delimiter: EntryDelimiter::Unknown,
            trailing_comma: false,
        };
    };
    let bytes = raw.as_bytes();
    let open_offset = bytes.iter().position(|byte| matches!(*byte, b'{' | b'('));
    let Some(open_offset) = open_offset else {
        return DirectiveShape {
            name: None,
            value_range: TextRange::new(range.end, range.end),
            delimiter: EntryDelimiter::Unknown,
            trailing_comma: false,
        };
    };
    let delimiter = if bytes[open_offset] == b'{' {
        EntryDelimiter::Braces
    } else {
        EntryDelimiter::Parentheses
    };
    let mut body_start = open_offset + 1;
    let mut body_end = bytes.len();
    while body_end > body_start && bytes[body_end - 1].is_ascii_whitespace() {
        body_end -= 1;
    }
    if body_end > body_start && matches!(bytes[body_end - 1], b'}' | b')') {
        body_end -= 1;
    }
    while body_end > body_start && bytes[body_end - 1].is_ascii_whitespace() {
        body_end -= 1;
    }
    let trailing_comma = body_end > body_start && bytes[body_end - 1] == b',';
    if trailing_comma {
        body_end -= 1;
        while body_end > body_start && bytes[body_end - 1].is_ascii_whitespace() {
            body_end -= 1;
        }
    }
    while body_start < body_end && bytes[body_start].is_ascii_whitespace() {
        body_start += 1;
    }

    let (name, value_start) = if has_name {
        let name_start = body_start;
        let mut name_end = name_start;
        while name_end < body_end && is_identifier_byte(bytes[name_end]) {
            name_end += 1;
        }
        let mut equals = name_end;
        while equals < body_end && bytes[equals].is_ascii_whitespace() {
            equals += 1;
        }
        if equals < body_end && bytes[equals] == b'=' {
            equals += 1;
        }
        while equals < body_end && bytes[equals].is_ascii_whitespace() {
            equals += 1;
        }
        let token_range = absolute_subrange(range, name_start, name_end);
        (
            Some(SyntaxToken::new(
                raw.get(name_start..name_end).unwrap_or_default(),
                token_range,
            )),
            equals,
        )
    } else {
        (None, body_start)
    };
    DirectiveShape {
        name,
        value_range: absolute_subrange(range, value_start, body_end),
        delimiter,
        trailing_comma,
    }
}

fn append_gap(
    source: &str,
    start: usize,
    end: usize,
    text: &mut Vec<TextNode>,
    comments: &mut Vec<CommentNode>,
    blocks: &mut Vec<SyntaxBlock>,
) {
    let bytes = source.as_bytes();
    let mut cursor = start;
    while cursor < end {
        let percent = bytes[cursor..end]
            .iter()
            .position(|byte| *byte == b'%')
            .map(|offset| cursor + offset);
        let Some(percent) = percent else {
            push_text(cursor, end, text, blocks);
            break;
        };
        push_text(cursor, percent, text, blocks);
        let comment_end = bytes[percent..end]
            .iter()
            .position(|byte| matches!(*byte, b'\n' | b'\r'))
            .map_or(end, |offset| percent + offset);
        let index = comments.len();
        comments.push(CommentNode {
            range: text_range(percent, comment_end),
            content_range: text_range(percent + 1, comment_end),
            kind: CommentKind::Percent,
        });
        blocks.push(SyntaxBlock::Comment(index));
        cursor = comment_end;
        if cursor == percent {
            cursor += 1;
        }
    }
}

fn push_text(start: usize, end: usize, text: &mut Vec<TextNode>, blocks: &mut Vec<SyntaxBlock>) {
    if start >= end {
        return;
    }
    let index = text.len();
    text.push(TextNode {
        range: text_range(start, end),
    });
    blocks.push(SyntaxBlock::Text(index));
}

fn map_diagnostic(
    diagnostic: &bibtex_parser::Diagnostic,
    source_id: &SourceId,
    index: usize,
) -> Diagnostic {
    let range = span_range(diagnostic.source);
    let severity = match diagnostic.severity {
        BackendSeverity::Error => Severity::Error,
        BackendSeverity::Warning => Severity::Warning,
        BackendSeverity::Info => Severity::Information,
    };
    let code = syntax_rule_code(diagnostic.code.as_str());
    Diagnostic {
        id: DiagnosticId::new(format!(
            "syntax:{}:{}:{}",
            code.as_str(),
            range.start,
            index
        )),
        code,
        severity,
        blocking: severity == Severity::Error,
        message: diagnostic.message.clone(),
        primary_location: diagnostic
            .source
            .map(|_| SourceLocation::new(source_id.clone(), range)),
        related_locations: Vec::new(),
        notes: diagnostic.snippet.clone().into_iter().collect(),
        fixes: Vec::new(),
    }
}

fn syntax_rule_code(code: &str) -> RuleCode {
    let stable = match code {
        "missing-entry-key" => "BIB-SYNTAX-102",
        "missing-field-separator" => "BIB-SYNTAX-103",
        "expected-field-name" => "BIB-SYNTAX-104",
        "empty-field-value" => "BIB-SYNTAX-105",
        "expected-value-atom" => "BIB-SYNTAX-106",
        "bad-field-boundary" => "BIB-SYNTAX-107",
        "bad-value-boundary" => "BIB-SYNTAX-108",
        "unclosed-entry" => "BIB-SYNTAX-109",
        "unclosed-braced-value" => "BIB-SYNTAX-110",
        "unclosed-quoted-value" => "BIB-SYNTAX-111",
        _ => "BIB-SYNTAX-101",
    };
    RuleCode::new(stable)
}

fn panic_fallback(source: Arc<str>, options: ParseOptions) -> SyntaxDocument {
    error_fallback(
        source,
        options,
        "parser backend panicked; input was retained losslessly".to_string(),
    )
}

fn error_fallback(source: Arc<str>, options: ParseOptions, message: String) -> SyntaxDocument {
    let range = text_range(0, source.len());
    let diagnostic = Diagnostic {
        id: DiagnosticId::new("syntax:BIB-SYNTAX-112:0:0"),
        code: RuleCode::new("BIB-SYNTAX-112"),
        severity: Severity::Error,
        blocking: true,
        message: message.clone(),
        primary_location: Some(SourceLocation::new(options.source_id.clone(), range)),
        related_locations: Vec::new(),
        notes: Vec::new(),
        fixes: Vec::new(),
    };
    SyntaxDocument::from_parts(DocumentParts {
        source,
        source_id: options.source_id,
        mode: options.mode,
        blocks: vec![SyntaxBlock::Failed(0)],
        text: Vec::new(),
        entries: Vec::new(),
        strings: Vec::new(),
        preambles: Vec::new(),
        comments: Vec::new(),
        failed_blocks: vec![FailedBlock { range, message }],
        diagnostics: vec![diagnostic],
        summary: SyntaxSummary {
            status: ParseStatus::Failed,
            failed_blocks: 1,
            errors: 1,
            ..SyntaxSummary::default()
        },
    })
}

fn find_open_delimiter(
    source: &str,
    entry_range: TextRange,
    type_range: TextRange,
) -> Option<TextRange> {
    find_any_byte_between(source, type_range.end, entry_range.end, b"{(")
}

fn find_close_delimiter(
    source: &str,
    range: TextRange,
    delimiter: EntryDelimiter,
) -> Option<TextRange> {
    let close = delimiter.close()? as u8;
    let raw = source_slice(source, range)?;
    let offset = raw.as_bytes().iter().rposition(|byte| *byte == close)?;
    Some(absolute_subrange(range, offset, offset + 1))
}

fn find_byte_between(source: &str, start: u32, end: u32, byte: u8) -> Option<TextRange> {
    find_any_byte_between(source, start, end, &[byte])
}

fn find_any_byte_between(source: &str, start: u32, end: u32, wanted: &[u8]) -> Option<TextRange> {
    let start = start as usize;
    let end = (end as usize).min(source.len());
    let bytes = source.as_bytes().get(start..end)?;
    let offset = bytes.iter().position(|byte| wanted.contains(byte))?;
    Some(text_range(start + offset, start + offset + 1))
}

fn span_range(span: Option<bibtex_parser::SourceSpan>) -> TextRange {
    span.map_or_else(TextRange::default, |span| {
        text_range(span.byte_start, span.byte_end)
    })
}

fn source_slice(source: &str, range: TextRange) -> Option<&str> {
    source.get(range.start as usize..range.end as usize)
}

fn slice_or(source: &str, range: TextRange, fallback: &str) -> String {
    source_slice(source, range).unwrap_or(fallback).to_string()
}

fn absolute_subrange(parent: TextRange, start: usize, end: usize) -> TextRange {
    TextRange::new(
        parent.start.saturating_add(saturating_u32(start)),
        parent.start.saturating_add(saturating_u32(end)),
    )
}

fn text_range(start: usize, end: usize) -> TextRange {
    TextRange::new(saturating_u32(start), saturating_u32(end))
}

fn saturating_u32(value: usize) -> u32 {
    u32::try_from(value).unwrap_or(u32::MAX)
}

fn is_identifier_byte(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-' | b':' | b'.')
}
