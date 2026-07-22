//! Canonical, deterministic BibTeX generation from the parser-independent AST.

use bibmgr_model::{ProfileId, RuleCode};
use bibmgr_semantics::{
    BibliographicRecord, Bibliography, Person, Repository, SemanticField, ValueStatus, WorkType,
};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

pub const BUILTIN_EXPORT_PROFILE_IDS: &[&str] = &[
    "modern",
    "laboratory",
    "acl",
    "aaai",
    "acm-publications",
    "ieee-publications",
    "natbib-full-author-names",
    "springer-lncs",
    "ml-conferences",
    "lrec",
    "eamt",
    "ipsj-japanese",
    "ipsj-english",
    "jnlp-japanese",
    "jsai-journal",
    "classical-bst",
    "legacy-arxiv-article",
];

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "kebab-case")]
pub enum PreprintRepresentation {
    #[default]
    MiscEprint,
    MiscHowpublished,
    ArticleJournal,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "kebab-case")]
pub enum VenueStyle {
    Full,
    Short,
    #[default]
    AsRecorded,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "kebab-case")]
pub enum ValueDelimiter {
    #[default]
    Braces,
    Quotes,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "kebab-case")]
pub enum ExportFieldCase {
    Lowercase,
    #[default]
    Canonical,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "kebab-case")]
pub enum LineEnding {
    #[default]
    Lf,
    CrLf,
}

impl LineEnding {
    const fn as_str(self) -> &'static str {
        match self {
            Self::Lf => "\n",
            Self::CrLf => "\r\n",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "kebab-case")]
pub enum MonthFormat {
    #[default]
    Numeric,
    BibtexMacro,
}

/// Field projection applied after all semantic and extra fields are generated.
///
/// An absent allowlist keeps every candidate field. Names are compared without
/// regard to ASCII case, as required by BibTeX field semantics.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(default, deny_unknown_fields)]
pub struct ExportFieldSelection {
    pub allowed_fields: Option<Vec<String>>,
    pub excluded_fields: Vec<String>,
}

/// Standalone export configuration; it has no dependency on validation policy.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default = "ExportProfile::baseline", deny_unknown_fields)]
#[allow(clippy::struct_excessive_bools)]
pub struct ExportProfile {
    pub schema_version: String,
    pub profile: ProfileId,
    pub display_name: String,
    pub description: String,
    /// Validation policy used to check the generated BibTeX representation.
    /// This is explicit so custom export profile IDs never silently skip
    /// readiness validation.
    pub validation_profile: ProfileId,
    pub preprint_representation: PreprintRepresentation,
    pub venue_style: VenueStyle,
    pub month_format: MonthFormat,
    /// Target entry types understood by the bibliography style. An empty list
    /// keeps the general semantic-to-BibTeX mapping; a populated list also
    /// preserves an original entry type when the target style supports it.
    pub supported_entry_types: Vec<String>,
    pub field_order: Vec<String>,
    pub field_case: ExportFieldCase,
    pub value_delimiter: ValueDelimiter,
    pub line_ending: LineEnding,
    pub indent: String,
    pub trailing_comma: bool,
    pub include_doi: bool,
    pub include_url: bool,
    pub include_extra_fields: bool,
    /// Case-insensitive source-to-target field spelling conversions applied
    /// before the target allowlist (for example, `pmid` to `pubmed`).
    pub field_renames: BTreeMap<String, String>,
    pub field_selection: ExportFieldSelection,
    /// Legacy denylist retained for source compatibility. Unlike older
    /// versions, it is now applied to every generated field.
    pub excluded_fields: BTreeSet<String>,
    pub allow_unknown_work_type: bool,
}

impl Default for ExportProfile {
    fn default() -> Self {
        Self::modern()
    }
}

impl ExportProfile {
    fn baseline() -> Self {
        Self {
            schema_version: String::from(bibmgr_model::SCHEMA_VERSION),
            profile: ProfileId::new("modern"),
            display_name: String::from("Modern BibTeX"),
            description: String::from("General-purpose modern BibTeX output."),
            validation_profile: ProfileId::new("modern"),
            preprint_representation: PreprintRepresentation::MiscEprint,
            venue_style: VenueStyle::AsRecorded,
            month_format: MonthFormat::Numeric,
            supported_entry_types: Vec::new(),
            field_order: default_field_order(),
            field_case: ExportFieldCase::Canonical,
            value_delimiter: ValueDelimiter::Braces,
            line_ending: LineEnding::Lf,
            indent: String::from("  "),
            trailing_comma: true,
            include_doi: true,
            include_url: true,
            include_extra_fields: true,
            field_renames: BTreeMap::new(),
            field_selection: ExportFieldSelection::default(),
            excluded_fields: BTreeSet::new(),
            allow_unknown_work_type: true,
        }
    }

    pub fn modern() -> Self {
        Self::embedded(
            include_str!("../../../config/export-profiles/modern.toml"),
            "modern",
        )
    }

    pub fn laboratory() -> Self {
        Self::embedded(
            include_str!("../../../config/export-profiles/laboratory.toml"),
            "laboratory",
        )
    }

    pub fn classical_bst() -> Self {
        Self::embedded(
            include_str!("../../../config/export-profiles/classical-bst.toml"),
            "classical-bst",
        )
    }

    pub fn legacy_arxiv_article() -> Self {
        Self::embedded(
            include_str!("../../../config/export-profiles/legacy-arxiv-article.toml"),
            "legacy-arxiv-article",
        )
    }

    pub fn acl() -> Self {
        Self::embedded(
            include_str!("../../../config/export-profiles/acl-publications.toml"),
            "acl",
        )
    }

    pub fn aaai() -> Self {
        Self::embedded(
            include_str!("../../../config/export-profiles/aaai-conference.toml"),
            "aaai",
        )
    }

    pub fn builtin(profile: &str) -> Result<Self, ExportError> {
        let input = match profile {
            "default" | "modern" => include_str!("../../../config/export-profiles/modern.toml"),
            "laboratory" => {
                include_str!("../../../config/export-profiles/laboratory.toml")
            }
            "classical-bst" => {
                include_str!("../../../config/export-profiles/classical-bst.toml")
            }
            "legacy-arxiv-article" | "article-journal" => {
                include_str!("../../../config/export-profiles/legacy-arxiv-article.toml")
            }
            "acl" => include_str!("../../../config/export-profiles/acl-publications.toml"),
            "aaai" => include_str!("../../../config/export-profiles/aaai-conference.toml"),
            "acm-publications" => {
                include_str!("../../../config/export-profiles/acm-publications.toml")
            }
            "ieee-publications" => {
                include_str!("../../../config/export-profiles/ieee-publications.toml")
            }
            "natbib-full-author-names" => include_str!(
                "../../../config/export-profiles/natbib-full-author-names.toml"
            ),
            "springer-lncs" => {
                include_str!("../../../config/export-profiles/springer-lncs.toml")
            }
            "ml-conferences" => include_str!(
                "../../../config/export-profiles/machine-learning-conferences.toml"
            ),
            "lrec" => include_str!(
                "../../../config/export-profiles/lrec-language-resources.toml"
            ),
            "eamt" => {
                include_str!("../../../config/export-profiles/eamt-conference.toml")
            }
            "ipsj-japanese" => include_str!(
                "../../../config/export-profiles/information-processing-society-of-japan-japanese.toml"
            ),
            "ipsj-english" => include_str!(
                "../../../config/export-profiles/information-processing-society-of-japan-english.toml"
            ),
            "jnlp-japanese" => include_str!(
                "../../../config/export-profiles/journal-of-natural-language-processing-japanese.toml"
            ),
            "jsai-journal" => include_str!(
                "../../../config/export-profiles/japanese-society-for-artificial-intelligence-journal.toml"
            ),
            other => return Err(ExportError::UnknownProfile(other.to_owned())),
        };
        Self::from_toml(input)
    }

    /// Return every canonical built-in profile in stable catalog order.
    pub fn builtins() -> Result<Vec<Self>, ExportError> {
        BUILTIN_EXPORT_PROFILE_IDS
            .iter()
            .map(|profile| Self::builtin(profile))
            .collect()
    }

    pub fn for_profile(profile: &ProfileId) -> Result<Self, ExportError> {
        Self::builtin(profile.as_str())
    }

    pub fn from_toml(input: &str) -> Result<Self, ExportError> {
        let profile: Self = toml::from_str(input).map_err(ExportError::Toml)?;
        profile.validate()?;
        Ok(profile)
    }

    fn embedded(input: &str, profile_id: &str) -> Self {
        Self::from_toml(input).unwrap_or_else(|error| {
            panic!("embedded export profile `{profile_id}` must be valid: {error}")
        })
    }

