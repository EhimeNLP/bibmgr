//! Domain-level bibliography model and CST-to-semantics analysis.
//!
//! These DTOs are intentionally independent of the parser backend. Every
//! derived value carries source provenance, confidence and derivation status;
//! ambiguous and conflicting input is retained rather than silently replaced.

mod analyze;
mod names;

use bibmgr_model::{Diagnostic, SourceId, TextRange};
use bibmgr_syntax::SyntaxDocument;
use serde::{Deserialize, Serialize};
use std::fmt;

macro_rules! string_value {
    ($name:ident) => {
        #[derive(
            Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize, Default,
        )]
        #[serde(transparent)]
        pub struct $name(pub String);

        impl $name {
            pub fn new(value: impl Into<String>) -> Self {
                Self(value.into())
            }

            pub fn as_str(&self) -> &str {
                &self.0
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str(&self.0)
            }
        }

        impl From<&str> for $name {
            fn from(value: &str) -> Self {
                Self(value.to_owned())
            }
        }

        impl From<String> for $name {
            fn from(value: String) -> Self {
                Self(value)
            }
        }
    };
}

string_value!(CitationKey);
string_value!(Title);
string_value!(Doi);
string_value!(ArxivId);
string_value!(Isbn);
string_value!(Issn);
string_value!(Url);

/// BibTeX fields whose values are identifier-like bytes rather than TeX prose.
///
/// Validation and export share this classification so that a value accepted as
/// a literal identifier is never rewritten by the serializer later.
pub const RAW_IDENTIFIER_FIELD_NAMES: &[&str] = &[
    "url",
    "doi",
    "file",
    "eprint",
    "arxiv",
    "archiveprefix",
    "eprinttype",
    "primaryclass",
    "eprintclass",
    "isbn",
    "isbn-10",
    "isbn-13",
    "issn",
    "eissn",
    "coden",
    "lccn",
    "pmid",
    "pmcid",
    "pubmed",
    "eid",
    "pid",
    "islrn",
    "articleno",
    "crossref",
    "archived",
];

