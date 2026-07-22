use crate::{ValueAtom, ValueAtomKind, ValueExpression};
use bibmgr_model::TextRange;

pub(crate) fn lex_value(source: &str, range: TextRange) -> ValueExpression {
    let start = range.start as usize;
    let end = (range.end as usize).min(source.len());
    if start > end || source.get(start..end).is_none() {
        return ValueExpression {
            range,
            ..ValueExpression::default()
        };
    }

    let bytes = source.as_bytes();
    let mut pos = start;
    let mut atoms = Vec::new();
    let mut concatenation_ranges = Vec::new();

    while pos < end {
        pos = skip_ascii_space(bytes, pos, end);
        if pos >= end {
            break;
        }
        if bytes[pos] == b'#' {
            concatenation_ranges.push(text_range(pos, pos + 1));
            pos += 1;
            continue;
        }

        let atom_start = pos;
        let (atom_end, content_start, content_end, kind) = match bytes[pos] {
            b'{' => scan_braced(bytes, pos, end),
            b'"' => scan_quoted(bytes, pos, end),
            _ => scan_bare(bytes, pos, end),
        };
        let progressed_end = atom_end.max(pos + 1).min(end);
        atoms.push(ValueAtom {
            range: text_range(atom_start, progressed_end),
            content_range: text_range(content_start, content_end),
            kind,
        });
        pos = progressed_end;
    }

    ValueExpression {
        range,
        atoms,
        concatenation_ranges,
    }
}

fn scan_braced(bytes: &[u8], start: usize, end: usize) -> (usize, usize, usize, ValueAtomKind) {
    let mut pos = start + 1;
    let mut depth = 1_u32;
    while pos < end {
        match bytes[pos] {
            b'\\' => pos = (pos + 2).min(end),
            b'{' => {
                depth = depth.saturating_add(1);
                pos += 1;
            }
            b'}' => {
                depth = depth.saturating_sub(1);
                if depth == 0 {
                    return (
                        pos + 1,
                        start + 1,
                        pos,
                        ValueAtomKind::Braced { closed: true },
                    );
                }
                pos += 1;
            }
            _ => pos += 1,
        }
    }
    (end, start + 1, end, ValueAtomKind::Braced { closed: false })
}

fn scan_quoted(bytes: &[u8], start: usize, end: usize) -> (usize, usize, usize, ValueAtomKind) {
    let mut pos = start + 1;
    let mut brace_depth = 0_u32;
    while pos < end {
        match bytes[pos] {
            b'\\' => pos = (pos + 2).min(end),
            b'{' => {
                brace_depth = brace_depth.saturating_add(1);
                pos += 1;
            }
            b'}' => {
                brace_depth = brace_depth.saturating_sub(1);
                pos += 1;
            }
            b'"' if brace_depth == 0 => {
                return (
                    pos + 1,
                    start + 1,
                    pos,
                    ValueAtomKind::Quoted { closed: true },
                );
            }
            _ => pos += 1,
        }
    }
    (end, start + 1, end, ValueAtomKind::Quoted { closed: false })
}

fn scan_bare(bytes: &[u8], start: usize, end: usize) -> (usize, usize, usize, ValueAtomKind) {
    let mut pos = start;
    while pos < end
        && !bytes[pos].is_ascii_whitespace()
        && !matches!(bytes[pos], b'#' | b',' | b'}' | b')')
    {
        pos += 1;
    }
    if pos == start {
        pos += 1;
    }
    let raw = &bytes[start..pos];
    let kind = if raw.iter().all(u8::is_ascii_digit) && !raw.is_empty() {
        ValueAtomKind::Number
    } else if raw
        .iter()
        .all(|byte| byte.is_ascii_alphanumeric() || matches!(*byte, b'_' | b'-' | b':' | b'.'))
    {
        ValueAtomKind::Macro
    } else {
        ValueAtomKind::Invalid
    };
    (pos, start, pos, kind)
}

fn skip_ascii_space(bytes: &[u8], mut pos: usize, end: usize) -> usize {
    while pos < end && bytes[pos].is_ascii_whitespace() {
        pos += 1;
    }
    pos
}

fn text_range(start: usize, end: usize) -> TextRange {
    TextRange::new(saturating_u32(start), saturating_u32(end))
}

fn saturating_u32(value: usize) -> u32 {
    u32::try_from(value).unwrap_or(u32::MAX)
}