    pub fn validate(&self) -> Result<(), ExportError> {
        if self.schema_version != bibmgr_model::SCHEMA_VERSION {
            return Err(ExportError::UnsupportedSchemaVersion(
                self.schema_version.clone(),
            ));
        }
        if self.profile.as_str().trim().is_empty() {
            return Err(ExportError::InvalidProfile(String::from(
                "profile id cannot be empty",
            )));
        }
        if self.display_name.trim().is_empty() {
            return Err(ExportError::InvalidProfile(String::from(
                "display_name cannot be empty",
            )));
        }
        if self.description.trim().is_empty() {
            return Err(ExportError::InvalidProfile(String::from(
                "description cannot be empty",
            )));
        }
        if self.validation_profile.as_str().trim().is_empty() {
            return Err(ExportError::InvalidProfile(String::from(
                "validation profile id cannot be empty",
            )));
        }
        if self.indent.contains(['\r', '\n'])
            || !self
                .indent
                .chars()
                .all(|character| character == ' ' || character == '\t')
        {
            return Err(ExportError::InvalidProfile(String::from(
                "indent must contain only spaces or tabs",
            )));
        }
        let mut names = BTreeSet::new();
        for field in &self.field_order {
            if !valid_field_name(field) {
                return Err(ExportError::InvalidFieldName(field.clone()));
            }
            if !names.insert(field.to_ascii_lowercase()) {
                return Err(ExportError::DuplicateFieldOrder(field.clone()));
            }
        }
        validate_field_set("supported_entry_types", &self.supported_entry_types)?;
        validate_field_set("excluded_fields", &self.excluded_fields)?;
        if let Some(allowed_fields) = &self.field_selection.allowed_fields {
            validate_field_set("field_selection.allowed_fields", allowed_fields)?;
        }
        validate_field_set(
            "field_selection.excluded_fields",
            &self.field_selection.excluded_fields,
        )?;
        if let Some(allowed_fields) = &self.field_selection.allowed_fields {
            let excluded = self
                .field_selection
                .excluded_fields
                .iter()
                .chain(&self.excluded_fields);
            if let Some(conflict) = excluded.into_iter().find(|excluded| {
                allowed_fields
                    .iter()
                    .any(|allowed| allowed.eq_ignore_ascii_case(excluded))
            }) {
                return Err(ExportError::InvalidProfile(format!(
                    "field `{conflict}` is both allowed and excluded"
                )));
            }
        }
        self.validate_field_renames()?;
        Ok(())
    }