pub fn is_raw_identifier_field(field_name: &str) -> bool {
    RAW_IDENTIFIER_FIELD_NAMES
        .iter()
        .any(|candidate| candidate.eq_ignore_ascii_case(field_name))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum ValueStatus {
    #[default]
    Explicit,
    Parsed,
    Resolved,
    Inferred,
    Normalized,
    ExternallyVerified,
    Unresolved,
    Ambiguous,
    Conflicting,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum Confidence {
    High,
    Medium,
    Low,
    #[default]
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OriginKind {
    Entry,
    EntryType,
    CitationKey,
    Field,
    FieldName,
    FieldValue,
    /// The identifier token of a BibTeX macro use, either in an entry field
    /// or in another `@string` definition.
    MacroReference,
    /// The complete `@string` directive selected or considered while
    /// resolving a macro.
    StringDefinition,
    Inference,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SyntaxOrigin {
    pub source_id: SourceId,
    pub range: TextRange,
    pub kind: OriginKind,
    pub field_name: Option<String>,
}

impl SyntaxOrigin {
    pub fn new(source_id: SourceId, range: TextRange, kind: OriginKind) -> Self {
        Self {
            source_id,
            range,
            kind,
            field_name: None,
        }
    }

    #[must_use]
    pub fn for_field(mut self, field_name: impl Into<String>) -> Self {
        self.field_name = Some(field_name.into());
        self
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Sourced<T> {
    pub value: T,
    pub origins: Vec<SyntaxOrigin>,
    pub status: ValueStatus,
    pub confidence: Confidence,
}

impl<T> Sourced<T> {
    pub fn explicit(value: T, origin: SyntaxOrigin) -> Self {
        Self {
            value,
            origins: vec![origin],
            status: ValueStatus::Explicit,
            confidence: Confidence::High,
        }
    }

    pub fn map<U>(self, map: impl FnOnce(T) -> U) -> Sourced<U> {
        Sourced {
            value: map(self.value),
            origins: self.origins,
            status: self.status,
            confidence: self.confidence,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum WorkType {
    JournalArticle,
    ConferencePaper,
    Preprint,
    Book,
    InBook,
    InCollection,
    Thesis,
    TechnicalReport,
    Dataset,
    Software,
    WebResource,
    Miscellaneous,
    #[default]
    Unknown,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct Person {
    pub raw: String,
    pub given: Vec<String>,
    pub family: Vec<String>,
    pub prefix: Vec<String>,
    pub suffix: Vec<String>,
    pub literal: Option<String>,
}

impl Person {
    pub fn display_name(&self) -> String {
        if let Some(literal) = &self.literal {
            return literal.clone();
        }
        let mut parts = self.given.clone();
        parts.extend(self.prefix.clone());
        parts.extend(self.family.clone());
        let mut display = parts.join(" ");
        if !self.suffix.is_empty() {
            if !display.is_empty() {
                display.push_str(", ");
            }
            display.push_str(&self.suffix.join(" "));
        }
        display
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct PublicationDate {
    pub raw: String,
    pub year: Option<i32>,
    pub month: Option<u8>,
    pub day: Option<u8>,
}

/// Broad venue category supplied by a versioned venue registry.
///
/// Semantic extraction leaves this unresolved until the core facade matches
/// the source spelling to a registry entity.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum VenueKind {
    Conference,
    Journal,
    Workshop,
    BookSeries,
    Other,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct VenueRef {
    pub raw: String,
    pub venue_id: Option<String>,
    pub full_name: Option<String>,
    pub short_name: Option<String>,
    /// Present only when registry enrichment resolved the venue identity.
    pub kind: Option<VenueKind>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "name", rename_all = "snake_case")]
pub enum Repository {
    ArXiv,
    Other(String),
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Preprint {
    pub repository: Repository,
    pub identifier: String,
    pub version: Option<String>,
    pub primary_category: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct OtherIdentifier {
    pub scheme: String,
    pub value: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct Identifiers {
    #[serde(default)]
    pub dois: Vec<Sourced<Doi>>,
    #[serde(default)]
    pub arxiv: Vec<Sourced<ArxivId>>,
    #[serde(default)]
    pub isbns: Vec<Sourced<Isbn>>,
    #[serde(default)]
    pub issns: Vec<Sourced<Issn>>,
    #[serde(default)]
    pub other: Vec<Sourced<OtherIdentifier>>,
}

impl Identifiers {
    pub fn primary_doi(&self) -> Option<&Sourced<Doi>> {
        self.dois.first()
    }

    pub fn primary_arxiv(&self) -> Option<&Sourced<ArxivId>> {
        self.arxiv.first()
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct SemanticValue {
    pub raw: String,
    pub resolved: Option<String>,
    #[serde(default)]
    pub candidates: Vec<String>,
    #[serde(default)]
    pub unresolved_macros: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SemanticField {
    pub name: String,
    pub value: SemanticValue,
    pub origins: Vec<SyntaxOrigin>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SemanticCandidate {
    pub value: String,
    pub status: ValueStatus,
    pub confidence: Confidence,
    pub origins: Vec<SyntaxOrigin>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Ambiguity {
    pub kind: String,
    pub message: String,
    pub candidates: Vec<SemanticCandidate>,
    pub origins: Vec<SyntaxOrigin>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SemanticConflict {
    pub field: String,
    pub explicit_values: Vec<String>,
    pub inferred_values: Vec<String>,
    pub origins: Vec<SyntaxOrigin>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BibliographicRecord {
    pub citation_key: Sourced<CitationKey>,
    /// Original entry kind retained because multiple BibTeX kinds can map to
    /// one semantic [`WorkType`] without being interchangeable on export.
    pub entry_type: Sourced<String>,
    pub work_type: Sourced<WorkType>,
    pub title: Option<Sourced<Title>>,
    #[serde(default)]
    pub authors: Vec<Sourced<Person>>,
    #[serde(default)]
    pub editors: Vec<Sourced<Person>>,
    pub date: Option<Sourced<PublicationDate>>,
    pub venue: Option<Sourced<VenueRef>>,
    pub preprint: Option<Sourced<Preprint>>,
    pub identifiers: Identifiers,
    #[serde(default)]
    pub urls: Vec<Sourced<Url>>,
    #[serde(default)]
    pub extra_fields: Vec<SemanticField>,
    /// Fields whose value expression could not be fully evaluated. This keeps
    /// unresolved macro names and raw source text in the semantic layer.
    #[serde(default)]
    pub unresolved_values: Vec<SemanticField>,
    #[serde(default)]
    pub ambiguities: Vec<Ambiguity>,
    #[serde(default)]
    pub conflicts: Vec<SemanticConflict>,
    #[serde(default)]
    pub origins: Vec<SyntaxOrigin>,
}

impl BibliographicRecord {
    pub fn source_range(&self) -> Option<TextRange> {
        self.origins
            .iter()
            .find(|origin| origin.kind == OriginKind::Entry)
            .map(|origin| origin.range)
    }

    /// Whether registration would have to guess, discard, or silently choose
    /// among semantic values in this record.
    pub fn has_unresolved_semantics(&self) -> bool {
        let unresolved = |status| {
            matches!(
                status,
                ValueStatus::Unresolved | ValueStatus::Ambiguous | ValueStatus::Conflicting
            )
        };

        self.work_type.value == WorkType::Unknown
            || unresolved(self.citation_key.status)
            || unresolved(self.entry_type.status)
            || unresolved(self.work_type.status)
            || self
                .title
                .as_ref()
                .is_some_and(|value| unresolved(value.status))
            || self.authors.iter().any(|value| unresolved(value.status))
            || self.editors.iter().any(|value| unresolved(value.status))
            || self
                .date
                .as_ref()
                .is_some_and(|value| unresolved(value.status))
            || self
                .venue
                .as_ref()
                .is_some_and(|value| unresolved(value.status))
            || self
                .preprint
                .as_ref()
                .is_some_and(|value| unresolved(value.status))
            || self
                .identifiers
                .dois
                .iter()
                .any(|value| unresolved(value.status))
            || self
                .identifiers
                .arxiv
                .iter()
                .any(|value| unresolved(value.status))
            || self
                .identifiers
                .isbns
                .iter()
                .any(|value| unresolved(value.status))
            || self
                .identifiers
                .issns
                .iter()
                .any(|value| unresolved(value.status))
            || self
                .identifiers
                .other
                .iter()
                .any(|value| unresolved(value.status))
            || self.urls.iter().any(|value| unresolved(value.status))
            || !self.unresolved_values.is_empty()
            || !self.ambiguities.is_empty()
            || !self.conflicts.is_empty()
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct Bibliography {
    #[serde(default)]
    pub records: Vec<BibliographicRecord>,
    #[serde(default)]
    pub diagnostics: Vec<Diagnostic>,
}

impl Bibliography {
    pub fn has_unresolved_semantics(&self) -> bool {
        self.records
            .iter()
            .any(BibliographicRecord::has_unresolved_semantics)
    }
}

/// Convert a lossless CST into parser-independent bibliography semantics.
pub fn analyze(document: &SyntaxDocument) -> Bibliography {
    analyze::analyze(document)
}

pub use names::parse_people;

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeSet;

    #[test]
    fn raw_identifier_field_classification_is_unique_and_case_insensitive() {
        let unique = RAW_IDENTIFIER_FIELD_NAMES
            .iter()
            .map(|name| name.to_ascii_lowercase())
            .collect::<BTreeSet<_>>();

        assert_eq!(unique.len(), RAW_IDENTIFIER_FIELD_NAMES.len());
        assert!(RAW_IDENTIFIER_FIELD_NAMES
            .iter()
            .all(|name| is_raw_identifier_field(&name.to_ascii_uppercase())));
        assert!(!is_raw_identifier_field("title"));
    }
}
