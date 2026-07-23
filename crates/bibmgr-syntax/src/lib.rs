//! Lossless, parser-independent BibTeX concrete syntax.
//!
//! The upstream parser is deliberately hidden in the private adapter module. Every public
//! type is owned by bibmgr and is serializable. The original input is retained
//! as an [`Arc<str>`], so an untouched document always round-trips byte for
//! byte, including malformed input.

mod adapter;
mod value_lexer;

use bibmgr_model::{Diagnostic, LineColumn, SourceId, TextRange};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

/// Parser behavior requested by the caller.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum ParseMode {
    /// Report a strict parse failure while still retaining a recoverable CST.
    #[default]
    Strict,
    /// Recover entries and fields after malformed input where possible.
    Tolerant,
}

/// Options for parsing one BibTeX document.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ParseOptions {
    pub mode: ParseMode,
    pub source_id: SourceId,
}

impl Default for ParseOptions {
    fn default() -> Self {
        Self {
            mode: ParseMode::Strict,
            source_id: SourceId::new("input"),
        }
    }
}

impl ParseOptions {
    pub fn strict() -> Self {
        Self::default()
    }

    pub fn tolerant() -> Self {
        Self {
            mode: ParseMode::Tolerant,
            ..Self::default()
        }
    }

    #[must_use]
    pub fn with_source_id(mut self, source_id: impl Into<SourceId>) -> Self {
        self.source_id = source_id.into();
        self
    }
}

/// Overall result of syntactic analysis.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum ParseStatus {
    #[default]
    Ok,
    Partial,
    Failed,
}

/// Small serializable view suitable for frontends.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct SyntaxSummary {
    pub status: ParseStatus,
    pub entries: usize,
    pub strings: usize,
    pub preambles: usize,
    pub comments: usize,
    pub failed_blocks: usize,
    pub recovered_entries: usize,
    pub errors: usize,
    pub warnings: usize,
}

/// A token whose spelling and UTF-8 byte range are retained exactly.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SyntaxToken {
    pub text: String,
    pub range: TextRange,
}