    fn validate_field_renames(&self) -> Result<(), ExportError> {
        validate_field_set("field_renames sources", self.field_renames.keys())?;
        validate_field_set("field_renames targets", self.field_renames.values())?;
        for (source, target) in &self.field_renames {
            if source.eq_ignore_ascii_case(target) {
                return Err(ExportError::InvalidProfile(format!(
                    "field rename `{source}` to `{target}` does not change the field name"
                )));
            }
            if !field_is_selected(target, self) {
                return Err(ExportError::InvalidProfile(format!(
                    "renamed field `{target}` is not selected by the target field projection"
                )));
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ExportWarning {
    pub record_index: usize,
    pub message: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ExportResult {
    pub schema_version: String,
    pub source: String,
    pub profile: ProfileId,
    pub record_count: usize,
    pub warnings: Vec<ExportWarning>,
}

#[derive(Debug, thiserror::Error)]
pub enum ExportError {
    #[error("export blocked by diagnostics: {0:?}")]
    BlockingDiagnostics(Vec<RuleCode>),
    #[error("unknown export profile `{0}`")]
    UnknownProfile(String),
    #[error("unsupported export profile schema version `{0}`")]
    UnsupportedSchemaVersion(String),
    #[error("invalid export profile: {0}")]
    InvalidProfile(String),
    #[error("field order contains duplicate field `{0}`")]
    DuplicateFieldOrder(String),
    #[error("invalid BibTeX field name `{0}`")]
    InvalidFieldName(String),
    #[error("record {record_index} has invalid citation key `{key}`")]
    InvalidCitationKey { record_index: usize, key: String },
    #[error("record {record_index} has unknown work type")]
    UnknownWorkType { record_index: usize },
    #[error(
        "record {record_index} cannot be exported as entry type `{entry_type}` by profile `{profile}`"
    )]
    UnsupportedEntryType {
        record_index: usize,
        entry_type: String,
        profile: String,
    },
    #[error("record {record_index} contains duplicate field `{field}`")]
    DuplicateField { record_index: usize, field: String },
    #[error("record {record_index} field `{field}` has no resolved value")]
    UnresolvedField { record_index: usize, field: String },
    #[error("record {record_index} contains ambiguous semantics `{kind}`")]
    AmbiguousSemantics { record_index: usize, kind: String },
    #[error("record {record_index} contains conflicting semantics for `{field}`")]
    ConflictingSemantics { record_index: usize, field: String },
    #[error("invalid export profile TOML: {0}")]
    Toml(toml::de::Error),
}

/// Export a semantic bibliography without consulting or reserializing its CST.
pub fn export(
    bibliography: &Bibliography,
    profile: &ExportProfile,
) -> Result<ExportResult, ExportError> {
    profile.validate()?;
    let mut source = String::new();
    let mut warnings = Vec::new();
    for (record_index, record) in bibliography.records.iter().enumerate() {
        if record_index != 0 {
            source.push_str(profile.line_ending.as_str());
        }
        let rendered = export_record(record, record_index, profile, &mut warnings)?;
        source.push_str(&rendered);
    }
    Ok(ExportResult {
        schema_version: String::from(bibmgr_model::SCHEMA_VERSION),
        source,
        profile: profile.profile.clone(),
        record_count: bibliography.records.len(),
        warnings,
    })
}

#[allow(clippy::too_many_lines)]
fn export_record(
    record: &BibliographicRecord,
    record_index: usize,
    profile: &ExportProfile,
    warnings: &mut Vec<ExportWarning>,
) -> Result<String, ExportError> {
    let citation_key = record.citation_key.value.to_string();
    if !valid_citation_key(&citation_key) {
        return Err(ExportError::InvalidCitationKey {
            record_index,
            key: citation_key,
        });
    }
    if let Some(field) = record.unresolved_values.first() {
        return Err(ExportError::UnresolvedField {
            record_index,
            field: field.name.clone(),
        });
    }
    if record
        .date
        .as_ref()
        .is_some_and(|date| date.status == bibmgr_semantics::ValueStatus::Unresolved)
    {
        return Err(ExportError::UnresolvedField {
            record_index,
            field: String::from("date"),
        });
    }
    if let Some(ambiguity) = record.ambiguities.first() {
        return Err(ExportError::AmbiguousSemantics {
            record_index,
            kind: ambiguity.kind.clone(),
        });
    }
    if let Some(conflict) = record.conflicts.first() {
        return Err(ExportError::ConflictingSemantics {
            record_index,
            field: conflict.field.clone(),
        });
    }
    if let Some((field, status)) = first_uncertain_field(record) {
        return match status {
            ValueStatus::Ambiguous => Err(ExportError::AmbiguousSemantics {
                record_index,
                kind: format!("{field}-value"),
            }),
            ValueStatus::Conflicting => Err(ExportError::ConflictingSemantics {
                record_index,
                field,
            }),
            ValueStatus::Unresolved => Err(ExportError::UnresolvedField {
                record_index,
                field,
            }),
            _ => unreachable!("first_uncertain_field only returns uncertain statuses"),
        };
    }
    let original_entry_type = record.entry_type.value.to_ascii_lowercase();
    let preserves_original_entry_type = record.work_type.value != WorkType::Preprint
        && explicitly_supports_entry_type(profile, &original_entry_type);
    if record.work_type.value == WorkType::Unknown
        && !preserves_original_entry_type
        && !profile.allow_unknown_work_type
    {
        return Err(ExportError::UnknownWorkType { record_index });
    }
    if record.work_type.value == WorkType::Unknown && !preserves_original_entry_type {
        warnings.push(ExportWarning {
            record_index,
            message: String::from("unknown work type was exported as `misc`"),
        });
    }

    let entry_type = entry_type(record, profile);
    if !target_accepts_entry_type(profile, &entry_type) {
        return Err(ExportError::UnsupportedEntryType {
            record_index,
            entry_type,
            profile: profile.profile.to_string(),
        });
    }
    let mut fields = Vec::<ExportField>::new();
    if let Some(title) = &record.title {
        push_field(&mut fields, "title", title.value.to_string(), record_index)?;
    }
    if !record.authors.is_empty() {
        push_field(
            &mut fields,
            "author",
            format_people(record.authors.iter().map(|person| &person.value)),
            record_index,
        )?;
    }
    if !record.editors.is_empty() {
        push_field(
            &mut fields,
            "editor",
            format_people(record.editors.iter().map(|person| &person.value)),
            record_index,
        )?;
    }
    if let Some(venue) = record
        .venue
        .as_ref()
        .filter(|_| record.work_type.value != WorkType::Preprint)
    {
        let venue_value = match profile.venue_style {
            VenueStyle::Full => venue.value.full_name.as_ref().unwrap_or(&venue.value.raw),
            VenueStyle::Short => venue.value.short_name.as_ref().unwrap_or(&venue.value.raw),
            VenueStyle::AsRecorded => &venue.value.raw,
        };
        let field = match record.work_type.value {
            WorkType::JournalArticle => "journal",
            WorkType::ConferencePaper => "booktitle",
            _ => "howpublished",
        };
        push_field(&mut fields, field, venue_value.clone(), record_index)?;
    }
    if let Some(date) = &record.date {
        if let Some(year) = date.value.year {
            push_field(&mut fields, "year", year.to_string(), record_index)?;
        }
        let came_from_date_field = date.origins.iter().any(|origin| {
            origin
                .field_name
                .as_deref()
                .is_some_and(|name| name.eq_ignore_ascii_case("date"))
        });
        if came_from_date_field && !date.value.raw.trim().is_empty() {
            push_field(&mut fields, "date", date.value.raw.clone(), record_index)?;
        } else {
            if let Some(month) = date.value.month {
                let month = match profile.month_format {
                    MonthFormat::Numeric => month.to_string(),
                    MonthFormat::BibtexMacro => bibtex_month_macro(month).to_owned(),
                };
                push_field(&mut fields, "month", month, record_index)?;
            }
            if let Some(day) = date.value.day {
                push_field(&mut fields, "day", day.to_string(), record_index)?;
            }
        }
    }

    append_preprint_fields(record, profile, record_index, &mut fields)?;
    if profile.include_doi {
        if let Some(doi) = record.identifiers.primary_doi() {
            push_field(&mut fields, "doi", doi.value.to_string(), record_index)?;
        }
    }
    append_identifier_fields(record, record_index, &mut fields)?;
    if profile.include_url {
        if let Some(url) = record.urls.first() {
            push_field(&mut fields, "url", url.value.to_string(), record_index)?;
        }
        if record.urls.len() > 1 {
            warnings.push(ExportWarning {
                record_index,
                message: String::from("only the first URL was exported"),
            });
        }
    }
    if profile.include_extra_fields {
        for field in &record.extra_fields {
            append_extra_field(field, record_index, &mut fields)?;
        }
    }

    apply_field_renames(&mut fields, profile, record_index)?;
    project_fields(&mut fields, profile);
    sort_fields(&mut fields, &profile.field_order);
    let newline = profile.line_ending.as_str();
    let mut output = format!("@{entry_type}{{{citation_key},{newline}");
    for (index, field) in fields.iter().enumerate() {
        let name = field_spelling(&field.name, profile.field_case);
        let value = if field.name.eq_ignore_ascii_case("month")
            && profile.month_format == MonthFormat::BibtexMacro
            && is_bibtex_month_macro(&field.value)
        {
            field.value.clone()
        } else {
            format_field_value(&field.name, &field.value, profile.value_delimiter)
        };
        output.push_str(&profile.indent);
        output.push_str(&name);
        output.push_str(" = ");
        output.push_str(&value);
        if profile.trailing_comma || index + 1 < fields.len() {
            output.push(',');
        }
        output.push_str(newline);
    }
    output.push('}');
    output.push_str(newline);
    Ok(output)
}

fn first_uncertain_field(record: &BibliographicRecord) -> Option<(String, ValueStatus)> {
    let uncertain = |status: ValueStatus| {
        matches!(
            status,
            ValueStatus::Unresolved | ValueStatus::Ambiguous | ValueStatus::Conflicting
        )
    };
    let scalar = [
        ("citation_key", record.citation_key.status),
        ("entry_type", record.entry_type.status),
        ("work_type", record.work_type.status),
    ];
    if let Some((field, status)) = scalar.into_iter().find(|(_, status)| uncertain(*status)) {
        return Some((field.to_string(), status));
    }
    for (field, value) in [
        ("title", record.title.as_ref().map(|value| value.status)),
        ("date", record.date.as_ref().map(|value| value.status)),
        ("venue", record.venue.as_ref().map(|value| value.status)),
        (
            "preprint",
            record.preprint.as_ref().map(|value| value.status),
        ),
    ] {
        if let Some(status) = value.filter(|status| uncertain(*status)) {
            return Some((field.to_string(), status));
        }
    }
    for (field, statuses) in [
        (
            "author",
            record
                .authors
                .iter()
                .map(|value| value.status)
                .collect::<Vec<_>>(),
        ),
        (
            "editor",
            record.editors.iter().map(|value| value.status).collect(),
        ),
        (
            "doi",
            record
                .identifiers
                .dois
                .iter()
                .map(|value| value.status)
                .collect(),
        ),
        (
            "arxiv",
            record
                .identifiers
                .arxiv
                .iter()
                .map(|value| value.status)
                .collect(),
        ),
        (
            "isbn",
            record
                .identifiers
                .isbns
                .iter()
                .map(|value| value.status)
                .collect(),
        ),
        (
            "issn",
            record
                .identifiers
                .issns
                .iter()
                .map(|value| value.status)
                .collect(),
        ),
        (
            "identifier",
            record
                .identifiers
                .other
                .iter()
                .map(|value| value.status)
                .collect(),
        ),
        (
            "url",
            record.urls.iter().map(|value| value.status).collect(),
        ),
    ] {
        if let Some(status) = statuses.into_iter().find(|status| uncertain(*status)) {
            return Some((field.to_string(), status));
        }
    }
    None
}

fn append_identifier_fields(
    record: &BibliographicRecord,
    record_index: usize,
    fields: &mut Vec<ExportField>,
) -> Result<(), ExportError> {
    if !record.identifiers.isbns.is_empty() {
        push_field(
            fields,
            "isbn",
            record
                .identifiers
                .isbns
                .iter()
                .map(|identifier| identifier.value.as_str())
                .collect::<Vec<_>>()
                .join(", "),
            record_index,
        )?;
    }
    if !record.identifiers.issns.is_empty() {
        push_field(
            fields,
            "issn",
            record
                .identifiers
                .issns
                .iter()
                .map(|identifier| identifier.value.as_str())
                .collect::<Vec<_>>()
                .join(", "),
            record_index,
        )?;
    }

    let mut other = BTreeMap::<String, Vec<&str>>::new();
    for identifier in &record.identifiers.other {
        other
            .entry(identifier.value.scheme.to_ascii_lowercase())
            .or_default()
            .push(identifier.value.value.as_str());
    }
    for (scheme, values) in other {
        push_field(fields, &scheme, values.join(", "), record_index)?;
    }
    Ok(())
}

fn entry_type(record: &BibliographicRecord, profile: &ExportProfile) -> String {
    if record.work_type.value == WorkType::Preprint {
        return match profile.preprint_representation {
            PreprintRepresentation::MiscEprint | PreprintRepresentation::MiscHowpublished => {
                String::from("misc")
            }
            PreprintRepresentation::ArticleJournal => String::from("article"),
        };
    }
    let original = record.entry_type.value.to_ascii_lowercase();
    if explicitly_supports_entry_type(profile, &original) {
        return original;
    }
    match record.work_type.value {
        WorkType::JournalArticle => String::from("article"),
        WorkType::ConferencePaper => String::from("inproceedings"),
        WorkType::Book
            if original == "mvproceedings"
                && !profile.supported_entry_types.is_empty()
                && target_accepts_entry_type(profile, "proceedings") =>
        {
            String::from("proceedings")
        }
        WorkType::Book
            if profile.supported_entry_types.is_empty()
                && matches!(original.as_str(), "proceedings" | "mvproceedings") =>
        {
            original
        }
        WorkType::Book => String::from("book"),
        WorkType::InBook => String::from("inbook"),
        WorkType::InCollection => String::from("incollection"),
        WorkType::Thesis
            if profile.supported_entry_types.is_empty()
                && matches!(original.as_str(), "mastersthesis" | "phdthesis" | "thesis") =>
        {
            original
        }
        WorkType::Thesis => String::from("phdthesis"),
        WorkType::TechnicalReport => String::from("techreport"),
        WorkType::Dataset
        | WorkType::Software
        | WorkType::WebResource
        | WorkType::Miscellaneous
        | WorkType::Unknown
        | WorkType::Preprint => String::from("misc"),
    }
}

fn explicitly_supports_entry_type(profile: &ExportProfile, entry_type: &str) -> bool {
    !profile.supported_entry_types.is_empty()
        && profile
            .supported_entry_types
            .iter()
            .any(|supported| supported.eq_ignore_ascii_case(entry_type))
}

fn target_accepts_entry_type(profile: &ExportProfile, entry_type: &str) -> bool {
    profile.supported_entry_types.is_empty()
        || profile
            .supported_entry_types
            .iter()
            .any(|supported| supported.eq_ignore_ascii_case(entry_type))
}

fn append_preprint_fields(
    record: &BibliographicRecord,
    profile: &ExportProfile,
    record_index: usize,
    fields: &mut Vec<ExportField>,
) -> Result<(), ExportError> {
    let details = record.preprint.as_ref().map(|preprint| &preprint.value);
    let identifier = details
        .map(|preprint| preprint.identifier.as_str())
        .or_else(|| {
            record
                .identifiers
                .primary_arxiv()
                .map(|identifier| identifier.value.as_str())
        });
    let Some(identifier) = identifier else {
        return Ok(());
    };
    let version = details.and_then(|preprint| preprint.version.as_deref());
    let identifier = with_version(identifier, version);
    let repository_name = details.map_or("arXiv", |preprint| match &preprint.repository {
        Repository::ArXiv => "arXiv",
        Repository::Other(name) => name.as_str(),
    });
    let is_standalone_preprint = record.work_type.value == WorkType::Preprint;
    match profile.preprint_representation {
        PreprintRepresentation::MiscEprint => {
            push_field(fields, "eprint", identifier, record_index)?;
            push_field(fields, "archivePrefix", repository_name, record_index)?;
            if let Some(primary_class) =
                details.and_then(|preprint| preprint.primary_category.clone())
            {
                push_field(fields, "primaryClass", primary_class, record_index)?;
            }
        }
        PreprintRepresentation::MiscHowpublished => {
            if is_standalone_preprint {
                push_field(
                    fields,
                    "howpublished",
                    format!("{repository_name}:{identifier}"),
                    record_index,
                )?;
            } else {
                push_field(
                    fields,
                    "note",
                    format!("Also available as {repository_name}:{identifier}"),
                    record_index,
                )?;
            }
        }
        PreprintRepresentation::ArticleJournal => {
            if is_standalone_preprint {
                push_field(
                    fields,
                    "journal",
                    format!("{repository_name}:{identifier}"),
                    record_index,
                )?;
            } else {
                push_field(fields, "eprint", identifier, record_index)?;
                push_field(fields, "archivePrefix", repository_name, record_index)?;
            }
        }
    }
    Ok(())
}

fn append_extra_field(
    field: &SemanticField,
    record_index: usize,
    fields: &mut Vec<ExportField>,
) -> Result<(), ExportError> {
    if !valid_field_name(&field.name) {
        return Err(ExportError::InvalidFieldName(field.name.clone()));
    }
    let value = field
        .value
        .resolved
        .as_ref()
        .ok_or_else(|| ExportError::UnresolvedField {
            record_index,
            field: field.name.clone(),
        })?;
    if let Some(known) = fields
        .iter_mut()
        .find(|known| known.name.eq_ignore_ascii_case(&field.name))
    {
        if matches!(
            field.name.to_ascii_lowercase().as_str(),
            "note" | "howpublished"
        ) {
            known.value = merge_field_values(value, &known.value);
        }
        return Ok(());
    }
    push_field(fields, &field.name, value.clone(), record_index)
}

fn apply_field_renames(
    fields: &mut [ExportField],
    profile: &ExportProfile,
    record_index: usize,
) -> Result<(), ExportError> {
    for field in &mut *fields {
        if let Some((_, target)) = profile
            .field_renames
            .iter()
            .find(|(source, _)| source.eq_ignore_ascii_case(&field.name))
        {
            field.name.clone_from(target);
        }
    }
    let mut names = BTreeSet::new();
    for field in fields {
        if !names.insert(field.name.to_ascii_lowercase()) {
            return Err(ExportError::DuplicateField {
                record_index,
                field: field.name.clone(),
            });
        }
    }
    Ok(())
}

fn merge_field_values(source_value: &str, generated_value: &str) -> String {
    if source_value == generated_value || source_value.contains(generated_value) {
        source_value.to_owned()
    } else if generated_value.contains(source_value) {
        generated_value.to_owned()
    } else {
        format!("{source_value}; {generated_value}")
    }
}

#[derive(Debug)]
struct ExportField {
    name: String,
    value: String,
    ordinal: usize,
}

fn push_field(
    fields: &mut Vec<ExportField>,
    name: &str,
    value: impl Into<String>,
    record_index: usize,
) -> Result<(), ExportError> {
    if !valid_field_name(name) {
        return Err(ExportError::InvalidFieldName(name.to_owned()));
    }
    if fields
        .iter()
        .any(|field| field.name.eq_ignore_ascii_case(name))
    {
        return Err(ExportError::DuplicateField {
            record_index,
            field: name.to_owned(),
        });
    }
    fields.push(ExportField {
        name: name.to_owned(),
        value: value.into(),
        ordinal: fields.len(),
    });
    Ok(())
}

fn project_fields(fields: &mut Vec<ExportField>, profile: &ExportProfile) {
    fields.retain(|field| field_is_selected(&field.name, profile));
}

fn field_is_selected(field: &str, profile: &ExportProfile) -> bool {
    let is_named = |candidate: &String| candidate.eq_ignore_ascii_case(field);
    let allowed = profile
        .field_selection
        .allowed_fields
        .as_ref()
        .is_none_or(|fields| fields.iter().any(is_named));
    let excluded = profile
        .field_selection
        .excluded_fields
        .iter()
        .chain(&profile.excluded_fields)
        .any(is_named);
    allowed && !excluded
}

fn sort_fields(fields: &mut [ExportField], order: &[String]) {
    let ranks: BTreeMap<_, _> = order
        .iter()
        .enumerate()
        .map(|(index, name)| (name.to_ascii_lowercase(), index))
        .collect();
    fields.sort_by(|left, right| {
        let left_name = left.name.to_ascii_lowercase();
        let right_name = right.name.to_ascii_lowercase();
        let left_rank = ranks.get(&left_name).copied().unwrap_or(usize::MAX);
        let right_rank = ranks.get(&right_name).copied().unwrap_or(usize::MAX);
        (left_rank, &left_name, left.ordinal).cmp(&(right_rank, &right_name, right.ordinal))
    });
}

fn format_people<'a>(people: impl Iterator<Item = &'a Person>) -> String {
    people.map(format_person).collect::<Vec<_>>().join(" and ")
}

fn format_person(person: &Person) -> String {
    if let Some(literal) = &person.literal {
        return format!("{{{literal}}}");
    }
    if person.family.is_empty() {
        return person.raw.clone();
    }
    let family = person
        .prefix
        .iter()
        .chain(&person.family)
        .cloned()
        .collect::<Vec<_>>()
        .join(" ");
    let given = person.given.join(" ");
    let suffix = person.suffix.join(" ");
    match (suffix.is_empty(), given.is_empty()) {
        (true, true) => family,
        (true, false) => format!("{family}, {given}"),
        (false, true) => format!("{family}, {suffix}"),
        (false, false) => format!("{family}, {suffix}, {given}"),
    }
}

fn format_field_value(field_name: &str, value: &str, delimiter: ValueDelimiter) -> String {
    let escaped = if is_raw_identifier_field(field_name) {
        escape_bibtex_with_options(value, delimiter, false)
    } else {
        escape_bibtex(value, delimiter)
    };
    match delimiter {
        ValueDelimiter::Braces => format!("{{{escaped}}}"),
        ValueDelimiter::Quotes => format!("\"{escaped}\""),
    }
}

fn is_raw_identifier_field(field_name: &str) -> bool {
    matches!(
        field_name.to_ascii_lowercase().as_str(),
        "url"
            | "doi"
            | "file"
            | "eprint"
            | "arxiv"
            | "archiveprefix"
            | "eprinttype"
            | "primaryclass"
            | "eprintclass"
            | "isbn"
            | "isbn-10"
            | "isbn-13"
            | "issn"
            | "eissn"
            | "coden"
            | "lccn"
            | "pmid"
            | "pmcid"
            | "pubmed"
            | "eid"
            | "pid"
            | "islrn"
            | "articleno"
            | "crossref"
            | "archived"
    )
}

fn bibtex_month_macro(month: u8) -> &'static str {
    match month {
        1 => "jan",
        2 => "feb",
        3 => "mar",
        4 => "apr",
        5 => "may",
        6 => "jun",
        7 => "jul",
        8 => "aug",
        9 => "sep",
        10 => "oct",
        11 => "nov",
        12 => "dec",
        _ => unreachable!("semantic publication months are in the range 1..=12"),
    }
}

fn is_bibtex_month_macro(value: &str) -> bool {
    matches!(
        value.to_ascii_lowercase().as_str(),
        "jan"
            | "feb"
            | "mar"
            | "apr"
            | "may"
            | "jun"
            | "jul"
            | "aug"
            | "sep"
            | "oct"
            | "nov"
            | "dec"
    )
}

/// Deterministically escape TeX-sensitive bytes without rewriting Unicode.
///
/// URL-like braced command arguments (`\url`, `\nolinkurl`, and `\path`) and
/// the delimiter arguments of `\verb`, `\verb*`, `\Verb`, and `\lstinline`
/// retain their literal `%`, `&`, `#`, `_`, and `$` bytes. The latter two
/// commands support their optional argument syntax, and all three command
/// families support the same starred forms and delimiters as validation.
/// Quote-delimited BibTeX values still escape unescaped quotes in every
/// context.
pub fn escape_bibtex(value: &str, delimiter: ValueDelimiter) -> String {
    escape_bibtex_with_options(value, delimiter, true)
}

fn escape_bibtex_with_options(
    value: &str,
    delimiter: ValueDelimiter,
    escape_tex_sensitive: bool,
) -> String {
    let mut output = String::with_capacity(value.len());
    let bytes = value.as_bytes();
    let mut cursor = 0;
    let mut state = BibtexEscapeState::default();

    while cursor < bytes.len() {
        let character = value[cursor..]
            .chars()
            .next()
            .expect("cursor remains on a UTF-8 boundary");
        let character_len = character.len_utf8();

        if consume_literal_command_character(
            &mut output,
            character,
            delimiter,
            escape_tex_sensitive,
            &mut state,
        ) {
            cursor += character_len;
            continue;
        }

        if character == '\\' && !state.escaped && cursor + 1 < bytes.len() {
            let command_start = cursor + 1;
            if is_tex_command_byte(bytes[command_start]) {
                let mut command_end = command_start + 1;
                while command_end < bytes.len() && is_tex_command_byte(bytes[command_end]) {
                    command_end += 1;
                }
                let command = &bytes[command_start..command_end];
                output.push_str(&value[cursor..command_end]);
                state.pending_raw_brace_command = is_raw_brace_command(command);
                state.pending_verbatim = pending_verbatim_command(command);
                state.escaped = false;
                cursor = command_end;
                continue;
            }
        }

        let was_escaped = state.escaped;
        update_brace_context(
            character,
            was_escaped,
            state.pending_raw_brace_command,
            &mut state.brace_depth,
            &mut state.raw_brace_argument_depth,
        );
        push_bibtex_character(
            &mut output,
            character,
            delimiter,
            escape_tex_sensitive && state.raw_brace_argument_depth.is_none(),
            &mut state.escaped,
        );
        if !character.is_ascii_whitespace() || character == '{' {
            state.pending_raw_brace_command = false;
        }
        cursor += character_len;
    }
    output
}

#[derive(Debug, Default)]
struct BibtexEscapeState {
    escaped: bool,
    brace_depth: usize,
    raw_brace_argument_depth: Option<usize>,
    pending_raw_brace_command: bool,
    pending_verbatim: Option<PendingVerbatim>,
    verbatim_delimiter: Option<char>,
}

#[derive(Debug, Clone, Copy)]
enum PendingVerbatim {
    Delimiter {
        star_allowed: bool,
        options_allowed: bool,
        skip_horizontal_whitespace: bool,
    },
    Options {
        depth: usize,
    },
}

fn consume_literal_command_character(
    output: &mut String,
    character: char,
    delimiter: ValueDelimiter,
    escape_tex_sensitive: bool,
    state: &mut BibtexEscapeState,
) -> bool {
    if let Some(raw_delimiter) = state.verbatim_delimiter {
        let closes_argument = character == raw_delimiter;
        push_bibtex_character(output, character, delimiter, false, &mut state.escaped);
        if closes_argument || matches!(character, '\r' | '\n') {
            state.verbatim_delimiter = None;
        }
        return true;
    }

    let Some(pending) = state.pending_verbatim else {
        return false;
    };
    match pending {
        PendingVerbatim::Delimiter {
            star_allowed: true,
            options_allowed,
            skip_horizontal_whitespace,
        } if character == '*' => {
            push_bibtex_character(
                output,
                character,
                delimiter,
                escape_tex_sensitive && state.raw_brace_argument_depth.is_none(),
                &mut state.escaped,
            );
            state.pending_verbatim = Some(PendingVerbatim::Delimiter {
                star_allowed: false,
                options_allowed,
                skip_horizontal_whitespace,
            });
        }
        PendingVerbatim::Delimiter {
            options_allowed: true,
            ..
        } if character == '[' => {
            push_bibtex_character(
                output,
                character,
                delimiter,
                escape_tex_sensitive && state.raw_brace_argument_depth.is_none(),
                &mut state.escaped,
            );
            state.pending_verbatim = Some(PendingVerbatim::Options { depth: 1 });
        }
        PendingVerbatim::Delimiter {
            options_allowed,
            skip_horizontal_whitespace: true,
            ..
        } if matches!(character, ' ' | '\t') => {
            push_bibtex_character(
                output,
                character,
                delimiter,
                escape_tex_sensitive && state.raw_brace_argument_depth.is_none(),
                &mut state.escaped,
            );
            state.pending_verbatim = Some(PendingVerbatim::Delimiter {
                star_allowed: false,
                options_allowed,
                skip_horizontal_whitespace: true,
            });
        }
        PendingVerbatim::Delimiter { .. } if is_verbatim_delimiter(character) => {
            push_bibtex_character(output, character, delimiter, false, &mut state.escaped);
            state.pending_verbatim = None;
            state.verbatim_delimiter = Some(character);
        }
        PendingVerbatim::Options { depth } => {
            consume_lstinline_option_character(
                output,
                character,
                delimiter,
                escape_tex_sensitive,
                depth,
                state,
            );
        }
        PendingVerbatim::Delimiter { .. } => {
            state.pending_verbatim = None;
            return false;
        }
    }
    state.pending_raw_brace_command = false;
    true
}

fn consume_lstinline_option_character(
    output: &mut String,
    character: char,
    delimiter: ValueDelimiter,
    escape_tex_sensitive: bool,
    depth: usize,
    state: &mut BibtexEscapeState,
) {
    let was_escaped = state.escaped;
    let next_depth = match character {
        '[' if !was_escaped => depth.saturating_add(1),
        ']' if !was_escaped => depth.saturating_sub(1),
        _ => depth,
    };
    update_brace_context(
        character,
        was_escaped,
        false,
        &mut state.brace_depth,
        &mut state.raw_brace_argument_depth,
    );
    push_bibtex_character(
        output,
        character,
        delimiter,
        escape_tex_sensitive && state.raw_brace_argument_depth.is_none(),
        &mut state.escaped,
    );
    state.pending_verbatim = if next_depth == 0 {
        Some(PendingVerbatim::Delimiter {
            star_allowed: false,
            options_allowed: false,
            skip_horizontal_whitespace: true,
        })
    } else {
        Some(PendingVerbatim::Options { depth: next_depth })
    };
}

fn is_tex_command_byte(byte: u8) -> bool {
    byte.is_ascii_alphabetic() || byte == b'@'
}

fn is_raw_brace_command(command: &[u8]) -> bool {
    matches!(command, b"url" | b"nolinkurl" | b"path")
}

fn pending_verbatim_command(command: &[u8]) -> Option<PendingVerbatim> {
    match command {
        b"verb" => Some(PendingVerbatim::Delimiter {
            star_allowed: true,
            options_allowed: false,
            skip_horizontal_whitespace: false,
        }),
        b"Verb" | b"lstinline" => Some(PendingVerbatim::Delimiter {
            star_allowed: true,
            options_allowed: true,
            skip_horizontal_whitespace: true,
        }),
        _ => None,
    }
}

fn is_verbatim_delimiter(character: char) -> bool {
    !character.is_ascii_alphabetic() && !character.is_ascii_whitespace()
}

fn update_brace_context(
    character: char,
    escaped: bool,
    begins_raw_argument: bool,
    brace_depth: &mut usize,
    raw_argument_depth: &mut Option<usize>,
) {
    if escaped {
        return;
    }
    match character {
        '{' => {
            *brace_depth = brace_depth.saturating_add(1);
            if begins_raw_argument && raw_argument_depth.is_none() {
                *raw_argument_depth = Some(*brace_depth);
            }
        }
        '}' => {
            if *raw_argument_depth == Some(*brace_depth) {
                *raw_argument_depth = None;
            }
            *brace_depth = brace_depth.saturating_sub(1);
        }
        _ => {}
    }
}

fn push_bibtex_character(
    output: &mut String,
    character: char,
    delimiter: ValueDelimiter,
    escape_tex_sensitive: bool,
    escaped: &mut bool,
) {
    match character {
        '\r' => *escaped = false,
        '\n' | '\t' => {
            if !output.ends_with(' ') {
                output.push(' ');
            }
            *escaped = false;
        }
        '"' if delimiter == ValueDelimiter::Quotes && !*escaped => {
            output.push_str("\\\"");
            *escaped = false;
        }
        '&' | '%' | '$' | '#' | '_' if escape_tex_sensitive && !*escaped => {
            output.push('\\');
            output.push(character);
            *escaped = false;
        }
        '\\' => {
            output.push(character);
            *escaped = !*escaped;
        }
        _ => {
            output.push(character);
            *escaped = false;
        }
    }
}

fn with_version(identifier: &str, version: Option<&str>) -> String {
    let Some(version) = version.filter(|version| !version.is_empty()) else {
        return identifier.to_owned();
    };
    if identifier.ends_with(version) {
        identifier.to_owned()
    } else if version.starts_with('v') || version.starts_with('V') {
        format!("{identifier}{version}")
    } else {
        format!("{identifier}v{version}")
    }
}

fn field_spelling(value: &str, case: ExportFieldCase) -> String {
    let normalized = value.to_ascii_lowercase();
    match case {
        ExportFieldCase::Lowercase => normalized,
        ExportFieldCase::Canonical => match normalized.as_str() {
            "archiveprefix" => String::from("archivePrefix"),
            "primaryclass" => String::from("primaryClass"),
            _ => normalized,
        },
    }
}

fn valid_citation_key(value: &str) -> bool {
    !value.is_empty()
        && value.chars().all(|character| {
            !character.is_whitespace() && !matches!(character, ',' | '{' | '}' | '(' | ')' | '"')
        })
}

fn valid_field_name(value: &str) -> bool {
    !value.is_empty()
        && value
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || matches!(character, '_' | '-'))
}

