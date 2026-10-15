//! Explainable record comparison. No persistence or deployment policy lives here.
use crate::{BibliographicRecord, Person, Sourced, ValueStatus};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use unicode_normalization::UnicodeNormalization;

pub const COMPARISON_VERSION: u32 = 1;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ComparisonRecord {
    pub version: u32,
    pub citation_key: String,
    pub title: Option<String>,
    pub dois: BTreeSet<String>,
    pub arxiv: BTreeSet<String>,
    pub arxiv_families: BTreeSet<String>,
    pub authors: Option<BTreeSet<String>>,
    pub year: Option<i32>,
    pub venue: Option<String>,
    pub volume: Option<String>,
    pub number: Option<String>,
    pub pages: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Agreement {
    Match,
    Different,
    Missing,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FieldComparison {
    pub field: String,
    pub agreement: Agreement,
    pub left: Vec<String>,
    pub right: Vec<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DuplicateKind {
    Identifier,
    ArxivFamily,
    CorroboratedTitle,
    Title,
    CitationKey,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DuplicateComparison {
    pub kind: DuplicateKind,
    pub fields: Vec<FieldComparison>,
}

fn reliable(status: ValueStatus) -> bool {
    !matches!(
        status,
        ValueStatus::Unresolved | ValueStatus::Ambiguous | ValueStatus::Conflicting
    )
}

fn reliable_value<T>(record: &BibliographicRecord, value: &Sourced<T>) -> bool {
    reliable(value.status)
        && !value
            .origins
            .iter()
            .filter_map(|o| o.field_name.as_deref())
            .any(|name| {
                record
                    .conflicts
                    .iter()
                    .any(|c| c.field.eq_ignore_ascii_case(name))
                    || record
                        .ambiguities
                        .iter()
                        .flat_map(|a| &a.origins)
                        .filter_map(|o| o.field_name.as_deref())
                        .any(|field| field.eq_ignore_ascii_case(name))
            })
}

/// Conservative text normalization: retain punctuation and digits. Unsupported
/// TeX/math makes the value unavailable, never an empty or guessed title.
pub fn normalize_comparison_text(input: &str) -> Option<String> {
    let mut output = String::new();
    let mut chars = input.chars().peekable();
    while let Some(ch) = chars.next() {
        match ch {
            '{' | '}' => {}
            '~' => output.push(' '),
            '$' | '^' | '_' => return None,
            '\\' => {
                let next = chars.next()?;
                if "&%#_{}".contains(next) {
                    output.push(next);
                } else if matches!(next, ' ' | ',' | ';' | '!') {
                    output.push(' ');
                } else if matches!(next, '\'' | '"' | '`' | '^' | '~' | '=') {
                    let base = if chars.peek() == Some(&'{') {
                        chars.next();
                        chars.next()?
                    } else {
                        chars.next()?
                    };
                    if !base.is_alphabetic() {
                        return None;
                    }
                    output.push(base);
                    output.push(match next {
                        '\'' => '\u{301}',
                        '"' => '\u{308}',
                        '`' => '\u{300}',
                        '^' => '\u{302}',
                        '~' => '\u{303}',
                        _ => '\u{304}',
                    });
                } else {
                    let mut command = String::from(next);
                    while chars.peek().is_some_and(char::is_ascii_alphabetic) {
                        command.push(chars.next()?);
                    }
                    match command.as_str() {
                        "textit" | "textbf" | "textrm" | "emph" | "textsc" | "mathrm"
                            if chars.peek() == Some(&'{') => {}
                        "LaTeX" => output.push_str("LaTeX"),
                        "TeX" => output.push_str("TeX"),
                        _ => return None,
                    }
                }
            }
            _ => output.push(ch),
        }
    }
    let normalized = output
        .nfc()
        .flat_map(char::to_lowercase)
        .collect::<String>();
    let normalized = normalized.split_whitespace().collect::<Vec<_>>().join(" ");
    (!normalized.is_empty()).then_some(normalized)
}

fn person_key(person: &Person) -> Option<String> {
    if let Some(literal) = &person.literal {
        return normalize_comparison_text(literal);
    }
    if person.family.is_empty() {
        return None;
    }
    let family = normalize_comparison_text(
        &[
            person.prefix.join(" "),
            person.family.join(" "),
            person.suffix.join(" "),
        ]
        .join(" "),
    )?;
    // Initials are supporting evidence only, never a strong identity.
    let initials: String = person
        .given
        .iter()
        .flat_map(|name| name.split(['-', '.']))
        .filter_map(|part| part.chars().next())
        .flat_map(char::to_lowercase)
        .collect();
    Some(format!("{family}|{initials}"))
}

fn arxiv_family(value: &str) -> String {
    let value = value.to_ascii_lowercase();
    if let Some((base, version)) = value.rsplit_once('v') {
        if !version.is_empty() && version.bytes().all(|b| b.is_ascii_digit()) {
            return base.to_owned();
        }
    }
    value
}

pub fn comparison_record(record: &BibliographicRecord) -> ComparisonRecord {
    let text_field = |name: &str| {
        if record
            .conflicts
            .iter()
            .any(|c| c.field.eq_ignore_ascii_case(name))
        {
            return None;
        }
        let values: BTreeSet<_> = record
            .extra_fields
            .iter()
            .filter(|f| f.name.eq_ignore_ascii_case(name))
            .filter_map(|f| {
                if f.value.unresolved_macros.is_empty() && f.value.candidates.len() <= 1 {
                    f.value.resolved.as_deref()
                } else {
                    None
                }
            })
            .collect();
        if values.len() != 1 {
            return None;
        }
        normalize_comparison_text(values.first()?)
    };
    let arxiv: BTreeSet<_> = record
        .identifiers
        .arxiv
        .iter()
        .filter(|v| reliable_value(record, v))
        .map(|v| v.value.as_str().to_ascii_lowercase())
        .collect();
    let authors =
        if record.authors.is_empty() || record.authors.iter().any(|v| !reliable_value(record, v)) {
            None
        } else {
            record
                .authors
                .iter()
                .map(|v| person_key(&v.value))
                .collect()
        };
    ComparisonRecord {
        version: COMPARISON_VERSION,
        citation_key: record.citation_key.value.as_str().to_ascii_lowercase(),
        title: record
            .title
            .as_ref()
            .filter(|v| reliable_value(record, v))
            .and_then(|v| normalize_comparison_text(v.value.as_str())),
        dois: record
            .identifiers
            .dois
            .iter()
            .filter(|v| reliable_value(record, v))
            .map(|v| v.value.as_str().to_ascii_lowercase())
            .collect(),
        arxiv_families: arxiv.iter().map(|v| arxiv_family(v)).collect(),
        arxiv,
        authors,
        year: record
            .date
            .as_ref()
            .filter(|v| reliable_value(record, v))
            .and_then(|v| v.value.year),
        venue: record
            .venue
            .as_ref()
            .filter(|v| reliable_value(record, v))
            .and_then(|v| {
                v.value
                    .venue_id
                    .as_ref()
                    .map(|id| format!("id:{id}"))
                    .or_else(|| {
                        normalize_comparison_text(&v.value.raw).map(|raw| format!("raw:{raw}"))
                    })
            }),
        volume: text_field("volume"),
        number: text_field("number"),
        pages: text_field("pages").map(|s| {
            s.replace("--", "-")
                .replace(['–', '—'], "-")
                .replace(' ', "")
        }),
    }
}

fn evidence(field: &str, left: Vec<String>, right: Vec<String>, overlap: bool) -> FieldComparison {
    let agreement = if left.is_empty() || right.is_empty() {
        Agreement::Missing
    } else if left == right || (overlap && left.iter().any(|v| right.contains(v))) {
        Agreement::Match
    } else {
        Agreement::Different
    };
    FieldComparison {
        field: field.to_owned(),
        agreement,
        left,
        right,
    }
}

/// Candidate detection and explanation are independent of any action policy.
pub fn compare_records(
    left: &ComparisonRecord,
    right: &ComparisonRecord,
) -> Option<DuplicateComparison> {
    let values = |value: &Option<String>| value.clone().into_iter().collect();
    let set = |value: &BTreeSet<String>| value.iter().cloned().collect();
    let fields = vec![
        evidence(
            "citation_key",
            (!left.citation_key.is_empty())
                .then(|| left.citation_key.clone())
                .into_iter()
                .collect(),
            (!right.citation_key.is_empty())
                .then(|| right.citation_key.clone())
                .into_iter()
                .collect(),
            false,
        ),
        evidence("title", values(&left.title), values(&right.title), false),
        evidence("doi", set(&left.dois), set(&right.dois), true),
        evidence("arxiv", set(&left.arxiv), set(&right.arxiv), true),
        evidence(
            "arxiv_family",
            set(&left.arxiv_families),
            set(&right.arxiv_families),
            true,
        ),
        evidence(
            "authors",
            left.authors.as_ref().map_or_else(Vec::new, set),
            right.authors.as_ref().map_or_else(Vec::new, set),
            false,
        ),
        evidence(
            "year",
            values(&left.year.map(|y| y.to_string())),
            values(&right.year.map(|y| y.to_string())),
            false,
        ),
        evidence("venue", values(&left.venue), values(&right.venue), false),
        evidence("volume", values(&left.volume), values(&right.volume), false),
        evidence("number", values(&left.number), values(&right.number), false),
        evidence("pages", values(&left.pages), values(&right.pages), false),
    ];
    let matches = |name: &str| {
        fields
            .iter()
            .any(|f| f.field == name && f.agreement == Agreement::Match)
    };
    let kind = if matches("doi") || matches("arxiv") {
        DuplicateKind::Identifier
    } else if matches("arxiv_family") {
        DuplicateKind::ArxivFamily
    } else if matches("title") {
        let conflict = fields.iter().any(|f| {
            !matches!(f.field.as_str(), "citation_key" | "authors")
                && f.agreement == Agreement::Different
        });
        // Require bibliographic coordinates, not just title + author/year.
        if !conflict
            && matches("year")
            && matches("venue")
            && (matches("pages") || (matches("authors") && matches("volume")))
        {
            DuplicateKind::CorroboratedTitle
        } else {
            DuplicateKind::Title
        }
    } else if matches("citation_key") {
        DuplicateKind::CitationKey
    } else {
        return None;
    };
    Some(DuplicateComparison { kind, fields })
}