impl SyntaxToken {
    pub fn new(text: impl Into<String>, range: TextRange) -> Self {
        Self {
            text: text.into(),
            range,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EntryDelimiter {
    Braces,
    Parentheses,
    Unknown,
}

impl EntryDelimiter {
    pub const fn open(self) -> Option<char> {
        match self {
            Self::Braces => Some('{'),
            Self::Parentheses => Some('('),
            Self::Unknown => None,
        }
    }

    pub const fn close(self) -> Option<char> {
        match self {
            Self::Braces => Some('}'),
            Self::Parentheses => Some(')'),
            Self::Unknown => None,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EntryStatus {
    Complete,
    Recovered,
}

/// One value atom. Delimiter bytes are included in `range` and excluded from
/// `content_range` for quoted/braced atoms.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ValueAtom {
    pub range: TextRange,
    pub content_range: TextRange,
    pub kind: ValueAtomKind,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ValueAtomKind {
    Braced { closed: bool },
    Quoted { closed: bool },
    Number,
    Macro,
    Invalid,
}

/// A lossless BibTeX value expression, including all `#` separators.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct ValueExpression {
    pub range: TextRange,
    pub atoms: Vec<ValueAtom>,
    pub concatenation_ranges: Vec<TextRange>,
}

impl ValueExpression {
    pub fn is_concatenated(&self) -> bool {
        !self.concatenation_ranges.is_empty()
    }
}

/// A field in source order. Repeated names remain repeated entries in this
/// vector rather than being collapsed into a map.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FieldNode {
    pub range: TextRange,
    pub name: SyntaxToken,
    pub equals_range: Option<TextRange>,
    pub value: ValueExpression,
    pub comma_range: Option<TextRange>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EntryNode {
    pub range: TextRange,
    pub at_range: TextRange,
    pub entry_type: SyntaxToken,
    pub citation_key: SyntaxToken,
    pub delimiter: EntryDelimiter,
    pub open_delimiter_range: Option<TextRange>,
    pub close_delimiter_range: Option<TextRange>,
    pub fields: Vec<FieldNode>,
    /// Percent comments found between entry fields. These comments remain
    /// nested in the entry rather than becoming overlapping document blocks.
    #[serde(default)]
    pub inline_comments: Vec<CommentNode>,
    pub trailing_comma: bool,
    pub status: EntryStatus,
}

impl EntryNode {
    pub fn field(&self, name: &str) -> Option<&FieldNode> {
        self.fields
            .iter()
            .find(|field| field.name.text.eq_ignore_ascii_case(name))
    }

    pub fn fields_named<'a>(&'a self, name: &'a str) -> impl Iterator<Item = &'a FieldNode> {
        self.fields
            .iter()
            .filter(move |field| field.name.text.eq_ignore_ascii_case(name))
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StringNode {
    pub range: TextRange,
    pub name: SyntaxToken,
    pub value: ValueExpression,
    pub delimiter: EntryDelimiter,
    pub trailing_comma: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PreambleNode {
    pub range: TextRange,
    pub value: ValueExpression,
    pub delimiter: EntryDelimiter,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CommentKind {
    Percent,
    Explicit,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CommentNode {
    pub range: TextRange,
    pub content_range: TextRange,
    pub kind: CommentKind,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TextNode {
    pub range: TextRange,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FailedBlock {
    pub range: TextRange,
    pub message: String,
}

/// Source-order document block. Payload indices address the corresponding
/// slices on [`SyntaxDocument`].
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "index", rename_all = "snake_case")]
pub enum SyntaxBlock {
    Text(usize),
    Entry(usize),
    String(usize),
    Preamble(usize),
    Comment(usize),
    Failed(usize),
}

/// An owned, shareable and lossless BibTeX document.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SyntaxDocument {
    source: Arc<str>,
    source_id: SourceId,
    mode: ParseMode,
    blocks: Vec<SyntaxBlock>,
    text: Vec<TextNode>,
    entries: Vec<EntryNode>,
    strings: Vec<StringNode>,
    preambles: Vec<PreambleNode>,
    comments: Vec<CommentNode>,
    failed_blocks: Vec<FailedBlock>,
    diagnostics: Vec<Diagnostic>,
    summary: SyntaxSummary,
}

impl SyntaxDocument {
    /// The exact original source. No formatter is involved.
    pub fn to_source(&self) -> &str {
        &self.source
    }

    pub fn source(&self) -> &Arc<str> {
        &self.source
    }

    pub fn source_id(&self) -> &SourceId {
        &self.source_id
    }

    pub const fn mode(&self) -> ParseMode {
        self.mode
    }

    pub fn blocks(&self) -> &[SyntaxBlock] {
        &self.blocks
    }

    /// Resolve a source-order block reference to its byte range.
    pub fn block_range(&self, block: &SyntaxBlock) -> Option<TextRange> {
        match *block {
            SyntaxBlock::Text(index) => self.text.get(index).map(|node| node.range),
            SyntaxBlock::Entry(index) => self.entries.get(index).map(|node| node.range),
            SyntaxBlock::String(index) => self.strings.get(index).map(|node| node.range),
            SyntaxBlock::Preamble(index) => self.preambles.get(index).map(|node| node.range),
            SyntaxBlock::Comment(index) => self.comments.get(index).map(|node| node.range),
            SyntaxBlock::Failed(index) => self.failed_blocks.get(index).map(|node| node.range),
        }
    }

    pub fn block_source(&self, block: &SyntaxBlock) -> Option<&str> {
        self.slice(self.block_range(block)?)
    }

    pub fn text_blocks(&self) -> &[TextNode] {
        &self.text
    }

    pub fn entries(&self) -> &[EntryNode] {
        &self.entries
    }

    pub fn strings(&self) -> &[StringNode] {
        &self.strings
    }

    pub fn preambles(&self) -> &[PreambleNode] {
        &self.preambles
    }

    pub fn comments(&self) -> &[CommentNode] {
        &self.comments
    }

    pub fn failed_blocks(&self) -> &[FailedBlock] {
        &self.failed_blocks
    }

    pub fn diagnostics(&self) -> &[Diagnostic] {
        &self.diagnostics
    }

    pub fn summary(&self) -> &SyntaxSummary {
        &self.summary
    }

    /// Slice the retained input at a checked UTF-8 byte range.
    pub fn slice(&self, range: TextRange) -> Option<&str> {
        if !range.is_valid() {
            return None;
        }
        let start = usize::try_from(range.start).ok()?;
        let end = usize::try_from(range.end).ok()?;
        self.source.get(start..end)
    }

    /// Convert a valid UTF-8 byte offset to a one-based display position.
    pub fn line_column(&self, offset: u32) -> Option<LineColumn> {
        let offset = usize::try_from(offset).ok()?;
        if offset > self.source.len() || !self.source.is_char_boundary(offset) {
            return None;
        }
        let mut line = 1_u32;
        let mut column = 1_u32;
        for character in self.source[..offset].chars() {
            if character == '\n' {
                line = line.saturating_add(1);
                column = 1;
            } else {
                column = column.saturating_add(1);
            }
        }
        Some(LineColumn { line, column })
    }

    pub(crate) fn from_parts(parts: DocumentParts) -> Self {
        Self {
            source: parts.source,
            source_id: parts.source_id,
            mode: parts.mode,
            blocks: parts.blocks,
            text: parts.text,
            entries: parts.entries,
            strings: parts.strings,
            preambles: parts.preambles,
            comments: parts.comments,
            failed_blocks: parts.failed_blocks,
            diagnostics: parts.diagnostics,
            summary: parts.summary,
        }
    }
}

#[derive(Debug)]
pub(crate) struct DocumentParts {
    pub source: Arc<str>,
    pub source_id: SourceId,
    pub mode: ParseMode,
    pub blocks: Vec<SyntaxBlock>,
    pub text: Vec<TextNode>,
    pub entries: Vec<EntryNode>,
    pub strings: Vec<StringNode>,
    pub preambles: Vec<PreambleNode>,
    pub comments: Vec<CommentNode>,
    pub failed_blocks: Vec<FailedBlock>,
    pub diagnostics: Vec<Diagnostic>,
    pub summary: SyntaxSummary,
}

/// Parse a complete BibTeX document. This function catches parser panics and
/// turns them into a failed, lossless document diagnostic.
pub fn parse(source: &str, options: ParseOptions) -> SyntaxDocument {
    adapter::parse(source, options)
}

/// Convenience equivalent to [`parse`] using strict defaults.
pub fn parse_strict(source: &str) -> SyntaxDocument {
    parse(source, ParseOptions::strict())
}

/// Convenience equivalent to [`parse`] using tolerant defaults.
pub fn parse_tolerant(source: &str) -> SyntaxDocument {
    parse(source, ParseOptions::tolerant())
}