fn validate_field_set<'a>(
    label: &str,
    fields: impl IntoIterator<Item = &'a String>,
) -> Result<(), ExportError> {
    let mut normalized = BTreeSet::new();
    for field in fields {
        if !valid_field_name(field) {
            return Err(ExportError::InvalidFieldName(field.clone()));
        }
        if !normalized.insert(field.to_ascii_lowercase()) {
            return Err(ExportError::InvalidProfile(format!(
                "{label} contains duplicate field `{field}`"
            )));
        }
    }
    Ok(())
}

fn default_field_order() -> Vec<String> {
    [
        "author",
        "editor",
        "title",
        "booktitle",
        "journal",
        "series",
        "volume",
        "number",
        "pages",
        "publisher",
        "address",
        "school",
        "institution",
        "month",
        "day",
        "year",
        "date",
        "isbn",
        "issn",
        "doi",
        "pmid",
        "pmcid",
        "eprint",
        "archivePrefix",
        "primaryClass",
        "howpublished",
        "url",
        "note",
    ]
    .into_iter()
    .map(str::to_owned)
    .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use bibmgr_semantics::analyze;
    use bibmgr_syntax::{parse, ParseOptions};

    fn bibliography(source: &str) -> Bibliography {
        let syntax = parse(source, ParseOptions::tolerant());
        analyze(&syntax)
    }

    const RICH_SOURCE: &str = include_str!("../tests/fixtures/profile-rich-input.bib");

    #[test]
    #[allow(clippy::match_same_arms)]
    fn builtin_profiles_match_complete_goldens() {
        let bibliography = bibliography(RICH_SOURCE);
        for profile in ExportProfile::builtins().unwrap() {
            let output = export(&bibliography, &profile).unwrap().source;
            let expected = match profile.profile.as_str() {
                "modern" => include_str!("../tests/fixtures/modern.bib"),
                "laboratory" => include_str!("../tests/fixtures/laboratory.bib"),
                "acl" => include_str!("../tests/fixtures/acl.bib"),
                "aaai" => include_str!("../tests/fixtures/aaai.bib"),
                "acm-publications" => {
                    include_str!("../tests/fixtures/acm-publications.bib")
                }
                "ieee-publications" => {
                    include_str!("../tests/fixtures/ieee-publications.bib")
                }
                "natbib-full-author-names" => {
                    include_str!("../tests/fixtures/natbib-full-author-names.bib")
                }
                "springer-lncs" => include_str!("../tests/fixtures/springer-lncs.bib"),
                "ml-conferences" => {
                    include_str!("../tests/fixtures/machine-learning-conferences.bib")
                }
                "lrec" => include_str!("../tests/fixtures/lrec-language-resources.bib"),
                "eamt" => include_str!("../tests/fixtures/eamt-conference.bib"),
                "ipsj-japanese" => include_str!("../tests/fixtures/ipsj-japanese.bib"),
                "ipsj-english" => include_str!("../tests/fixtures/ipsj-english.bib"),
                "jnlp-japanese" => include_str!("../tests/fixtures/jnlp-japanese.bib"),
                "jsai-journal" => include_str!("../tests/fixtures/jsai-journal.bib"),
                "classical-bst" => include_str!("../tests/fixtures/classical-bst.bib"),
                "legacy-arxiv-article" => {
                    include_str!("../tests/fixtures/legacy-arxiv-article.bib")
                }
                unexpected => panic!("unexpected built-in profile `{unexpected}`"),
            };
            assert_eq!(output, expected, "profile `{}`", profile.profile);
        }
    }

    #[test]
    fn builtin_catalog_is_canonical_stable_and_described() {
        let profiles = ExportProfile::builtins().unwrap();
        assert_eq!(
            profiles
                .iter()
                .map(|profile| profile.profile.as_str())
                .collect::<Vec<_>>(),
            BUILTIN_EXPORT_PROFILE_IDS
        );
        assert!(profiles.iter().all(|profile| {
            !profile.display_name.trim().is_empty() && !profile.description.trim().is_empty()
        }));
        assert_eq!(ExportProfile::builtin("default").unwrap(), profiles[0]);
        let legacy_arxiv = profiles
            .iter()
            .find(|profile| profile.profile.as_str() == "legacy-arxiv-article")
            .unwrap();
        assert_eq!(
            ExportProfile::builtin("article-journal").unwrap(),
            legacy_arxiv.clone()
        );
    }

    #[test]
    fn every_builtin_profile_is_idempotent() {
        let records = bibliography(RICH_SOURCE);
        for profile in ExportProfile::builtins().unwrap() {
            let first = export(&records, &profile).unwrap().source;
            let second = export(&bibliography(&first), &profile).unwrap().source;
            assert_eq!(second, first, "profile `{}`", profile.profile);
        }
    }

    #[test]
    fn artifact_profiles_project_style_specific_fields() {
        let records = bibliography(
            "@misc{probe, title={Probe}, year={2026}, assignee={Unused Assignee}, nationality={Japanese}, distinctURL={true}, pmid={12345}, lastchecked={2026-07-22}, eid={A1}, islrn={42-123-456-789-0}, pid={lrec_123}, yomi={ぷろーぶ}, romaji={puroobu}, refdate={2026-07-22}, custom={drop me},}\n",
        );
        let cases = [
            ("aaai", &["eid"][..], &["pubmed", "custom"][..]),
            (
                "acl",
                &["eid", "pubmed", "lastchecked"][..],
                &["islrn", "custom"][..],
            ),
            (
                "acm-publications",
                &["eid", "distincturl"][..],
                &["pubmed", "custom"][..],
            ),
            (
                "ieee-publications",
                &["nationality"][..],
                &["assignee", "eid", "custom"][..],
            ),
            ("ml-conferences", &["eid"][..], &["pubmed", "custom"][..]),
            (
                "lrec",
                &["pubmed", "lastchecked", "islrn", "pid"][..],
                &["eid", "custom"][..],
            ),
            (
                "ipsj-japanese",
                &["refdate", "yomi"][..],
                &["romaji", "custom"][..],
            ),
            ("ipsj-english", &["refdate"][..], &["yomi", "custom"][..]),
            (
                "jnlp-japanese",
                &["romaji", "yomi"][..],
                &["refdate", "custom"][..],
            ),
            ("jsai-journal", &["yomi"][..], &["romaji", "custom"][..]),
        ];

        for (profile_id, retained, dropped) in cases {
            let output = export(&records, &ExportProfile::builtin(profile_id).unwrap())
                .unwrap()
                .source;
            for field in retained {
                assert!(
                    output.contains(&format!("  {field} =")),
                    "profile `{profile_id}` should retain `{field}`:\n{output}"
                );
            }
            for field in dropped {
                assert!(
                    !output.contains(&format!("  {field} =")),
                    "profile `{profile_id}` should drop `{field}`:\n{output}"
                );
            }
        }
    }

    #[test]
    fn artifact_profiles_preserve_bst_native_entry_types() {
        let cases = [
            (
                "acl",
                "@presentation{probe, author={Doe, Jane}, title={Talk}, year={2026},}\n",
                "presentation",
                "title",
            ),
            (
                "acm-publications",
                "@artifactsoftware{probe, author={Doe, Jane}, title={Tool}, year={2026}, url={https://example.test/tool},}\n",
                "artifactsoftware",
                "url",
            ),
            (
                "ieee-publications",
                "@patent{probe, author={Doe, Jane}, nationality={Japanese}, number={12345}, title={Widget}, year={2026},}\n",
                "patent",
                "nationality",
            ),
            (
                "lrec",
                "@languageresource{probe, author={Doe, Jane}, title={Corpus}, year={2026}, islrn={42-123-456-789-0}, pid={lrec_123},}\n",
                "languageresource",
                "islrn",
            ),
            (
                "ipsj-japanese",
                "@webpage{probe, author={Doe, Jane}, title={Page}, organization={Example Organization}, year={2026}, url={https://example.test/page}, refdate={2026-07-22},}\n",
                "webpage",
                "refdate",
            ),
            (
                "jnlp-japanese",
                "@dbathesis{probe, author={Doe, Jane}, title={Thesis}, school={Example University}, year={2026}, yomi={ぷろーぶ},}\n",
                "dbathesis",
                "yomi",
            ),
        ];

        for (profile_id, source, entry_type, field) in cases {
            let output = export(
                &bibliography(source),
                &ExportProfile::builtin(profile_id).unwrap(),
            )
            .unwrap()
            .source;
            assert!(
                output.starts_with(&format!("@{entry_type}{{probe,")),
                "profile `{profile_id}` did not preserve `{entry_type}`:\n{output}"
            );
            assert!(
                output.contains(&format!("  {field} =")),
                "profile `{profile_id}` did not retain `{field}`:\n{output}"
            );
        }

        for (source, expected_entry_type) in [
            (
                "@mvproceedings{probe, title={Proceedings}, year={2026},}\n",
                "proceedings",
            ),
            (
                "@thesis{probe, author={Doe, Jane}, title={Thesis}, school={Example University}, year={2026},}\n",
                "phdthesis",
            ),
        ] {
            let output = export(
                &bibliography(source),
                &ExportProfile::builtin("aaai").unwrap(),
            )
            .unwrap()
            .source;
            assert!(
                output.starts_with(&format!("@{expected_entry_type}{{probe,")),
                "unsupported source alias was not mapped to `{expected_entry_type}`:\n{output}"
            );
        }
    }

    #[test]
    fn ieee_profile_preserves_bst_control_entries() {
        let output = export(
            &bibliography(
                "@IEEEtranBSTCTL{IEEEexample:BSTcontrol, CTLuse_article_number={yes}, CTLuse_forced_etal={no},}\n",
            ),
            &ExportProfile::builtin("ieee-publications").unwrap(),
        )
        .unwrap()
        .source;
        assert!(output.starts_with("@ieeetranbstctl{IEEEexample:BSTcontrol,"));
        assert!(output.contains("ctluse_article_number = {yes}"));
        assert!(output.contains("ctluse_forced_etal = {no}"));
    }

    #[test]
    fn artifact_profiles_use_target_field_names_and_month_macros() {
        for profile_id in ["acl", "lrec"] {
            let output = export(
                &bibliography(RICH_SOURCE),
                &ExportProfile::builtin(profile_id).unwrap(),
            )
            .unwrap()
            .source;
            assert!(output.contains("month = jul"), "profile `{profile_id}`");
            assert!(
                output.contains("pubmed = {12345}"),
                "profile `{profile_id}`"
            );
            assert!(!output.contains("pmid ="), "profile `{profile_id}`");
        }
    }

    #[test]
    fn field_projection_applies_to_structured_identifiers_and_extra_fields() {
        let bibliography = bibliography(RICH_SOURCE);
        let mut allowlist = ExportProfile::modern();
        allowlist.field_selection.allowed_fields =
            Some(["TITLE", "custom"].into_iter().map(str::to_owned).collect());
        let selected = export(&bibliography, &allowlist).unwrap().source;
        assert!(selected.contains("title = {Parsing \\& Generation}"));
        assert!(selected.contains("custom = {Modern only}"));
        for excluded in [
            "author =",
            "booktitle =",
            "year =",
            "doi =",
            "isbn =",
            "eprint =",
            "url =",
            "note =",
        ] {
            assert!(!selected.contains(excluded), "unexpected `{excluded}`");
        }

        let mut denylist = ExportProfile::modern();
        denylist.field_selection.excluded_fields = [
            "TITLE",
            "author",
            "doi",
            "isbn",
            "eprint",
            "archiveprefix",
            "url",
            "custom",
        ]
        .into_iter()
        .map(str::to_owned)
        .collect();
        let denied = export(&bibliography, &denylist).unwrap().source;
        for excluded in [
            "\n  title =",
            "\n  author =",
            "\n  doi =",
            "\n  isbn =",
            "\n  eprint =",
            "\n  archivePrefix =",
            "\n  url =",
            "\n  custom =",
        ] {
            assert!(!denied.contains(excluded), "unexpected `{excluded}`");
        }
        assert!(denied.contains("booktitle = {Proceedings of Testing}"));
    }

    #[test]
    fn field_selection_rejects_invalid_duplicates_and_conflicts() {
        let mut invalid = ExportProfile::modern();
        invalid.field_selection.allowed_fields = Some(
            ["title", "not a field"]
                .into_iter()
                .map(str::to_owned)
                .collect(),
        );
        assert!(matches!(
            invalid.validate(),
            Err(ExportError::InvalidFieldName(ref field)) if field == "not a field"
        ));

        let mut exact_duplicate = ExportProfile::modern();
        exact_duplicate.field_selection.allowed_fields =
            Some(vec![String::from("title"), String::from("title")]);
        assert!(matches!(
            exact_duplicate.validate(),
            Err(ExportError::InvalidProfile(ref message)) if message.contains("duplicate field")
        ));

        let mut case_duplicate = ExportProfile::modern();
        case_duplicate.field_selection.allowed_fields =
            Some(vec![String::from("title"), String::from("TITLE")]);
        assert!(matches!(
            case_duplicate.validate(),
            Err(ExportError::InvalidProfile(ref message)) if message.contains("duplicate field")
        ));

        let mut conflict = ExportProfile::modern();
        conflict.field_selection.allowed_fields =
            Some([String::from("Title")].into_iter().collect());
        conflict
            .field_selection
            .excluded_fields
            .push(String::from("title"));
        assert!(matches!(
            conflict.validate(),
            Err(ExportError::InvalidProfile(ref message)) if message.contains("both allowed and excluded")
        ));
    }

    #[test]
    fn entry_type_and_field_rename_configuration_is_validated() {
        let mut duplicate_entry_type = ExportProfile::modern();
        duplicate_entry_type.supported_entry_types =
            vec![String::from("webpage"), String::from("WebPage")];
        assert!(matches!(
            duplicate_entry_type.validate(),
            Err(ExportError::InvalidProfile(ref message)) if message.contains("duplicate field")
        ));

        let mut duplicate_target = ExportProfile::modern();
        duplicate_target
            .field_renames
            .insert(String::from("pmid"), String::from("pubmed"));
        duplicate_target
            .field_renames
            .insert(String::from("pmcid"), String::from("PUBMED"));
        assert!(matches!(
            duplicate_target.validate(),
            Err(ExportError::InvalidProfile(ref message)) if message.contains("duplicate field")
        ));

        let mut unselected_target = ExportProfile::modern();
        unselected_target.field_selection.allowed_fields = Some(vec![String::from("title")]);
        unselected_target
            .field_renames
            .insert(String::from("pmid"), String::from("pubmed"));
        assert!(matches!(
            unselected_target.validate(),
            Err(ExportError::InvalidProfile(ref message)) if message.contains("not selected")
        ));

        let records = bibliography("@misc{probe, title={Probe}, pmid={12345}, pubmed={67890},}\n");
        let mut conflicting_fields = ExportProfile::modern();
        conflicting_fields
            .field_renames
            .insert(String::from("pmid"), String::from("pubmed"));
        assert!(matches!(
            export(&records, &conflicting_fields),
            Err(ExportError::DuplicateField { ref field, .. }) if field == "pubmed"
        ));
    }

    #[test]
    fn generated_preprint_fields_merge_source_text_without_losing_information() {
        let records = bibliography(
            "@misc{preprint, title={T}, howpublished={Online first}, eprint={2401.01234}, archivePrefix={arXiv},}\n@article{published, title={P}, journal={J}, year={2024}, note={Accepted version}, eprint={2401.05678}, archivePrefix={arXiv},}\n",
        );
        let profile = ExportProfile::classical_bst();
        let first = export(&records, &profile).unwrap().source;
        assert!(first.contains("howpublished = {Online first; arXiv:2401.01234}"));
        assert!(first.contains("note = {Accepted version; Also available as arXiv:2401.05678}"));
        assert_eq!(first.matches("howpublished =").count(), 1);
        assert_eq!(first.matches("note =").count(), 1);

        let second = export(&bibliography(&first), &profile).unwrap().source;
        assert_eq!(second, first);
    }

    #[test]
    fn sparse_toml_defaults_from_baseline_without_recursing() {
        let profile = ExportProfile::from_toml(
            r#"
schema_version = "1"
profile = "custom"
display_name = "Custom"
description = "A sparse custom profile."
validation_profile = "modern"
"#,
        )
        .unwrap();
        assert_eq!(profile.profile.as_str(), "custom");
        assert_eq!(profile.field_selection, ExportFieldSelection::default());
        assert_eq!(
            profile.preprint_representation,
            PreprintRepresentation::MiscEprint
        );
    }

    #[test]
    fn same_preprint_has_three_deterministic_representations() {
        let bibliography = bibliography(
            "@misc{vaswani2017, title={Attention}, author={Vaswani, Ashish}, year={2017}, eprint={1706.03762}, archivePrefix={arXiv},}\n",
        );
        let eprint = export(&bibliography, &ExportProfile::laboratory())
            .unwrap()
            .source;
        assert!(eprint.starts_with("@misc{vaswani2017,"));
        assert!(eprint.contains("eprint = {1706.03762}"));
        assert!(eprint.contains("archiveprefix = {arXiv}"));

        let howpublished = export(&bibliography, &ExportProfile::classical_bst())
            .unwrap()
            .source;
        assert!(howpublished.starts_with("@misc{vaswani2017,"));
        assert!(howpublished.contains("howpublished = {arXiv:1706.03762}"));

        let article = export(&bibliography, &ExportProfile::legacy_arxiv_article())
            .unwrap()
            .source;
        assert!(article.starts_with("@article{vaswani2017,"));
        assert!(article.contains("journal = {arXiv:1706.03762}"));
    }

    #[test]
    fn published_article_with_related_preprint_stays_an_article() {
        let bibliography = bibliography(
            "@article{k, title={Published}, author={Doe, Jane}, journal={Journal}, year={2024}, doi={10.1000/example}, eprint={1706.03762}, archivePrefix={arXiv},}\n",
        );
        assert_eq!(
            bibliography.records[0].work_type.value,
            WorkType::JournalArticle
        );
        let output = export(&bibliography, &ExportProfile::laboratory())
            .unwrap()
            .source;
        assert!(output.starts_with("@article{k,"));
        assert!(output.contains("journal = {Journal}"));
        assert!(output.contains("eprint = {1706.03762}"));
    }

    #[test]
    fn field_order_and_output_are_stable() {
        let bibliography = bibliography(
            "@article{k, year={2020}, title={T}, author={Doe, Jane}, journal={J}, doi={10.1/x},}\n",
        );
        let first = export(&bibliography, &ExportProfile::modern()).unwrap();
        let second = export(&bibliography, &ExportProfile::modern()).unwrap();
        assert_eq!(first, second);
        assert!(first.source.find("author =").unwrap() < first.source.find("title =").unwrap());
        assert!(first.source.find("title =").unwrap() < first.source.find("journal =").unwrap());
    }

    #[test]
    fn escaping_is_deterministic_and_does_not_double_escape() {
        assert_eq!(
            escape_bibtex("A & B \\& C_1", ValueDelimiter::Braces),
            "A \\& B \\& C\\_1"
        );
        assert_eq!(
            escape_bibtex("line\r\nbreak", ValueDelimiter::Braces),
            "line break"
        );
    }

    #[test]
    fn prose_url_and_verbatim_commands_preserve_only_their_literal_arguments() {
        let records = bibliography(
            r"@misc{k,
  title={Outside 50% & C_1 # $5 \url{https://example.test/{part_1}/a%20_b?x=1&cost=$5#frag_1} after 60% \textbf{Bold 70% & C_2 # $6}},
  note={Note 20% \nolinkurl{https://example.test/b%20_c?x=2&cost=$6#frag_2} \verb|100% & C_3 # $7| \verb*+90% & C_4 # $8+ \Verb!80% & C_5 # $9!},
  howpublished={Path 30% \path{paper%20&draft_2#$} \lstinline[language=TeX]|70% & C_6 # $0|},
}
",
        );
        let profile = ExportProfile::modern();

        let first = export(&records, &profile).unwrap().source;
        assert!(first.contains(
            r"title = {Outside 50\% \& C\_1 \# \$5 \url{https://example.test/{part_1}/a%20_b?x=1&cost=$5#frag_1} after 60\% \textbf{Bold 70\% \& C\_2 \# \$6}}"
        ));
        assert!(first.contains(
            r"note = {Note 20\% \nolinkurl{https://example.test/b%20_c?x=2&cost=$6#frag_2} \verb|100% & C_3 # $7| \verb*+90% & C_4 # $8+ \Verb!80% & C_5 # $9!}"
        ));
        assert!(first.contains(
            r"howpublished = {Path 30\% \path{paper%20&draft_2#$} \lstinline[language=TeX]|70% & C_6 # $0|}"
        ));

        let second = export(&bibliography(&first), &profile).unwrap().source;
        assert_eq!(second, first);
    }

    #[test]
    fn verbatim_command_syntax_matches_validation_scanner() {
        let source = r"\Verb [formatcom=\small] /40% & C_1 # $5/ \lstinline* [language=TeX] 9numeric% & C_2 # $six9 \verb8digit% & C_3 # $seven8 \unknown|10% & C_4 # $2|";

        assert_eq!(
            escape_bibtex(source, ValueDelimiter::Braces),
            r"\Verb [formatcom=\small] /40% & C_1 # $5/ \lstinline* [language=TeX] 9numeric% & C_2 # $six9 \verb8digit% & C_3 # $seven8 \unknown|10\% \& C\_4 \# \$2|"
        );
    }

    #[test]
    fn prose_literal_commands_still_escape_quote_delimiters() {
        let records = bibliography(
            r#"@misc{k, title={Say "outside" 50% \url{https://example.test/a%20_b?label="inside"&cost=$5#frag_1} \verb|"literal" 20% & C_1 # $5| after 30%},}
"#,
        );
        let mut profile = ExportProfile::modern();
        profile.value_delimiter = ValueDelimiter::Quotes;

        let first = export(&records, &profile).unwrap().source;
        assert!(first.contains(
            r#"title = "Say \"outside\" 50\% \url{https://example.test/a%20_b?label=\"inside\"&cost=$5#frag_1} \verb|\"literal\" 20% & C_1 # $5| after 30\%""#
        ));

        let second = export(&bibliography(&first), &profile).unwrap().source;
        assert_eq!(second, first);
    }

    #[test]
    fn acm_archived_url_round_trips_without_identifier_escaping() {
        const ARCHIVED: &str = "https://archive.example.test/a%20b?left=a_b&price=$5#part_2";
        let records = bibliography(&format!(
            "@online{{k, title={{Archived}}, year={{2026}}, archived={{{ARCHIVED}}},}}\n"
        ));
        let profile = ExportProfile::builtin("acm-publications").unwrap();

        let first = export(&records, &profile).unwrap().source;
        assert!(first.contains(&format!("archived = {{{ARCHIVED}}}")));

        let reparsed = bibliography(&first);
        assert_eq!(
            reparsed.records[0]
                .extra_fields
                .iter()
                .find(|field| field.name.eq_ignore_ascii_case("archived"))
                .and_then(|field| field.value.resolved.as_deref()),
            Some(ARCHIVED)
        );
        assert_eq!(export(&reparsed, &profile).unwrap().source, first);
    }

    #[test]
    fn identifier_fields_preserve_tex_sensitive_characters() {
        let value = "part%20&query#fragment_$5";
        for field in [
            "url",
            "doi",
            "file",
            "eprint",
            "archivePrefix",
            "primaryClass",
            "isbn",
            "issn",
            "pmid",
            "pmcid",
            "pubmed",
        ] {
            assert_eq!(
                format_field_value(field, value, ValueDelimiter::Braces),
                format!("{{{value}}}"),
                "field `{field}`"
            );
        }
        assert_eq!(
            format_field_value("title", value, ValueDelimiter::Braces),
            "{part\\%20\\&query\\#fragment\\_\\$5}"
        );
        assert_eq!(
            format_field_value(
                "url",
                "https://example.test/a%20b?label=\"quoted\"\r\nnext",
                ValueDelimiter::Quotes,
            ),
            "\"https://example.test/a%20b?label=\\\"quoted\\\" next\""
        );
    }

    #[test]
    fn url_doi_and_file_values_round_trip_without_identifier_changes() {
        const DOI: &str = "10.1000/example_name";
        const URL: &str = "https://example.test/a%20b?left=a_b&price=$5#part_2";
        const FILE: &str = "paper%20draft_1&copy#part$.pdf";
        let records = bibliography(&format!(
            "@article{{k, title={{50% ready & C_1 # $5}}, journal={{J}}, year={{2024}}, doi={{{DOI}}}, url={{{URL}}}, file={{{FILE}}},}}\n"
        ));
        let original_doi = records.records[0]
            .identifiers
            .primary_doi()
            .unwrap()
            .value
            .as_str()
            .to_owned();
        let original_url = records.records[0].urls[0].value.as_str().to_owned();
        let original_file = records.records[0]
            .extra_fields
            .iter()
            .find(|field| field.name.eq_ignore_ascii_case("file"))
            .and_then(|field| field.value.resolved.clone())
            .unwrap();

        let output = export(&records, &ExportProfile::modern()).unwrap().source;
        assert!(output.contains("title = {50\\% ready \\& C\\_1 \\# \\$5}"));
        assert!(output.contains(&format!("doi = {{{DOI}}}")));
        assert!(output.contains(&format!("url = {{{URL}}}")));
        assert!(output.contains(&format!("file = {{{FILE}}}")));

        let reparsed = bibliography(&output);
        assert_eq!(
            reparsed.records[0]
                .identifiers
                .primary_doi()
                .unwrap()
                .value
                .as_str(),
            original_doi
        );
        assert_eq!(reparsed.records[0].urls[0].value.as_str(), original_url);
        assert_eq!(
            reparsed.records[0]
                .extra_fields
                .iter()
                .find(|field| field.name.eq_ignore_ascii_case("file"))
                .and_then(|field| field.value.resolved.as_deref()),
            Some(original_file.as_str())
        );
    }

    #[test]
    fn renamed_identifier_field_uses_its_target_name_for_formatting() {
        const PUBMED: &str = "123_45%67&copy#part$";
        let records = bibliography(&format!(
            "@misc{{k, title={{T}}, year={{2024}}, pmid={{{PUBMED}}},}}\n"
        ));
        let profile = ExportProfile::acl();

        let first = export(&records, &profile).unwrap().source;
        assert!(first.contains(&format!("pubmed = {{{PUBMED}}}")));
        assert!(!first.contains("pmid ="));

        let second = export(&bibliography(&first), &profile).unwrap().source;
        assert_eq!(second, first);
    }

    #[test]
    fn person_names_use_unambiguous_bibtex_order() {
        let person = Person {
            raw: String::from("Jane von Doe Jr."),
            given: vec![String::from("Jane")],
            family: vec![String::from("Doe")],
            prefix: vec![String::from("von")],
            suffix: vec![String::from("Jr.")],
            literal: None,
        };
        assert_eq!(format_person(&person), "von Doe, Jr., Jane");
    }

    #[test]
    fn invalid_profiles_are_rejected_without_panicking() {
        let mut profile = ExportProfile::default();
        profile.field_order.push(String::from("TITLE"));
        assert!(matches!(
            profile.validate(),
            Err(ExportError::DuplicateFieldOrder(_))
        ));
    }

    #[test]
    fn profile_round_trips_through_toml() {
        let profile = ExportProfile::laboratory();
        let encoded = toml::to_string(&profile).unwrap();
        assert_eq!(ExportProfile::from_toml(&encoded).unwrap(), profile);
    }

    #[test]
    fn structured_identifiers_are_exported_in_canonical_order() {
        let bibliography = bibliography(
            "@article{k, title={T}, journal={J}, year={2024}, doi={10.1000/example}, isbn={978-1-4028-9462-6}, issn={1234-567X}, pmid={12345}, pmcid={PMC67890},}\n",
        );
        let mut profile = ExportProfile::modern();
        profile.include_extra_fields = false;

        let output = export(&bibliography, &profile).unwrap().source;
        assert!(output.contains("isbn = {9781402894626}"));
        assert!(output.contains("issn = {1234-567X}"));
        assert!(output.contains("pmid = {12345}"));
        assert!(output.contains("pmcid = {PMC67890}"));
        assert!(output.find("isbn =").unwrap() < output.find("issn =").unwrap());
        assert!(output.find("issn =").unwrap() < output.find("doi =").unwrap());
        assert!(output.find("doi =").unwrap() < output.find("pmid =").unwrap());
        assert!(output.find("pmid =").unwrap() < output.find("pmcid =").unwrap());
    }

    #[test]
    fn unresolved_macro_is_rejected_instead_of_exported_as_literal_text() {
        let bibliography =
            bibliography("@misc{k, title={Resolved title}, customField=missingMacro,}\n");

        let error = export(&bibliography, &ExportProfile::modern()).unwrap_err();
        assert!(matches!(
            error,
            ExportError::UnresolvedField {
                record_index: 0,
                ref field,
            } if field == "customField"
        ));
    }

    #[test]
    fn semantic_export_preserves_date_precision() {
        let components = bibliography(
            "@article{k, title={T}, journal={J}, year={2024}, month={5}, day={17},}\n",
        );
        let component_output = export(&components, &ExportProfile::modern())
            .unwrap()
            .source;
        assert!(component_output.contains("year = {2024}"));
        assert!(component_output.contains("month = {5}"));
        assert!(component_output.contains("day = {17}"));

        let iso = bibliography("@misc{k, title={T}, date={2024-05-17},}\n");
        let iso_output = export(&iso, &ExportProfile::modern()).unwrap().source;
        assert!(iso_output.contains("year = {2024}"));
        assert!(iso_output.contains("date = {2024-05-17}"));
    }

    #[test]
    fn unresolved_date_is_not_silently_exported() {
        let bibliography = bibliography("@misc{k, title={T}, year={twenty},}\n");
        assert!(matches!(
            export(&bibliography, &ExportProfile::modern()),
            Err(ExportError::UnresolvedField {
                record_index: 0,
                ref field,
            }) if field == "date"
        ));
    }

    #[test]
    fn ambiguous_or_conflicting_semantics_are_never_silently_selected() {
        let ambiguous = bibliography(
            "@misc{k, title={T}, eprint={10.1101/123456}, archivePrefix={bioRxiv}, eprintType={medRxiv},}\n",
        );
        assert!(matches!(
            export(&ambiguous, &ExportProfile::modern()),
            Err(ExportError::AmbiguousSemantics {
                record_index: 0,
                ref kind,
            }) if kind == "multiple-preprint-repositories"
        ));

        let mut conflicting = bibliography(
            "@article{k, title={T}, journal={J}, year={2024}, doi={10.1000/one}, url={https://doi.org/10.1000/two},}\n",
        );
        assert!(!conflicting.records[0].conflicts.is_empty());
        conflicting.records[0].ambiguities.clear();
        assert!(matches!(
            export(&conflicting, &ExportProfile::modern()),
            Err(ExportError::ConflictingSemantics {
                record_index: 0,
                ref field,
            }) if field == "doi"
        ));

        let macro_ambiguity =
            bibliography("@string{x={One}}\n@string{x={Two}}\n@misc{k, title=x,}\n");
        assert!(matches!(
            export(&macro_ambiguity, &ExportProfile::modern()),
            Err(ExportError::AmbiguousSemantics {
                record_index: 0,
                ref kind,
            }) if kind == "ambiguous-macro-expansion"
        ));
    }

    #[test]
    fn export_profiles_drop_fields_forbidden_by_the_target_format() {
        let bibliography = bibliography(
            "@misc{k, title={T}, abstract={Private}, file={local.pdf}, url={https://example.test},}\n",
        );

        let laboratory = export(&bibliography, &ExportProfile::laboratory())
            .unwrap()
            .source;
        assert!(!laboratory.contains("abstract ="));
        assert!(!laboratory.contains("file ="));
        assert!(!laboratory.contains("url ="));

        let classical = export(&bibliography, &ExportProfile::classical_bst())
            .unwrap()
            .source;
        assert!(!classical.contains("file ="));
        assert!(!classical.contains("url ="));
    }

    #[test]
    fn export_does_not_change_thesis_level_or_proceedings_identity() {
        let masters = bibliography(
            "@mastersthesis{k, title={T}, author={Doe, Jane}, school={S}, year={2024},}\n",
        );
        let masters_output = export(&masters, &ExportProfile::modern()).unwrap().source;
        assert!(masters_output.starts_with("@mastersthesis{k,"));

        let proceedings = bibliography("@proceedings{p, title={Proceedings}, year={2024},}\n");
        let proceedings_output = export(&proceedings, &ExportProfile::modern())
            .unwrap()
            .source;
        assert!(proceedings_output.starts_with("@proceedings{p,"));
    }
}
