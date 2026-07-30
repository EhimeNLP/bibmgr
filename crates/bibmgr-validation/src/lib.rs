//! Shared deterministic validation and registration policy engine.

use bibmgr_model::{
    Diagnostic, DiagnosticId, Fix, FixApplicability, FixId, ProfileId, RelatedLocation, RuleCode,
    Severity, SourceLocation, SourceRevision, TextEdit, TextRange,
};
pub use bibmgr_semantics::VenueKind;
use bibmgr_semantics::{is_raw_identifier_field, Bibliography, WorkType};
use bibmgr_syntax::{EntryNode, FieldNode, SyntaxDocument, ValueAtomKind, ValueExpression};
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::sync::OnceLock;

pub const RULE_DUPLICATE_FIELD: &str = "BIB-SYNTAX-001";
pub const RULE_FIELD_CASE: &str = "BIB-SYNTAX-002";
pub const RULE_FIELD_ORDER: &str = "BIB-SYNTAX-003";
pub const RULE_TRAILING_COMMA: &str = "BIB-SYNTAX-004";
pub const RULE_VALUE_DELIMITER: &str = "BIB-SYNTAX-005";
pub const RULE_EQUALS_WHITESPACE: &str = "BIB-SYNTAX-006";
pub const RULE_INLINE_PERCENT_COMMENT: &str = "BIB-SYNTAX-007";
pub const RULE_UNESCAPED_TEX_SPECIAL: &str = "BIB-SYNTAX-008";
pub const RULE_VALUE_LINE_BREAKS: &str = "BIB-SYNTAX-009";
pub const RULE_UNESCAPED_PERCENT: &str = RULE_UNESCAPED_TEX_SPECIAL;
pub const RULE_DOI: &str = "BIB-SEMANTIC-001";
pub const RULE_ARXIV: &str = "BIB-SEMANTIC-002";
pub const RULE_REQUIRED_DATA: &str = "BIB-SEMANTIC-003";
pub const RULE_TYPE_MISMATCH: &str = "BIB-SEMANTIC-004";
pub const RULE_IDENTIFIER_CONFLICT: &str = "BIB-SEMANTIC-005";
pub const RULE_AUTHOR: &str = "BIB-SEMANTIC-006";
pub const RULE_DATE: &str = "BIB-SEMANTIC-007";
pub const RULE_UNRESOLVED_SEMANTICS: &str = "BIB-SEMANTIC-008";
pub const RULE_DUPLICATE_CITATION_KEY: &str = "BIB-SEMANTIC-009";
pub const RULE_DUPLICATE_DOI: &str = "BIB-SEMANTIC-010";
pub const RULE_DUPLICATE_ARXIV: &str = "BIB-SEMANTIC-011";
pub const RULE_REPOSITORY_IDENTIFIER: &str = "BIB-SEMANTIC-012";
pub const RULE_CITATION_KEY: &str = "LAB-KEY-002";
pub const RULE_REQUIRED_FIELDS: &str = "LAB-ENTRY-003";
pub const RULE_FORBIDDEN_FIELDS: &str = "LAB-ENTRY-004";
pub const RULE_ARXIV_REPRESENTATION: &str = "LAB-ARXIV-001";
pub const RULE_URL_POLICY: &str = "LAB-URL-001";

pub const REGISTERED_RULE_CODES: &[&str] = &[
    "BIB-SYNTAX-101",
    "BIB-SYNTAX-102",
    "BIB-SYNTAX-103",
    "BIB-SYNTAX-104",
    "BIB-SYNTAX-105",
    "BIB-SYNTAX-106",
    "BIB-SYNTAX-107",
    "BIB-SYNTAX-108",
    "BIB-SYNTAX-109",
    "BIB-SYNTAX-110",
    "BIB-SYNTAX-111",
    "BIB-SYNTAX-112",
    RULE_DUPLICATE_FIELD,
    RULE_FIELD_CASE,
    RULE_FIELD_ORDER,
    RULE_TRAILING_COMMA,
    RULE_VALUE_DELIMITER,
    RULE_EQUALS_WHITESPACE,
    RULE_INLINE_PERCENT_COMMENT,
    RULE_UNESCAPED_TEX_SPECIAL,
    RULE_VALUE_LINE_BREAKS,
    "BIB-SEMANTIC-101",
    "BIB-SEMANTIC-102",
    "BIB-SEMANTIC-106",
    RULE_DOI,
    RULE_ARXIV,
    RULE_REQUIRED_DATA,
    RULE_TYPE_MISMATCH,
    RULE_IDENTIFIER_CONFLICT,
    RULE_AUTHOR,
    RULE_DATE,
    RULE_UNRESOLVED_SEMANTICS,
    RULE_DUPLICATE_CITATION_KEY,
    RULE_DUPLICATE_DOI,
    RULE_DUPLICATE_ARXIV,
    RULE_REPOSITORY_IDENTIFIER,
    RULE_CITATION_KEY,
    RULE_REQUIRED_FIELDS,
    RULE_FORBIDDEN_FIELDS,
    RULE_ARXIV_REPRESENTATION,
    RULE_URL_POLICY,
];

const RETIRED_RULE_CODE_ALIASES: &[(&str, &str)] = &[
    ("BIB-SEMANTIC-103", RULE_DOI),
    ("BIB-SEMANTIC-104", RULE_ARXIV),
    ("BIB-SEMANTIC-105", RULE_DATE),
];

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "kebab-case")]
pub enum FieldCase {
    #[default]
    Lowercase,
    Canonical,
    Preserve,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "kebab-case")]
pub enum ArxivRepresentation {
    #[default]
    Any,
    Eprint,
    Howpublished,
    ArticleJournal,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "kebab-case")]
pub enum UrlPolicy {
    #[default]
    Allow,
    Discourage,
    Forbid,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct RuleSetting {
    pub enabled: bool,
    pub severity: Severity,
    pub blocking: bool,
}

impl Default for RuleSetting {
    fn default() -> Self {
        Self {
            enabled: true,
            severity: Severity::Warning,
            blocking: false,
        }
    }
}

/// TOML-friendly validation configuration. Missing rule overrides use embedded defaults.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default = "ValidationPolicy::baseline", deny_unknown_fields)]
pub struct ValidationPolicy {
    pub schema_version: String,
    /// Optional parent id for registries that resolve profile inheritance.
    pub extends: Option<ProfileId>,
    pub profile: ProfileId,
    pub field_case: FieldCase,
    pub field_order: Vec<String>,
    pub citation_key_pattern: String,
    pub required_fields: BTreeMap<String, Vec<String>>,
    pub forbidden_fields: BTreeSet<String>,
    pub url_policy: UrlPolicy,
    pub arxiv_representation: ArxivRepresentation,
    pub prefer_braces: bool,
    pub rules: BTreeMap<RuleCode, RuleSetting>,
}

impl Default for ValidationPolicy {
    fn default() -> Self {
        Self::modern()
    }
}

impl ValidationPolicy {
    pub fn archive() -> Self {
        Self::builtin("archive").unwrap_or_else(|_| {
            let mut policy = Self::baseline();
            policy.profile = ProfileId::new("archive");
            policy.field_case = FieldCase::Preserve;
            policy.field_order.clear();
            policy.citation_key_pattern =
                String::from(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*-[0-9]{4}-[a-z0-9]+(?:-[a-z0-9]+)*$");
            policy.required_fields.clear();
            policy.rules.insert(
                RuleCode::new(RULE_CITATION_KEY),
                RuleSetting {
                    enabled: true,
                    severity: Severity::Warning,
                    blocking: true,
                },
            );
            policy
        })
    }

    pub fn modern() -> Self {
        Self::builtin("modern").unwrap_or_else(|_| Self::baseline())
    }

    fn baseline() -> Self {
        Self {
            schema_version: String::from(bibmgr_model::SCHEMA_VERSION),
            extends: None,
            profile: ProfileId::new("modern"),
            field_case: FieldCase::Lowercase,
            field_order: default_field_order(),
            citation_key_pattern: String::from(r"^[A-Za-z][A-Za-z0-9_:+./-]*$"),
            required_fields: default_required_fields(),
            forbidden_fields: BTreeSet::new(),
            url_policy: UrlPolicy::Allow,
            arxiv_representation: ArxivRepresentation::Any,
            prefer_braces: true,
            rules: default_rule_settings(),
        }
    }

    pub fn laboratory() -> Self {
        Self::builtin("laboratory").unwrap_or_else(|_| {
            let mut policy = Self::baseline();
            policy.profile = ProfileId::new("laboratory");
            policy
        })
    }

    pub fn acl() -> Self {
        Self::builtin("acl").unwrap_or_else(|_| {
            let mut policy = Self::baseline();
            policy.profile = ProfileId::new("acl");
            policy
        })
    }

    pub fn classical_bst() -> Self {
        Self::builtin("classical-bst").unwrap_or_else(|_| {
            let mut policy = Self::baseline();
            policy.profile = ProfileId::new("classical-bst");
            policy
        })
    }

    pub fn builtin(profile: &str) -> Result<Self, ConfigurationError> {
        match profile {
            "archive" => Self::from_toml(include_str!("../../../config/policies/archive.toml")),
            "default" | "modern" => {
                Self::from_toml(include_str!("../../../config/policies/modern.toml"))
            }
            "laboratory" => {
                Self::from_toml(include_str!("../../../config/policies/laboratory.toml"))
            }
            "acl" => Self::from_toml(include_str!("../../../config/policies/acl.toml")),
            "classical-bst" => {
                Self::from_toml(include_str!("../../../config/policies/classical-bst.toml"))
            }
            other => Err(ConfigurationError::UnknownProfile(other.to_owned())),
        }
    }

    pub fn for_profile(profile: &ProfileId) -> Result<Self, ConfigurationError> {
        Self::builtin(profile.as_str())
    }

    pub fn from_toml(input: &str) -> Result<Self, ConfigurationError> {
        let mut policy: Self = toml::from_str(input).map_err(ConfigurationError::Toml)?;
        migrate_deprecated_rule_settings(&mut policy.rules)?;
        policy.validate_configuration()?;
        Ok(policy)
    }

    pub fn validate_configuration(&self) -> Result<(), ConfigurationError> {
        if self.profile.as_str().trim().is_empty() {
            return Err(ConfigurationError::EmptyProfile);
        }
        if self.schema_version != bibmgr_model::SCHEMA_VERSION {
            return Err(ConfigurationError::UnsupportedSchemaVersion(
                self.schema_version.clone(),
            ));
        }
        if self.extends.as_ref() == Some(&self.profile) {
            return Err(ConfigurationError::InheritanceCycle(vec![
                self.profile.clone(),
                self.profile.clone(),
            ]));
        }
        Regex::new(&self.citation_key_pattern)
            .map_err(|error| ConfigurationError::InvalidCitationKeyRegex(error.to_string()))?;

        let mut fields = BTreeSet::new();
        for field in &self.field_order {
            let normalized = field.to_ascii_lowercase();
            if normalized.is_empty() || !is_field_name(&normalized) {
                return Err(ConfigurationError::InvalidFieldName(field.clone()));
            }
            if !fields.insert(normalized) {
                return Err(ConfigurationError::DuplicateFieldOrder(field.clone()));
            }
        }
        for fields in self.required_fields.values() {
            for field in fields {
                if !is_field_name(field) {
                    return Err(ConfigurationError::InvalidFieldName(field.clone()));
                }
            }
        }
        for code in self.rules.keys() {
            if !REGISTERED_RULE_CODES.contains(&code.as_str()) {
                return Err(ConfigurationError::UnknownRule(code.clone()));
            }
        }
        Ok(())
    }

    fn setting(&self, code: &str) -> RuleSetting {
        self.rules
            .get(&RuleCode::new(code))
            .cloned()
            .unwrap_or_else(|| default_rule_setting(code))
    }
}

#[derive(Debug, thiserror::Error)]
pub enum ConfigurationError {
    #[error("unknown validation profile `{0}`")]
    UnknownProfile(String),
    #[error("validation profile id cannot be empty")]
    EmptyProfile,
    #[error("unsupported configuration schema version `{0}`")]
    UnsupportedSchemaVersion(String),
    #[error("validation profile inheritance cycle: {0:?}")]
    InheritanceCycle(Vec<ProfileId>),
    #[error("duplicate validation profile `{0}`")]
    DuplicateProfile(ProfileId),
    #[error("profile `{profile}` extends missing profile `{parent}`")]
    MissingParentProfile {
        profile: ProfileId,
        parent: ProfileId,
    },
    #[error("unknown rule code `{0}`")]
    UnknownRule(RuleCode),
    #[error("deprecated rule code `{deprecated}` conflicts with canonical code `{canonical}`")]
    ConflictingRuleAlias {
        deprecated: RuleCode,
        canonical: RuleCode,
    },
    #[error("invalid citation key regular expression: {0}")]
    InvalidCitationKeyRegex(String),
    #[error("field order contains duplicate field `{0}`")]
    DuplicateFieldOrder(String),
    #[error("invalid BibTeX field name `{0}`")]
    InvalidFieldName(String),
    #[error("duplicate venue id `{0}`")]
    DuplicateVenueId(String),
    #[error("venue alias `{alias}` refers to both `{first}` and `{second}`")]
    VenueAliasConflict {
        alias: String,
        first: String,
        second: String,
    },
    #[error("duplicate repository id `{0}`")]
    DuplicateRepositoryId(String),
    #[error("repository alias `{alias}` refers to both `{first}` and `{second}`")]
    RepositoryAliasConflict {
        alias: String,
        first: String,
        second: String,
    },
    #[error("repository `{repository}` has invalid identifier pattern: {message}")]
    InvalidRepositoryPattern { repository: String, message: String },
    #[error("repository `{0}` URL template must contain `{{identifier}}`")]
    InvalidRepositoryUrlTemplate(String),
    #[error("invalid registry id `{0}`")]
    InvalidRegistryId(String),
    #[error("invalid validation policy TOML: {0}")]
    Toml(toml::de::Error),
}

/// Validate uniqueness, parent existence, and cycles for a collection of profiles.
pub fn validate_policy_registry(policies: &[ValidationPolicy]) -> Result<(), ConfigurationError> {
    let mut by_id = BTreeMap::new();
    for policy in policies {
        policy.validate_configuration()?;
        if by_id.insert(policy.profile.clone(), policy).is_some() {
            return Err(ConfigurationError::DuplicateProfile(policy.profile.clone()));
        }
    }
    for policy in policies {
        if let Some(parent) = &policy.extends {
            if !by_id.contains_key(parent) {
                return Err(ConfigurationError::MissingParentProfile {
                    profile: policy.profile.clone(),
                    parent: parent.clone(),
                });
            }
        }
    }

    let mut complete = BTreeSet::new();
    for id in by_id.keys() {
        let mut path = Vec::new();
        visit_profile(id, &by_id, &mut path, &mut complete)?;
    }
    Ok(())
}

fn visit_profile(
    id: &ProfileId,
    policies: &BTreeMap<ProfileId, &ValidationPolicy>,
    path: &mut Vec<ProfileId>,
    complete: &mut BTreeSet<ProfileId>,
) -> Result<(), ConfigurationError> {
    if complete.contains(id) {
        return Ok(());
    }
    if let Some(cycle_start) = path.iter().position(|item| item == id) {
        let mut cycle = path[cycle_start..].to_vec();
        cycle.push(id.clone());
        return Err(ConfigurationError::InheritanceCycle(cycle));
    }
    path.push(id.clone());
    if let Some(parent) = policies.get(id).and_then(|policy| policy.extends.as_ref()) {
        visit_profile(parent, policies, path, complete)?;
    }
    path.pop();
    complete.insert(id.clone());
    Ok(())
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct VenueEntity {
    pub id: String,
    pub full_name: String,
    pub short_name: String,
    #[serde(default)]
    pub aliases: Vec<String>,
    pub kind: VenueKind,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct VenueRegistry {
    pub schema_version: String,
    #[serde(default)]
    pub venues: Vec<VenueEntity>,
}

impl VenueRegistry {
    /// Load the registry embedded in the binary so basic operation never
    /// depends on a runtime configuration file being present.
    pub fn builtin() -> Result<Self, ConfigurationError> {
        Self::from_toml(include_str!("../../../config/registries/venues.toml"))
    }

    pub fn from_toml(input: &str) -> Result<Self, ConfigurationError> {
        let registry: Self = toml::from_str(input).map_err(ConfigurationError::Toml)?;
        registry.validate()?;
        Ok(registry)
    }

    pub fn validate(&self) -> Result<(), ConfigurationError> {
        validate_schema_version(&self.schema_version)?;
        let mut ids = BTreeSet::new();
        let mut names = BTreeMap::<String, String>::new();
        for venue in &self.venues {
            let id = normalized_id(&venue.id)?;
            if !ids.insert(id.clone()) {
                return Err(ConfigurationError::DuplicateVenueId(venue.id.clone()));
            }
            for name in std::iter::once(&venue.full_name)
                .chain(std::iter::once(&venue.short_name))
                .chain(&venue.aliases)
            {
                register_venue_alias(&mut names, name, &id, |alias, first, second| {
                    ConfigurationError::VenueAliasConflict {
                        alias,
                        first,
                        second,
                    }
                })?;
            }
        }
        Ok(())
    }

    pub fn resolve(&self, name: &str) -> Option<&VenueEntity> {
        let normalized = normalize_venue_alias(name);
        self.venues.iter().find(|venue| {
            normalize_venue_alias(&venue.id) == normalized
                || normalize_venue_alias(&venue.full_name) == normalized
                || normalize_venue_alias(&venue.short_name) == normalized
                || venue
                    .aliases
                    .iter()
                    .any(|alias| normalize_venue_alias(alias) == normalized)
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RepositoryEntity {
    pub id: String,
    pub full_name: String,
    pub short_name: String,
    #[serde(default)]
    pub aliases: Vec<String>,
    pub archive_prefix: String,
    pub identifier_pattern: String,
    pub url_template: String,
}

impl RepositoryEntity {
    pub fn accepts_identifier(&self, identifier: &str) -> bool {
        Regex::new(&self.identifier_pattern)
            .ok()
            .is_some_and(|pattern| pattern.is_match(identifier))
    }

    pub fn identifier_url(&self, identifier: &str) -> Option<String> {
        self.accepts_identifier(identifier)
            .then(|| self.url_template.replace("{identifier}", identifier))
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RepositoryRegistry {
    pub schema_version: String,
    #[serde(default)]
    pub repositories: Vec<RepositoryEntity>,
}

impl RepositoryRegistry {
    /// Load the repository registry embedded in the binary.
    pub fn builtin() -> Result<Self, ConfigurationError> {
        Self::from_toml(include_str!("../../../config/registries/repositories.toml"))
    }

    pub fn from_toml(input: &str) -> Result<Self, ConfigurationError> {
        let registry: Self = toml::from_str(input).map_err(ConfigurationError::Toml)?;
        registry.validate()?;
        Ok(registry)
    }

    pub fn validate(&self) -> Result<(), ConfigurationError> {
        validate_schema_version(&self.schema_version)?;
        let mut ids = BTreeSet::new();
        let mut names = BTreeMap::<String, String>::new();
        for repository in &self.repositories {
            let id = normalized_id(&repository.id)?;
            if !ids.insert(id.clone()) {
                return Err(ConfigurationError::DuplicateRepositoryId(
                    repository.id.clone(),
                ));
            }
            Regex::new(&repository.identifier_pattern).map_err(|error| {
                ConfigurationError::InvalidRepositoryPattern {
                    repository: repository.id.clone(),
                    message: error.to_string(),
                }
            })?;
            if !repository.url_template.contains("{identifier}") {
                return Err(ConfigurationError::InvalidRepositoryUrlTemplate(
                    repository.id.clone(),
                ));
            }
            for name in std::iter::once(&repository.full_name)
                .chain(std::iter::once(&repository.short_name))
                .chain(std::iter::once(&repository.archive_prefix))
                .chain(&repository.aliases)
            {
                register_alias(&mut names, name, &id, |alias, first, second| {
                    ConfigurationError::RepositoryAliasConflict {
                        alias,
                        first,
                        second,
                    }
                })?;
            }
        }
        Ok(())
    }

    pub fn resolve(&self, name: &str) -> Option<&RepositoryEntity> {
        let normalized = normalize_alias(name);
        self.repositories.iter().find(|repository| {
            normalize_alias(&repository.id) == normalized
                || normalize_alias(&repository.full_name) == normalized
                || normalize_alias(&repository.short_name) == normalized
                || normalize_alias(&repository.archive_prefix) == normalized
                || repository
                    .aliases
                    .iter()
                    .any(|alias| normalize_alias(alias) == normalized)
        })
    }
}

fn validate_schema_version(version: &str) -> Result<(), ConfigurationError> {
    if version == bibmgr_model::SCHEMA_VERSION {
        Ok(())
    } else {
        Err(ConfigurationError::UnsupportedSchemaVersion(
            version.to_owned(),
        ))
    }
}

fn normalized_id(id: &str) -> Result<String, ConfigurationError> {
    let id = id.trim().to_ascii_lowercase();
    if id.is_empty()
        || !id
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-')
    {
        Err(ConfigurationError::InvalidRegistryId(id))
    } else {
        Ok(id)
    }
}

fn normalize_alias(alias: &str) -> String {
    alias
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_lowercase()
}

fn normalize_venue_alias(alias: &str) -> String {
    let mut normalized = normalize_alias(alias);
    if let Some(volume) = normalized
        .find(" (volume ")
        .or_else(|| normalized.find(": volume "))
    {
        normalized.truncate(volume);
    }
    let Some(last_word) = normalized.split_whitespace().next_back() else {
        return normalized;
    };
    let year = last_word.trim_matches(|character: char| {
        matches!(character, ',' | '.' | ':' | ';' | '(' | ')' | '[' | ']')
    });
    if year.len() == 4
        && year.bytes().all(|byte| byte.is_ascii_digit())
        && matches!(year.parse::<u16>(), Ok(1900..=2199))
    {
        let new_length = normalized.rfind(last_word).unwrap_or(normalized.len());
        normalized.truncate(new_length);
        normalized = normalized
            .trim_end_matches(|character: char| {
                character.is_whitespace() || matches!(character, ',' | '.' | ':' | ';' | '-' | '–')
            })
            .to_owned();
    }
    for prefix in ["proceedings of the ", "proceedings of "] {
        if let Some(remainder) = normalized.strip_prefix(prefix) {
            normalized = remainder.to_owned();
            break;
        }
    }
    if let Some((first_word, remainder)) = normalized.split_once(' ') {
        if is_edition_word(first_word) || is_year_word(first_word) {
            normalized = remainder.to_owned();
        }
    }
    normalized
}

fn is_edition_word(value: &str) -> bool {
    let digits = value.trim_end_matches(|character: char| character.is_ascii_alphabetic());
    !digits.is_empty()
        && digits.len() < value.len()
        && digits.bytes().all(|byte| byte.is_ascii_digit())
        && matches!(&value[digits.len()..], "st" | "nd" | "rd" | "th")
}

fn is_year_word(value: &str) -> bool {
    value.len() == 4
        && value.bytes().all(|byte| byte.is_ascii_digit())
        && matches!(value.parse::<u16>(), Ok(1900..=2199))
}

fn register_venue_alias(
    aliases: &mut BTreeMap<String, String>,
    alias: &str,
    id: &str,
    conflict: impl FnOnce(String, String, String) -> ConfigurationError,
) -> Result<(), ConfigurationError> {
    let alias = normalize_venue_alias(alias);
    register_normalized_alias(aliases, alias, id, conflict)
}

fn register_alias(
    aliases: &mut BTreeMap<String, String>,
    alias: &str,
    id: &str,
    conflict: impl FnOnce(String, String, String) -> ConfigurationError,
) -> Result<(), ConfigurationError> {
    let alias = normalize_alias(alias);
    register_normalized_alias(aliases, alias, id, conflict)
}

fn register_normalized_alias(
    aliases: &mut BTreeMap<String, String>,
    alias: String,
    id: &str,
    conflict: impl FnOnce(String, String, String) -> ConfigurationError,
) -> Result<(), ConfigurationError> {
    if alias.is_empty() {
        return Err(ConfigurationError::InvalidRegistryId(alias));
    }
    if let Some(existing) = aliases.get(&alias) {
        if existing != id {
            return Err(conflict(alias, existing.clone(), id.to_owned()));
        }
    } else {
        aliases.insert(alias, id.to_owned());
    }
    Ok(())
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(default, deny_unknown_fields)]
pub struct RuleSelector {
    pub all: bool,
    pub include: BTreeSet<RuleCode>,
    pub exclude: BTreeSet<RuleCode>,
}

impl RuleSelector {
    pub fn matches(&self, code: &RuleCode) -> bool {
        !self.exclude.contains(code) && (self.all || self.include.contains(code))
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct RegistrationPolicy {
    pub schema_version: String,
    pub validation_profile: ProfileId,
    pub minimum_severity: Option<Severity>,
    pub blocking_rules: RuleSelector,
    pub allow_unresolved_semantics: bool,
    pub apply_safe_fixes: bool,
}

impl Default for RegistrationPolicy {
    fn default() -> Self {
        Self {
            schema_version: String::from(bibmgr_model::SCHEMA_VERSION),
            validation_profile: ProfileId::new("modern"),
            minimum_severity: Some(Severity::Error),
            blocking_rules: RuleSelector::default(),
            allow_unresolved_semantics: true,
            apply_safe_fixes: false,
        }
    }
}

impl RegistrationPolicy {
    pub fn archive() -> Self {
        Self {
            schema_version: String::from(bibmgr_model::SCHEMA_VERSION),
            validation_profile: ProfileId::new("archive"),
            minimum_severity: None,
            blocking_rules: RuleSelector::default(),
            allow_unresolved_semantics: true,
            apply_safe_fixes: false,
        }
    }

    pub fn laboratory() -> Self {
        Self {
            schema_version: String::from(bibmgr_model::SCHEMA_VERSION),
            validation_profile: ProfileId::new("laboratory"),
            minimum_severity: Some(Severity::Error),
            blocking_rules: RuleSelector::default(),
            allow_unresolved_semantics: false,
            apply_safe_fixes: false,
        }
    }

    pub fn for_profile(profile: &ProfileId) -> Result<Self, ConfigurationError> {
        match profile.as_str() {
            "archive" => Ok(Self::archive()),
            "default" | "modern" | "acl" | "classical-bst" => Ok(Self {
                validation_profile: profile.clone(),
                ..Self::default()
            }),
            "laboratory" => Ok(Self::laboratory()),
            other => Err(ConfigurationError::UnknownProfile(other.to_owned())),
        }
    }

    pub fn from_toml(input: &str) -> Result<Self, ConfigurationError> {
        let mut policy: Self = toml::from_str(input).map_err(ConfigurationError::Toml)?;
        migrate_deprecated_rule_set(&mut policy.blocking_rules.include);
        migrate_deprecated_rule_set(&mut policy.blocking_rules.exclude);
        policy.validate_configuration()?;
        Ok(policy)
    }

    pub fn validate_configuration(&self) -> Result<(), ConfigurationError> {
        if self.schema_version != bibmgr_model::SCHEMA_VERSION {
            return Err(ConfigurationError::UnsupportedSchemaVersion(
                self.schema_version.clone(),
            ));
        }
        if self.validation_profile.as_str().trim().is_empty() {
            return Err(ConfigurationError::EmptyProfile);
        }
        for code in self
            .blocking_rules
            .include
            .iter()
            .chain(&self.blocking_rules.exclude)
        {
            if !REGISTERED_RULE_CODES.contains(&code.as_str()) {
                return Err(ConfigurationError::UnknownRule(code.clone()));
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct ValidationResult {
    pub diagnostics: Vec<Diagnostic>,
    pub fixes: Vec<Fix>,
}

impl ValidationResult {
    pub fn has_blocking_diagnostics(&self) -> bool {
        self.diagnostics
            .iter()
            .any(|diagnostic| diagnostic.blocking)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RegistrationValidation {
    pub accepted: bool,
    pub diagnostics: Vec<Diagnostic>,
    pub safe_fix_ids: Vec<FixId>,
    pub unresolved_semantics: bool,
}

/// Run every enabled rule, returning diagnostics and fixes in stable order.
pub fn validate(
    syntax: &SyntaxDocument,
    semantics: &Bibliography,
    policy: &ValidationPolicy,
) -> ValidationResult {
    let mut engine = Engine::new(syntax, policy);
    engine.import_diagnostics(syntax.diagnostics());
    engine.import_diagnostics(&semantics.diagnostics);

    for (entry_index, entry) in syntax.entries().iter().enumerate() {
        engine.validate_entry_syntax(entry);
        engine.validate_identifiers(entry);
        engine.validate_laboratory(entry);
        if let Some(record) = semantics.records.get(entry_index) {
            engine.validate_semantics(entry, record);
        }
    }
    engine.validate_referenced_string_tex_specials();
    engine.validate_bibliography_duplicates(semantics);
    engine.finish()
}

/// Apply registration-specific blocking semantics to a shared validation run.
pub fn validate_for_registration(
    syntax: &SyntaxDocument,
    semantics: &Bibliography,
    validation_policy: &ValidationPolicy,
    registration_policy: &RegistrationPolicy,
) -> RegistrationValidation {
    let result = validate(syntax, semantics, validation_policy);
    let unresolved_semantics = semantics.has_unresolved_semantics();
    let mut diagnostics = result.diagnostics;
    apply_registration_blocking(&mut diagnostics, registration_policy);
    let safe_fix_ids = result
        .fixes
        .iter()
        .filter(|fix| fix.applicability == FixApplicability::Safe)
        .map(|fix| fix.id.clone())
        .collect();
    let accepted = !semantics.records.is_empty()
        && !diagnostics.iter().any(|diagnostic| diagnostic.blocking)
        && (registration_policy.allow_unresolved_semantics || !unresolved_semantics);
    RegistrationValidation {
        accepted,
        diagnostics,
        safe_fix_ids,
        unresolved_semantics,
    }
}

/// Mark diagnostics that become blocking under registration-only policy.
///
/// Keeping this mutation in the validation crate ensures the Rust facade and
/// direct validation consumers return the same authoritative presentation.
pub fn apply_registration_blocking(diagnostics: &mut [Diagnostic], policy: &RegistrationPolicy) {
    for diagnostic in diagnostics {
        let severity_blocks = policy
            .minimum_severity
            .is_some_and(|minimum| diagnostic.severity.rank() >= minimum.rank());
        diagnostic.blocking |= severity_blocks
            || policy.blocking_rules.matches(&diagnostic.code)
            || (!policy.allow_unresolved_semantics
                && diagnostic.code.as_str() == RULE_UNRESOLVED_SEMANTICS);
    }
}

/// Decide registration eligibility from an already validated diagnostic set.
///
/// This helper is useful to high-level facades that have already run [`validate`].
pub fn registration_allowed(
    diagnostics: &[Diagnostic],
    semantics: &Bibliography,
    policy: &RegistrationPolicy,
) -> bool {
    if semantics.records.is_empty() {
        return false;
    }
    let unresolved = semantics.has_unresolved_semantics();
    if unresolved && !policy.allow_unresolved_semantics {
        return false;
    }
    !diagnostics.iter().any(|diagnostic| {
        diagnostic.blocking
            || policy.blocking_rules.matches(&diagnostic.code)
            || policy
                .minimum_severity
                .is_some_and(|minimum| diagnostic.severity.rank() >= minimum.rank())
    })
}

struct Engine<'a> {
    syntax: &'a SyntaxDocument,
    policy: &'a ValidationPolicy,
    revision: SourceRevision,
    diagnostics: Vec<Diagnostic>,
    fixes: Vec<Fix>,
    counters: BTreeMap<&'static str, usize>,
}

impl<'a> Engine<'a> {
    fn new(syntax: &'a SyntaxDocument, policy: &'a ValidationPolicy) -> Self {
        Self {
            syntax,
            policy,
            revision: SourceRevision::of(syntax.to_source()),
            diagnostics: Vec::new(),
            fixes: Vec::new(),
            counters: BTreeMap::new(),
        }
    }

    fn import_diagnostics(&mut self, diagnostics: &[Diagnostic]) {
        for diagnostic in diagnostics {
            let setting = self.policy.setting(diagnostic.code.as_str());
            if setting.enabled {
                let mut diagnostic = diagnostic.clone();
                diagnostic.severity = setting.severity;
                diagnostic.blocking = setting.blocking;
                self.diagnostics.push(diagnostic);
            }
        }
    }

    fn validate_bibliography_duplicates(&mut self, bibliography: &Bibliography) {
        let mut citation_keys = BTreeMap::<String, Vec<TextRange>>::new();
        let mut dois = BTreeMap::<String, Vec<TextRange>>::new();
        let mut arxiv_ids = BTreeMap::<String, Vec<TextRange>>::new();

        for record in &bibliography.records {
            let entry_range = record.source_range().unwrap_or_default();
            let citation_range = record
                .citation_key
                .origins
                .first()
                .map_or(entry_range, |origin| origin.range);
            citation_keys
                .entry(record.citation_key.value.as_str().to_ascii_lowercase())
                .or_default()
                .push(citation_range);

            for identifier in &record.identifiers.dois {
                let range = identifier
                    .origins
                    .first()
                    .map_or(entry_range, |origin| origin.range);
                dois.entry(identifier.value.as_str().to_ascii_lowercase())
                    .or_default()
                    .push(range);
            }
            for identifier in &record.identifiers.arxiv {
                let range = identifier
                    .origins
                    .first()
                    .map_or(entry_range, |origin| origin.range);
                arxiv_ids
                    .entry(identifier.value.as_str().to_ascii_lowercase())
                    .or_default()
                    .push(range);
            }
        }

        self.emit_duplicate_groups(RULE_DUPLICATE_CITATION_KEY, "citation key", citation_keys);
        self.emit_duplicate_groups(RULE_DUPLICATE_DOI, "DOI", dois);
        self.emit_duplicate_groups(RULE_DUPLICATE_ARXIV, "arXiv identifier", arxiv_ids);
    }

    fn emit_duplicate_groups(
        &mut self,
        code: &'static str,
        label: &str,
        groups: BTreeMap<String, Vec<TextRange>>,
    ) {
        for (value, ranges) in groups {
            if ranges.len() < 2 {
                continue;
            }
            let related_locations = ranges[1..]
                .iter()
                .copied()
                .map(|range| RelatedLocation {
                    message: format!("same {label} appears here"),
                    location: self.location(range),
                })
                .collect();
            self.emit(
                code,
                format!("{label} `{value}` is used by multiple records"),
                ranges[0],
                related_locations,
                vec![String::from(
                    "duplicate identities must be resolved before registration or export",
                )],
                None,
            );
        }
    }

    #[allow(clippy::too_many_lines)]
    fn validate_entry_syntax(&mut self, entry: &EntryNode) {
        let mut first_fields: BTreeMap<String, &FieldNode> = BTreeMap::new();
        for field in &entry.fields {
            let normalized = field.name.text.to_ascii_lowercase();
            if let Some(first) = first_fields.get(&normalized) {
                self.emit(
                    RULE_DUPLICATE_FIELD,
                    format!("field `{}` is repeated", field.name.text),
                    field.name.range,
                    vec![RelatedLocation {
                        message: String::from("first occurrence"),
                        location: self.location(first.name.range),
                    }],
                    vec![String::from(
                        "BibTeX consumers disagree about which duplicate value wins",
                    )],
                    Some(FixDraft {
                        title: format!("Remove duplicate `{}` field", field.name.text),
                        applicability: FixApplicability::Unsafe,
                        edits: vec![TextEdit {
                            range: field.range,
                            replacement: String::new(),
                        }],
                    }),
                );
            } else {
                first_fields.insert(normalized, field);
            }
        }

        for field in &entry.fields {
            let expected = expected_field_spelling(&field.name.text, self.policy.field_case);
            if expected != field.name.text {
                self.emit(
                    RULE_FIELD_CASE,
                    format!("field `{}` should be spelled `{expected}`", field.name.text),
                    field.name.range,
                    vec![],
                    vec![],
                    Some(FixDraft {
                        title: format!("Rename field to `{expected}`"),
                        applicability: FixApplicability::Safe,
                        edits: vec![TextEdit {
                            range: field.name.range,
                            replacement: expected,
                        }],
                    }),
                );
            }
        }

        if let Some((range, edit)) = self.field_order_issue(entry) {
            let comment_sensitive = !inline_percent_comment_ranges(self.syntax, entry).is_empty()
                || edit.as_ref().is_some_and(|(_, applicability)| {
                    *applicability == FixApplicability::RequiresConfirmation
                });
            self.emit(
                RULE_FIELD_ORDER,
                String::from("fields do not follow the configured order"),
                range,
                vec![],
                comment_sensitive
                    .then(|| {
                        String::from(
                            "comments between fields may change association when fields move",
                        )
                    })
                    .into_iter()
                    .collect(),
                edit.map(|(edit, applicability)| FixDraft {
                    title: String::from("Reorder fields"),
                    applicability,
                    edits: vec![edit],
                }),
            );
        }

        if !entry.fields.is_empty() && !entry.trailing_comma {
            let offset = entry
                .fields
                .last()
                .map_or(entry.citation_key.range.end, |field| field.range.end);
            self.emit(
                RULE_TRAILING_COMMA,
                String::from("last field should have a trailing comma"),
                TextRange::new(offset, offset),
                vec![],
                vec![],
                Some(FixDraft {
                    title: String::from("Add trailing comma"),
                    applicability: FixApplicability::Safe,
                    edits: vec![TextEdit {
                        range: TextRange::new(offset, offset),
                        replacement: String::from(","),
                    }],
                }),
            );
        }

        if self.policy.prefer_braces {
            for field in &entry.fields {
                for atom in &field.value.atoms {
                    if matches!(atom.kind, ValueAtomKind::Quoted { closed: true })
                        && atom.range.len() >= 2
                    {
                        self.emit(
                            RULE_VALUE_DELIMITER,
                            String::from("braced values are preferred over quoted values"),
                            atom.range,
                            vec![],
                            vec![],
                            Some(FixDraft {
                                title: String::from("Use braces around value"),
                                applicability: FixApplicability::Safe,
                                edits: vec![
                                    TextEdit {
                                        range: TextRange::new(
                                            atom.range.start,
                                            atom.range.start + 1,
                                        ),
                                        replacement: String::from("{"),
                                    },
                                    TextEdit {
                                        range: TextRange::new(atom.range.end - 1, atom.range.end),
                                        replacement: String::from("}"),
                                    },
                                ],
                            }),
                        );
                    }
                }
            }
        }

        for field in &entry.fields {
            if let Some((range, edits)) = self.equals_whitespace_issue(field) {
                self.emit(
                    RULE_EQUALS_WHITESPACE,
                    String::from("use one space on each side of `=`"),
                    range,
                    vec![],
                    vec![],
                    Some(FixDraft {
                        title: String::from("Normalize whitespace around `=`"),
                        applicability: FixApplicability::Safe,
                        edits,
                    }),
                );
            }
            if let Some((range, edits)) = self.value_line_break_issue(field) {
                self.emit(
                    RULE_VALUE_LINE_BREAKS,
                    format!(
                        "field `{}` contains line breaks in its value",
                        field.name.text
                    ),
                    range,
                    vec![],
                    vec![String::from(
                        "stored field values use a single space at line boundaries",
                    )],
                    Some(FixDraft {
                        title: format!("Normalize line breaks in `{}`", field.name.text),
                        applicability: FixApplicability::Safe,
                        edits,
                    }),
                );
            }
        }

        for range in inline_percent_comment_ranges(self.syntax, entry) {
            self.emit(
                RULE_INLINE_PERCENT_COMMENT,
                String::from("percent comments should be placed between entries"),
                range,
                vec![],
                vec![String::from(
                    "inline percent comments inside entries are not portable BibTeX",
                )],
                None,
            );
        }

        if self.policy.setting(RULE_UNESCAPED_TEX_SPECIAL).enabled {
            for field in &entry.fields {
                for issue in unescaped_tex_special_issues(self.syntax, field) {
                    let Some(primary_range) = issue.occurrences.first_range() else {
                        continue;
                    };
                    let mut notes = vec![tex_special_note()];
                    if issue.occurrences.omitted > 0 {
                        notes.push(tex_special_omission_note(
                            issue.occurrences.len(),
                            issue.occurrences.omitted,
                        ));
                    }
                    let labels = tex_special_labels(&issue.occurrences.items);
                    self.emit(
                        RULE_UNESCAPED_TEX_SPECIAL,
                        format!(
                            "field `{}` contains unescaped TeX-special character(s) {labels}",
                            field.name.text
                        ),
                        primary_range,
                        vec![],
                        notes,
                        (issue.occurrences.omitted == 0).then(|| FixDraft {
                            title: format!(
                                "Escape TeX-special character(s) in `{}`",
                                field.name.text
                            ),
                            applicability: issue.applicability,
                            edits: tex_special_escape_edits(&issue.occurrences.items),
                        }),
                    );
                }
            }
        }
    }

    fn validate_referenced_string_tex_specials(&mut self) {
        if !self.policy.setting(RULE_UNESCAPED_TEX_SPECIAL).enabled {
            return;
        }
        let analysis = referenced_string_tex_special_analysis(self.syntax);
        self.emit_referenced_string_tex_special_analysis(analysis);
    }

    #[cfg(test)]
    fn validate_referenced_string_tex_specials_with_limit(&mut self, visit_limit: usize) {
        let analysis = referenced_string_tex_special_analysis_with_limit(self.syntax, visit_limit);
        self.emit_referenced_string_tex_special_analysis(analysis);
    }

    fn emit_referenced_string_tex_special_analysis(
        &mut self,
        analysis: ReferencedStringTexSpecialAnalysis,
    ) {
        let fixes_allowed = analysis.incomplete_range.is_none();
        for issue in analysis.issues {
            let Some(primary_range) = issue.occurrences.first_range() else {
                continue;
            };
            let fields = issue
                .consumer_fields
                .iter()
                .map(|field| format!("`{field}`"))
                .collect::<Vec<_>>()
                .join(", ");
            let mut notes = vec![tex_special_note()];
            if issue.occurrences.omitted > 0 {
                notes.push(tex_special_omission_note(
                    issue.occurrences.len(),
                    issue.occurrences.omitted,
                ));
            }
            let labels = tex_special_labels(&issue.occurrences.items);
            self.emit(
                RULE_UNESCAPED_TEX_SPECIAL,
                format!(
                    "@string `{}` used by field(s) {fields} contains unescaped TeX-special character(s) {labels}",
                    issue.macro_name
                ),
                primary_range,
                vec![],
                notes,
                issue
                    .applicability
                    .filter(|_| fixes_allowed)
                    .and_then(|applicability| {
                        (issue.occurrences.omitted == 0).then(|| FixDraft {
                            title: format!(
                                "Escape TeX-special character(s) in @string `{}`",
                                issue.macro_name
                            ),
                            applicability,
                            edits: tex_special_escape_edits(&issue.occurrences.items),
                        })
                    }),
            );
        }
        if let Some(range) = analysis.incomplete_range {
            self.emit(
                RULE_UNESCAPED_TEX_SPECIAL,
                String::from("TeX-special-character analysis is incomplete"),
                range,
                vec![],
                vec![format!(
                    "analysis stopped after {} @string expansion visits because a traversal bound was reached; automatic fixes for referenced @string values are disabled",
                    analysis.completed_macro_visits
                )],
                None,
            );
        }
    }

    #[allow(clippy::too_many_lines)]
    fn validate_identifiers(&mut self, entry: &EntryNode) {
        let doi_regex = Regex::new(r"(?i)^10\.[0-9]{4,9}/[-._;()/:A-Z0-9]+$").ok();
        let arxiv_regex =
            Regex::new(r"(?i)^(?:[a-z][a-z0-9.+-]*/[0-9]{7}|[0-9]{4}\.[0-9]{4,5})(?:v[0-9]+)?$")
                .ok();
        let mut doi_values = BTreeMap::<String, TextRange>::new();
        let mut arxiv_values = BTreeMap::<String, TextRange>::new();
        let eprint_is_arxiv = ["archiveprefix", "eprinttype"]
            .iter()
            .filter_map(|name| entry.field(name))
            .find_map(|field| plain_value(self.syntax, field))
            .is_none_or(|(repository, _)| repository.to_ascii_lowercase().contains("arxiv"));

        if !eprint_is_arxiv {
            static REPOSITORIES: OnceLock<Option<RepositoryRegistry>> = OnceLock::new();
            let repository = ["archiveprefix", "eprinttype"]
                .iter()
                .filter_map(|name| entry.field(name))
                .find_map(|field| plain_value(self.syntax, field));
            let eprint = entry
                .field("eprint")
                .and_then(|field| plain_value(self.syntax, field));
            if let (Some((repository_name, repository_range)), Some((identifier, range))) =
                (repository, eprint)
            {
                match REPOSITORIES
                    .get_or_init(|| RepositoryRegistry::builtin().ok())
                    .as_ref()
                    .and_then(|registry| registry.resolve(repository_name))
                {
                    Some(entity) if !entity.accepts_identifier(identifier) => self.emit(
                        RULE_REPOSITORY_IDENTIFIER,
                        format!(
                            "`{identifier}` is not a valid {} identifier",
                            entity.full_name
                        ),
                        range,
                        vec![RelatedLocation {
                            message: String::from("repository is declared here"),
                            location: self.location(repository_range),
                        }],
                        vec![],
                        None,
                    ),
                    None => self.emit(
                        RULE_REPOSITORY_IDENTIFIER,
                        format!("repository `{repository_name}` is not registered"),
                        repository_range,
                        vec![],
                        vec![String::from(
                            "add a repository registry entry before treating this identifier as resolved",
                        )],
                        None,
                    ),
                    Some(_) => {}
                }
            }
        }

        for field in &entry.fields {
            let name = field.name.text.to_ascii_lowercase();
            let Some((value, range)) = plain_value(self.syntax, field) else {
                continue;
            };
            if name == "doi" {
                let normalized = normalize_doi(value);
                if doi_regex
                    .as_ref()
                    .is_some_and(|regex| regex.is_match(normalized))
                    && normalized != value
                {
                    self.emit(
                        RULE_DOI,
                        String::from("DOI contains a removable URL or `doi:` prefix"),
                        range,
                        vec![],
                        vec![],
                        Some(FixDraft {
                            title: String::from("Normalize DOI"),
                            applicability: FixApplicability::Safe,
                            edits: vec![TextEdit {
                                range,
                                replacement: normalized.to_owned(),
                            }],
                        }),
                    );
                }
                doi_values.insert(normalized.to_ascii_lowercase(), range);
            }

            if name == "arxiv" || (name == "eprint" && eprint_is_arxiv) {
                let normalized = normalize_arxiv(value);
                if arxiv_regex
                    .as_ref()
                    .is_some_and(|regex| regex.is_match(normalized))
                    && normalized != value
                {
                    self.emit(
                        RULE_ARXIV,
                        String::from("arXiv identifier should omit the `arXiv:` prefix"),
                        range,
                        vec![],
                        vec![],
                        Some(FixDraft {
                            title: String::from("Normalize arXiv identifier"),
                            applicability: FixApplicability::Safe,
                            edits: vec![TextEdit {
                                range,
                                replacement: normalized.to_owned(),
                            }],
                        }),
                    );
                }
                arxiv_values.insert(normalized.to_ascii_lowercase(), range);
            }
        }

        self.emit_conflicting_values("DOI", &doi_values);
        self.emit_conflicting_values("arXiv", &arxiv_values);
    }

    #[allow(clippy::too_many_lines)]
    fn validate_laboratory(&mut self, entry: &EntryNode) {
        if let Some(pattern) = Regex::new(&self.policy.citation_key_pattern)
            .ok()
            .filter(|pattern| !pattern.is_match(&entry.citation_key.text))
        {
            let replacement = normalize_citation_key(&entry.citation_key.text);
            let fix = (replacement != entry.citation_key.text && pattern.is_match(&replacement))
                .then_some(FixDraft {
                    title: format!("Change citation key to `{replacement}`"),
                    applicability: FixApplicability::RequiresConfirmation,
                    edits: vec![TextEdit {
                        range: entry.citation_key.range,
                        replacement,
                    }],
                });
            self.emit(
                RULE_CITATION_KEY,
                format!(
                    "citation key `{}` does not match the configured pattern",
                    entry.citation_key.text
                ),
                entry.citation_key.range,
                vec![],
                vec![String::from(
                    "changing a citation key may require updating citing documents",
                )],
                fix,
            );
        }

        let entry_type = entry.entry_type.text.to_ascii_lowercase();
        if let Some(required) = self.policy.required_fields.get(&entry_type) {
            let missing: Vec<_> = required
                .iter()
                .filter(|name| entry.field(name).is_none())
                .cloned()
                .collect();
            if !missing.is_empty() {
                self.emit(
                    RULE_REQUIRED_FIELDS,
                    format!("entry is missing required fields: {}", missing.join(", ")),
                    entry.entry_type.range,
                    vec![],
                    vec![],
                    None,
                );
            }
        }

        for field in &entry.fields {
            if self
                .policy
                .forbidden_fields
                .contains(&field.name.text.to_ascii_lowercase())
            {
                self.emit(
                    RULE_FORBIDDEN_FIELDS,
                    format!("field `{}` is forbidden by this profile", field.name.text),
                    field.name.range,
                    vec![],
                    vec![],
                    Some(FixDraft {
                        title: format!("Remove `{}` field", field.name.text),
                        applicability: FixApplicability::Unsafe,
                        edits: vec![TextEdit {
                            range: field.range,
                            replacement: String::new(),
                        }],
                    }),
                );
            }
        }

        let url_fields: Vec<_> = entry.fields_named("url").collect();
        if !url_fields.is_empty() && self.policy.url_policy != UrlPolicy::Allow {
            for field in url_fields {
                self.emit(
                    RULE_URL_POLICY,
                    String::from(
                        "the selected profile omits URLs during export; \
                         preserve the source field",
                    ),
                    field.name.range,
                    vec![],
                    vec![],
                    None,
                );
            }
        }

        let representation_matches = match self.policy.arxiv_representation {
            ArxivRepresentation::Any => true,
            ArxivRepresentation::Eprint => entry.field("eprint").is_some(),
            ArxivRepresentation::Howpublished => entry.field("howpublished").is_some(),
            ArxivRepresentation::ArticleJournal => {
                entry_type == "article" && entry.field("journal").is_some()
            }
        };
        if entry_looks_like_preprint(self.syntax, entry) && !representation_matches {
            self.emit(
                RULE_ARXIV_REPRESENTATION,
                String::from("arXiv preprint does not use the profile's required representation"),
                entry.entry_type.range,
                vec![],
                vec![],
                None,
            );
        }
    }

    #[allow(clippy::too_many_lines)]
    fn validate_semantics(
        &mut self,
        entry: &EntryNode,
        record: &bibmgr_semantics::BibliographicRecord,
    ) {
        let original_entry_type = entry.entry_type.text.to_ascii_lowercase();
        let expected_type = match record.work_type.value {
            WorkType::JournalArticle => Some("article"),
            WorkType::ConferencePaper => Some("inproceedings"),
            WorkType::Preprint => match self.policy.arxiv_representation {
                ArxivRepresentation::ArticleJournal => Some("article"),
                _ => Some("misc"),
            },
            WorkType::Book
                if matches!(
                    original_entry_type.as_str(),
                    "proceedings" | "mvproceedings"
                ) =>
            {
                None
            }
            WorkType::Book => Some("book"),
            WorkType::InBook => Some("inbook"),
            WorkType::InCollection => Some("incollection"),
            WorkType::Thesis
                if matches!(
                    original_entry_type.as_str(),
                    "mastersthesis" | "phdthesis" | "thesis"
                ) =>
            {
                None
            }
            WorkType::Thesis => Some("phdthesis"),
            WorkType::TechnicalReport => Some("techreport"),
            _ => None,
        };
        if let Some(expected) = expected_type {
            if !entry.entry_type.text.eq_ignore_ascii_case(expected) {
                self.emit(
                    RULE_TYPE_MISMATCH,
                    format!(
                        "entry type `{}` conflicts with semantic work type; expected `{expected}`",
                        entry.entry_type.text
                    ),
                    entry.entry_type.range,
                    vec![],
                    vec![],
                    Some(FixDraft {
                        title: format!("Change entry type to `{expected}`"),
                        applicability: FixApplicability::RequiresConfirmation,
                        edits: vec![TextEdit {
                            range: entry.entry_type.range,
                            replacement: expected.to_owned(),
                        }],
                    }),
                );
            }
        }

        if let Some((venue, expected, venue_kind)) = record.venue.as_ref().and_then(|venue| {
            let (expected, venue_kind) = match (original_entry_type.as_str(), venue.value.kind?) {
                ("article", VenueKind::Conference) => ("inproceedings", "conference"),
                ("article", VenueKind::Workshop) => ("inproceedings", "workshop"),
                ("inproceedings", VenueKind::Journal) => ("article", "journal"),
                _ => return None,
            };
            Some((venue, expected, venue_kind))
        }) {
            let related_locations = venue
                .origins
                .first()
                .map(|origin| RelatedLocation {
                    message: format!("venue resolves to a {venue_kind}"),
                    location: SourceLocation::new(origin.source_id.clone(), origin.range),
                })
                .into_iter()
                .collect();
            self.emit(
                RULE_TYPE_MISMATCH,
                format!(
                    "entry type `{}` conflicts with the resolved {venue_kind} venue; expected `{expected}`",
                    entry.entry_type.text
                ),
                entry.entry_type.range,
                related_locations,
                vec![],
                Some(FixDraft {
                    title: format!("Change entry type to `{expected}`"),
                    applicability: FixApplicability::RequiresConfirmation,
                    edits: vec![TextEdit {
                        range: entry.entry_type.range,
                        replacement: expected.to_owned(),
                    }],
                }),
            );
        }

        let mut missing = Vec::new();
        if record.title.is_none() {
            missing.push("title");
        }
        if matches!(
            record.work_type.value,
            WorkType::JournalArticle | WorkType::ConferencePaper | WorkType::Preprint
        ) && record.authors.is_empty()
        {
            missing.push("author");
        }
        if record.date.is_none()
            && matches!(
                record.work_type.value,
                WorkType::JournalArticle | WorkType::ConferencePaper
            )
        {
            missing.push("date/year");
        }
        if !missing.is_empty() {
            self.emit(
                RULE_REQUIRED_DATA,
                format!("semantic record lacks {}", missing.join(", ")),
                entry.entry_type.range,
                vec![],
                vec![],
                None,
            );
        }
        if entry.field("author").is_some() && record.authors.is_empty() {
            self.emit(
                RULE_AUTHOR,
                String::from("author field could not be parsed into a person"),
                entry
                    .field("author")
                    .map_or(entry.range, |field| field.value.range),
                vec![],
                vec![],
                None,
            );
        }
        if record.has_unresolved_semantics() {
            let (message, range) = if record.work_type.value == WorkType::Unknown {
                (
                    String::from("entry type has no resolved bibliographic work type"),
                    record
                        .work_type
                        .origins
                        .first()
                        .map_or(entry.entry_type.range, |origin| origin.range),
                )
            } else if let Some(date) = record
                .date
                .as_ref()
                .filter(|date| date.status == bibmgr_semantics::ValueStatus::Unresolved)
            {
                (
                    String::from("publication date or year could not be resolved"),
                    date.origins
                        .first()
                        .map_or(entry.entry_type.range, |origin| origin.range),
                )
            } else if let Some(field) = record.unresolved_values.first() {
                (
                    format!("field `{}` contains an unresolved value", field.name),
                    field
                        .origins
                        .first()
                        .map_or(entry.entry_type.range, |origin| origin.range),
                )
            } else {
                (
                    String::from("bibliographic meaning is ambiguous or conflicting"),
                    record.source_range().unwrap_or(entry.range),
                )
            };
            self.emit(
                RULE_UNRESOLVED_SEMANTICS,
                message,
                range,
                vec![],
                vec![String::from(
                    "registration policies may reject unresolved semantic values",
                )],
                None,
            );
        }
    }

    fn field_order_issue(
        &self,
        entry: &EntryNode,
    ) -> Option<(TextRange, Option<(TextEdit, FixApplicability)>)> {
        if entry.fields.len() < 2 || self.policy.field_order.is_empty() {
            return None;
        }
        let ranks: BTreeMap<_, _> = self
            .policy
            .field_order
            .iter()
            .enumerate()
            .map(|(index, name)| (name.to_ascii_lowercase(), index))
            .collect();
        let rank = |field: &FieldNode| {
            ranks
                .get(&field.name.text.to_ascii_lowercase())
                .copied()
                .unwrap_or(usize::MAX)
        };
        let issue = entry
            .fields
            .windows(2)
            .find(|pair| rank(&pair[0]) > rank(&pair[1]))?;

        let mut order: Vec<_> = (0..entry.fields.len()).collect();
        order.sort_by_key(|index| (rank(&entry.fields[*index]), *index));
        let first = entry.fields.first()?;
        let last = entry.fields.last()?;
        let mut replacement = String::new();
        let separators: Option<Vec<_>> = entry
            .fields
            .windows(2)
            .map(|pair| {
                self.syntax
                    .slice(TextRange::new(pair[0].range.end, pair[1].range.start))
            })
            .collect();
        let separators = separators?;
        let applicability = if inline_percent_comment_ranges(self.syntax, entry).is_empty()
            && separators.iter().all(|separator| {
                separator
                    .bytes()
                    .all(|byte| byte == b',' || byte.is_ascii_whitespace())
            }) {
            FixApplicability::Safe
        } else {
            FixApplicability::RequiresConfirmation
        };
        for (position, field_index) in order.into_iter().enumerate() {
            replacement.push_str(self.syntax.slice(entry.fields[field_index].range)?);
            if let Some(separator) = separators.get(position) {
                replacement.push_str(separator);
            }
        }
        let range = TextRange::new(first.range.start, last.range.end);
        let edit = (self.syntax.slice(range)? != replacement)
            .then_some((TextEdit { range, replacement }, applicability));
        Some((issue[1].name.range, edit))
    }

    fn equals_whitespace_issue(&self, field: &FieldNode) -> Option<(TextRange, Vec<TextEdit>)> {
        let equals = field.equals_range?;
        if field.name.range.end > equals.start || equals.end > field.value.range.start {
            return None;
        }

        let left = TextRange::new(field.name.range.end, equals.start);
        let right = TextRange::new(equals.end, field.value.range.start);
        let left_gap = self.syntax.slice(left)?;
        let right_gap = self.syntax.slice(right)?;
        let fix_left = is_simple_horizontal_gap(left_gap) && left_gap != " ";
        let fix_right = is_simple_horizontal_gap(right_gap) && right_gap != " ";
        if !fix_left && !fix_right {
            return None;
        }

        let edit_range = TextRange::new(
            if fix_left { left.start } else { equals.start },
            if fix_right { right.end } else { equals.end },
        );
        let replacement = match (fix_left, fix_right) {
            (true, true) => " = ",
            (true, false) => " =",
            (false, true) => "= ",
            (false, false) => unreachable!("an issue edits at least one simple gap"),
        };
        Some((
            TextRange::new(field.name.range.end, field.value.range.start),
            vec![TextEdit {
                range: edit_range,
                replacement: replacement.to_owned(),
            }],
        ))
    }

    fn value_line_break_issue(&self, field: &FieldNode) -> Option<(TextRange, Vec<TextEdit>)> {
        let mut edits = Vec::new();
        for atom in &field.value.atoms {
            if !matches!(
                atom.kind,
                ValueAtomKind::Braced { .. } | ValueAtomKind::Quoted { .. }
            ) {
                continue;
            }
            let value = self.syntax.slice(atom.content_range)?;
            if let Some(replacement) = normalize_value_line_breaks(value) {
                edits.push(TextEdit {
                    range: atom.content_range,
                    replacement,
                });
            }
        }
        let first = edits.first()?;
        let last = edits.last()?;
        Some((TextRange::new(first.range.start, last.range.end), edits))
    }

    fn emit_conflicting_values(&mut self, label: &str, values: &BTreeMap<String, TextRange>) {
        if values.len() <= 1 {
            return;
        }
        let mut iter = values.values();
        let Some(primary) = iter.next().copied() else {
            return;
        };
        let related = iter
            .copied()
            .map(|range| RelatedLocation {
                message: format!("conflicting {label} value"),
                location: self.location(range),
            })
            .collect();
        self.emit(
            RULE_IDENTIFIER_CONFLICT,
            format!("entry contains conflicting {label} identifiers"),
            primary,
            related,
            vec![],
            None,
        );
    }

    #[allow(clippy::too_many_arguments)]
    fn emit(
        &mut self,
        code: &'static str,
        message: String,
        primary_range: TextRange,
        related_locations: Vec<RelatedLocation>,
        notes: Vec<String>,
        fix: Option<FixDraft>,
    ) {
        let setting = self.policy.setting(code);
        if !setting.enabled {
            return;
        }
        let counter = self.counters.entry(code).or_default();
        let ordinal = *counter;
        *counter += 1;
        let stable_id = format!("{code}:{ordinal}");
        let mut fix_ids = Vec::new();
        if let Some(fix) = fix.filter(|fix| !fix.edits.is_empty()) {
            let id = FixId::new(stable_id.clone());
            fix_ids.push(id.clone());
            self.fixes.push(Fix {
                id,
                title: fix.title,
                applicability: fix.applicability,
                source_revision: self.revision.clone(),
                edits: fix.edits,
            });
        }
        self.diagnostics.push(Diagnostic {
            id: DiagnosticId::new(stable_id),
            code: RuleCode::new(code),
            severity: setting.severity,
            blocking: setting.blocking,
            message,
            primary_location: Some(self.location(primary_range)),
            related_locations,
            notes,
            fixes: fix_ids,
        });
    }

    fn location(&self, range: TextRange) -> SourceLocation {
        SourceLocation::new(self.syntax.source_id().clone(), range)
    }

    fn finish(mut self) -> ValidationResult {
        self.diagnostics.sort_by(diagnostic_order);
        self.fixes.sort_by(|left, right| left.id.cmp(&right.id));
        ValidationResult {
            diagnostics: self.diagnostics,
            fixes: self.fixes,
        }
    }
}

struct FixDraft {
    title: String,
    applicability: FixApplicability,
    edits: Vec<TextEdit>,
}

fn diagnostic_order(left: &Diagnostic, right: &Diagnostic) -> std::cmp::Ordering {
    let left_location = left.primary_location.as_ref().map(|location| {
        (
            location.source_id.as_str(),
            location.range.start,
            location.range.end,
        )
    });
    let right_location = right.primary_location.as_ref().map(|location| {
        (
            location.source_id.as_str(),
            location.range.start,
            location.range.end,
        )
    });
    (left_location, &left.code, &left.id).cmp(&(right_location, &right.code, &right.id))
}

fn plain_value<'a>(syntax: &'a SyntaxDocument, field: &FieldNode) -> Option<(&'a str, TextRange)> {
    if field.value.atoms.len() != 1 || field.value.is_concatenated() {
        return None;
    }
    let atom = field.value.atoms.first()?;
    let value = syntax.slice(atom.content_range)?.trim();
    Some((value, atom.content_range))
}

fn is_simple_horizontal_gap(value: &str) -> bool {
    value.bytes().all(|byte| matches!(byte, b' ' | b'\t'))
}

fn normalize_value_line_breaks(value: &str) -> Option<String> {
    if !value.contains('\r') && !value.contains('\n') {
        return None;
    }

    let mut output = String::with_capacity(value.len());
    let mut after_line_break = false;
    for character in value.chars() {
        if matches!(character, '\r' | '\n') {
            after_line_break = true;
            while output.ends_with(' ') || output.ends_with('\t') {
                output.pop();
            }
            continue;
        }
        if after_line_break {
            if matches!(character, ' ' | '\t') {
                continue;
            }
            if !output.is_empty() {
                output.push(' ');
            }
            after_line_break = false;
        }
        output.push(character);
    }
    Some(output)
}

fn inline_percent_comment_ranges(syntax: &SyntaxDocument, entry: &EntryNode) -> Vec<TextRange> {
    let Some(source) = syntax.slice(entry.range) else {
        return Vec::new();
    };
    let value_ranges = entry
        .fields
        .iter()
        .flat_map(|field| field.value.atoms.iter().map(|atom| atom.range))
        .collect::<Vec<_>>();
    let bytes = source.as_bytes();
    let mut ranges = Vec::new();
    let mut cursor = 0;

    while cursor < bytes.len() {
        let Some(relative) = bytes[cursor..].iter().position(|byte| *byte == b'%') else {
            break;
        };
        let percent = cursor + relative;
        let Ok(percent_offset) = u32::try_from(percent) else {
            break;
        };
        let absolute = entry.range.start.saturating_add(percent_offset);
        if value_ranges.iter().any(|range| range.contains(absolute))
            || is_escaped_percent(bytes, percent)
        {
            cursor = percent + 1;
            continue;
        }

        let end = bytes[percent..]
            .iter()
            .position(|byte| matches!(*byte, b'\n' | b'\r'))
            .map_or(bytes.len(), |offset| percent + offset);
        let Ok(end_offset) = u32::try_from(end) else {
            break;
        };
        ranges.push(TextRange::new(
            absolute,
            entry.range.start.saturating_add(end_offset),
        ));
        cursor = end.max(percent + 1);
    }

    ranges
}

const MAX_TEX_SPECIAL_OCCURRENCES_PER_ISSUE: usize = 256;
const MAX_TEX_SPECIAL_MACRO_EXPANSION_DEPTH: usize = 256;
const MAX_TEX_SPECIAL_MACRO_VISITS: usize = 65_536;
const MAX_TEX_SPECIAL_NESTED_SCAN_DEPTH: usize = 64;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
enum TexSpecialKind {
    Percent,
    Ampersand,
    Hash,
    Underscore,
    Caret,
    Dollar,
}

impl TexSpecialKind {
    fn from_byte(byte: u8) -> Option<Self> {
        match byte {
            b'%' => Some(Self::Percent),
            b'&' => Some(Self::Ampersand),
            b'#' => Some(Self::Hash),
            b'_' => Some(Self::Underscore),
            b'^' => Some(Self::Caret),
            b'$' => Some(Self::Dollar),
            _ => None,
        }
    }

    fn symbol(self) -> char {
        match self {
            Self::Percent => '%',
            Self::Ampersand => '&',
            Self::Hash => '#',
            Self::Underscore => '_',
            Self::Caret => '^',
            Self::Dollar => '$',
        }
    }

    fn replacement(self) -> &'static str {
        match self {
            Self::Percent => "\\%",
            Self::Ampersand => "\\&",
            Self::Hash => "\\#",
            Self::Underscore => "\\_",
            Self::Caret => "\\textasciicircum{}",
            Self::Dollar => "\\$",
        }
    }

    fn requires_confirmation_in_plain_text(self) -> bool {
        matches!(self, Self::Caret | Self::Dollar)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
struct TexSpecialOccurrence {
    range: TextRange,
    kind: TexSpecialKind,
}

#[derive(Debug, Clone, Default)]
struct CappedTexSpecialOccurrences {
    items: Vec<TexSpecialOccurrence>,
    omitted: usize,
}

impl CappedTexSpecialOccurrences {
    fn push(&mut self, occurrence: TexSpecialOccurrence) {
        if self.items.len() < MAX_TEX_SPECIAL_OCCURRENCES_PER_ISSUE {
            self.items.push(occurrence);
        } else {
            self.omitted = self.omitted.saturating_add(1);
        }
    }

    fn merge(&mut self, other: &Self) {
        if other.is_empty() {
            return;
        }
        self.omitted = self.omitted.saturating_add(other.omitted);
        self.items.extend(other.items.iter().copied());
        self.items.sort_unstable();
        self.items.dedup();
        if self.items.len() > MAX_TEX_SPECIAL_OCCURRENCES_PER_ISSUE {
            self.omitted = self
                .omitted
                .saturating_add(self.items.len() - MAX_TEX_SPECIAL_OCCURRENCES_PER_ISSUE);
            self.items.truncate(MAX_TEX_SPECIAL_OCCURRENCES_PER_ISSUE);
        }
    }

    fn is_empty(&self) -> bool {
        self.items.is_empty() && self.omitted == 0
    }

    fn len(&self) -> usize {
        self.items.len()
    }

    fn first_range(&self) -> Option<TextRange> {
        self.items.first().map(|occurrence| occurrence.range)
    }
}

#[derive(Debug)]
struct UnescapedTexSpecialIssue {
    occurrences: CappedTexSpecialOccurrences,
    applicability: FixApplicability,
}

fn unescaped_tex_special_issues(
    syntax: &SyntaxDocument,
    field: &FieldNode,
) -> Vec<UnescapedTexSpecialIssue> {
    let policy = tex_special_consumer_policy(&field.name.text);
    if policy == TexSpecialConsumerPolicy::Ignore {
        return Vec::new();
    }
    let composite = tex_special_expression_is_composite(&field.value);
    let occurrences = literal_tex_special_occurrences(syntax, &field.value);
    let mut safe = CappedTexSpecialOccurrences::default();
    let mut review = occurrences.review;

    if policy == TexSpecialConsumerPolicy::Review || composite {
        review.merge(&occurrences.plain_safe);
    } else {
        safe.merge(&occurrences.plain_safe);
    }

    let mut issues = Vec::new();
    if !safe.is_empty() {
        issues.push(UnescapedTexSpecialIssue {
            occurrences: safe,
            applicability: FixApplicability::Safe,
        });
    }
    if !review.is_empty() {
        issues.push(UnescapedTexSpecialIssue {
            occurrences: review,
            applicability: FixApplicability::RequiresConfirmation,
        });
    }
    issues
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum TexSpecialConsumerPolicy {
    Ignore,
    PlainText,
    Review,
}

fn tex_special_consumer_policy(field_name: &str) -> TexSpecialConsumerPolicy {
    if is_raw_identifier_field(field_name) {
        return TexSpecialConsumerPolicy::Ignore;
    }
    match field_name.to_ascii_lowercase().as_str() {
        "abstract" | "address" | "author" | "booktitle" | "editor" | "institution" | "journal"
        | "journaltitle" | "keywords" | "location" | "organization" | "publisher" | "school"
        | "series" | "subtitle" | "title" | "translator" => TexSpecialConsumerPolicy::PlainText,
        _ => TexSpecialConsumerPolicy::Review,
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
enum TexOccurrenceClass {
    PlainSafe,
    Review,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum TexContext {
    Plain,
    CommandArgument,
    UrlCommandArgument,
    Math,
}

#[derive(Debug, Clone, Default)]
struct LiteralTexSpecialOccurrences {
    plain_safe: CappedTexSpecialOccurrences,
    review: CappedTexSpecialOccurrences,
}

impl LiteralTexSpecialOccurrences {
    fn record(&mut self, occurrence: TexSpecialOccurrence, context: TexContext) {
        match context {
            TexContext::Plain if !occurrence.kind.requires_confirmation_in_plain_text() => {
                self.plain_safe.push(occurrence);
            }
            TexContext::Plain | TexContext::CommandArgument => self.review.push(occurrence),
            TexContext::Math
                if matches!(
                    occurrence.kind,
                    TexSpecialKind::Percent | TexSpecialKind::Hash | TexSpecialKind::Dollar
                ) =>
            {
                self.review.push(occurrence);
            }
            TexContext::UrlCommandArgument | TexContext::Math => {}
        }
    }

    fn groups(&self) -> [(TexOccurrenceClass, &CappedTexSpecialOccurrences); 2] {
        [
            (TexOccurrenceClass::PlainSafe, &self.plain_safe),
            (TexOccurrenceClass::Review, &self.review),
        ]
    }
}

fn literal_tex_special_occurrences(
    syntax: &SyntaxDocument,
    expression: &ValueExpression,
) -> LiteralTexSpecialOccurrences {
    let mut occurrences = LiteralTexSpecialOccurrences::default();
    for atom in &expression.atoms {
        if !matches!(
            atom.kind,
            ValueAtomKind::Braced { .. } | ValueAtomKind::Quoted { .. }
        ) {
            continue;
        }
        let Some(value) = syntax.slice(atom.content_range) else {
            continue;
        };
        scan_literal_tex_special_atom(value.as_bytes(), atom.content_range.start, &mut occurrences);
    }
    occurrences
}

fn tex_special_expression_is_composite(expression: &ValueExpression) -> bool {
    expression.is_concatenated()
        || expression
            .atoms
            .iter()
            .any(|atom| atom.kind == ValueAtomKind::Macro)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum MathDelimiter {
    Dollar,
    DisplayDollar,
    Parenthesis,
    Bracket,
    EnsureMath,
}

#[derive(Debug)]
struct MathFrame {
    delimiter: MathDelimiter,
    group_depth: usize,
    openers: CappedTexSpecialOccurrences,
    deferred: CappedTexSpecialOccurrences,
}

#[derive(Debug, Default)]
struct UrlFrame {
    deferred: CappedTexSpecialOccurrences,
}

impl MathFrame {
    fn new(delimiter: MathDelimiter, group_depth: usize) -> Self {
        Self {
            delimiter,
            group_depth,
            openers: CappedTexSpecialOccurrences::default(),
            deferred: CappedTexSpecialOccurrences::default(),
        }
    }
}

fn scan_literal_tex_special_atom(
    bytes: &[u8],
    content_start: u32,
    occurrences: &mut LiteralTexSpecialOccurrences,
) {
    scan_literal_tex_special_atom_with_depth(bytes, content_start, occurrences, 0);
}

#[allow(clippy::too_many_lines)]
fn scan_literal_tex_special_atom_with_depth(
    bytes: &[u8],
    content_start: u32,
    occurrences: &mut LiteralTexSpecialOccurrences,
    nested_scan_depth: usize,
) {
    let mut group_commands = Vec::<Option<TexCommandKind>>::new();
    let mut command_argument_depth = 0_usize;
    let mut url_command_argument_depth = 0_usize;
    let mut url_frames = Vec::<UrlFrame>::new();
    let mut math_frames = Vec::<MathFrame>::new();
    let mut pending_command = None::<TexCommandKind>;
    let mut continuation_command = None::<TexCommandKind>;
    let mut cursor = 0;
    while cursor < bytes.len() {
        match bytes[cursor] {
            b'\\' => {
                continuation_command = None;
                if url_command_argument_depth > 0 {
                    cursor = scan_url_literal_control_sequence(bytes, cursor);
                    pending_command = None;
                } else if scan_math_control_delimiter(
                    bytes,
                    &mut cursor,
                    group_commands.len(),
                    &mut math_frames,
                ) {
                    pending_command = None;
                } else {
                    (cursor, pending_command) = scan_tex_command(
                        bytes,
                        cursor,
                        content_start,
                        occurrences,
                        nested_scan_depth,
                    );
                }
            }
            b'*' if pending_command.is_some() => {
                if pending_command != Some(TexCommandKind::Other) {
                    pending_command = None;
                }
                cursor += 1;
            }
            b'[' if pending_command.is_some() => {
                if pending_command == Some(TexCommandKind::Other) {
                    let (next, closed) = scan_optional_tex_argument(
                        bytes,
                        cursor,
                        content_start,
                        occurrences,
                        nested_scan_depth,
                    );
                    cursor = next;
                    if !closed {
                        pending_command = None;
                    }
                } else {
                    pending_command = None;
                    cursor += 1;
                }
            }
            b'{' => {
                let command = pending_command.take().or(continuation_command.take());
                match command {
                    Some(TexCommandKind::Url) => {
                        url_command_argument_depth += 1;
                        url_frames.push(UrlFrame::default());
                    }
                    Some(TexCommandKind::Other) => command_argument_depth += 1,
                    Some(TexCommandKind::Math) => {
                        math_frames.push(MathFrame::new(
                            MathDelimiter::EnsureMath,
                            group_commands.len() + 1,
                        ));
                    }
                    None => {}
                }
                group_commands.push(command);
                cursor += 1;
            }
            b'}' => {
                pending_command = None;
                let closing_group_depth = group_commands.len();
                let command = group_commands.pop().flatten();
                match command {
                    Some(TexCommandKind::Url) => {
                        url_command_argument_depth = url_command_argument_depth.saturating_sub(1);
                        if let Some(completed) = url_frames.pop() {
                            if let Some(parent) = url_frames.last_mut() {
                                parent.deferred.merge(&completed.deferred);
                            }
                        }
                        invalidate_math_frames_at_group_boundary(
                            &mut math_frames,
                            closing_group_depth,
                            occurrences,
                        );
                        continuation_command = None;
                    }
                    Some(TexCommandKind::Other) => {
                        command_argument_depth = command_argument_depth.saturating_sub(1);
                        invalidate_math_frames_at_group_boundary(
                            &mut math_frames,
                            closing_group_depth,
                            occurrences,
                        );
                        continuation_command = Some(TexCommandKind::Other);
                    }
                    Some(TexCommandKind::Math) => {
                        close_ensuremath_group(&mut math_frames, closing_group_depth, occurrences);
                        continuation_command = None;
                    }
                    None => {
                        invalidate_math_frames_at_group_boundary(
                            &mut math_frames,
                            closing_group_depth,
                            occurrences,
                        );
                        continuation_command = None;
                    }
                }
                cursor += 1;
            }
            byte if byte.is_ascii_whitespace() => cursor += 1,
            byte if (pending_command.is_some() || continuation_command.is_some())
                && is_ambiguous_tex_delimiter(byte) =>
            {
                pending_command = None;
                continuation_command = None;
                cursor =
                    scan_ambiguous_delimited_argument(bytes, cursor, content_start, occurrences);
            }
            b'$' if url_command_argument_depth == 0 => {
                scan_math_dollar(
                    bytes,
                    &mut cursor,
                    content_start,
                    group_commands.len(),
                    &mut math_frames,
                    occurrences,
                );
                pending_command = None;
                continuation_command = None;
            }
            byte if TexSpecialKind::from_byte(byte).is_some() => {
                let kind = TexSpecialKind::from_byte(byte).expect("matched TeX-special byte");
                let occurrence = tex_special_occurrence(cursor, content_start, kind);
                if let Some(occurrence) = occurrence {
                    if let Some(frame) = url_frames.last_mut() {
                        frame.deferred.push(occurrence);
                    } else if !math_frames.is_empty()
                        && matches!(
                            kind,
                            TexSpecialKind::Ampersand
                                | TexSpecialKind::Underscore
                                | TexSpecialKind::Caret
                        )
                    {
                        if let Some(frame) = math_frames.last_mut() {
                            frame.deferred.push(occurrence);
                        }
                    } else {
                        let context = tex_context(
                            url_command_argument_depth,
                            command_argument_depth,
                            pending_command,
                            continuation_command,
                            !math_frames.is_empty(),
                        );
                        occurrences.record(occurrence, context);
                    }
                }
                pending_command = None;
                continuation_command = None;
                cursor += 1;
            }
            _ => {
                pending_command = None;
                continuation_command = None;
                cursor += 1;
            }
        }
    }

    invalidate_all_math_frames(&mut math_frames, occurrences);
    for frame in url_frames {
        occurrences.review.merge(&frame.deferred);
    }
}

fn scan_url_literal_control_sequence(bytes: &[u8], cursor: usize) -> usize {
    let Some(&next) = bytes.get(cursor + 1) else {
        return cursor + 1;
    };
    if !next.is_ascii_alphabetic() && next != b'@' {
        return cursor + 2;
    }
    let mut end = cursor + 2;
    while end < bytes.len() && (bytes[end].is_ascii_alphabetic() || bytes[end] == b'@') {
        end += 1;
    }
    end
}

fn tex_context(
    url_argument_depth: usize,
    command_argument_depth: usize,
    pending_command: Option<TexCommandKind>,
    continuation_command: Option<TexCommandKind>,
    in_math: bool,
) -> TexContext {
    if url_argument_depth > 0 {
        TexContext::UrlCommandArgument
    } else if in_math {
        TexContext::Math
    } else if command_argument_depth > 0
        || pending_command.is_some()
        || continuation_command.is_some()
    {
        TexContext::CommandArgument
    } else {
        TexContext::Plain
    }
}

fn scan_math_control_delimiter(
    bytes: &[u8],
    cursor: &mut usize,
    group_depth: usize,
    frames: &mut Vec<MathFrame>,
) -> bool {
    let Some(next) = bytes.get(*cursor + 1).copied() else {
        return false;
    };
    let delimiter = match next {
        b'(' => Some((MathDelimiter::Parenthesis, true)),
        b')' => Some((MathDelimiter::Parenthesis, false)),
        b'[' => Some((MathDelimiter::Bracket, true)),
        b']' => Some((MathDelimiter::Bracket, false)),
        _ => None,
    };
    let Some((delimiter, opens)) = delimiter else {
        return false;
    };
    if opens {
        if frames.is_empty() {
            frames.push(MathFrame::new(delimiter, group_depth));
        }
    } else {
        close_math_frame(frames, delimiter, group_depth);
    }
    *cursor += 2;
    true
}

fn scan_math_dollar(
    bytes: &[u8],
    cursor: &mut usize,
    content_start: u32,
    group_depth: usize,
    frames: &mut Vec<MathFrame>,
    occurrences: &mut LiteralTexSpecialOccurrences,
) {
    if frames.last().is_some_and(|frame| {
        frame.delimiter == MathDelimiter::Dollar && frame.group_depth == group_depth
    }) {
        frames.pop();
        *cursor += 1;
        return;
    }

    let display = bytes.get(*cursor + 1) == Some(&b'$');
    if frames.last().is_some_and(|frame| {
        frame.delimiter == MathDelimiter::DisplayDollar && frame.group_depth == group_depth
    }) {
        if display {
            frames.pop();
            *cursor += 2;
        } else {
            record_tex_special_occurrence(
                *cursor,
                content_start,
                TexSpecialKind::Dollar,
                occurrences,
                TexContext::Math,
            );
            *cursor += 1;
        }
        return;
    }

    if !frames.is_empty() {
        record_tex_special_occurrence(
            *cursor,
            content_start,
            TexSpecialKind::Dollar,
            occurrences,
            TexContext::Math,
        );
        if display {
            record_tex_special_occurrence(
                *cursor + 1,
                content_start,
                TexSpecialKind::Dollar,
                occurrences,
                TexContext::Math,
            );
        }
        *cursor += usize::from(display) + 1;
        return;
    }

    let delimiter = if display {
        MathDelimiter::DisplayDollar
    } else {
        MathDelimiter::Dollar
    };
    let mut frame = MathFrame::new(delimiter, group_depth);
    if let Some(opener) = tex_special_occurrence(*cursor, content_start, TexSpecialKind::Dollar) {
        frame.openers.push(opener);
    }
    if display {
        if let Some(opener) =
            tex_special_occurrence(*cursor + 1, content_start, TexSpecialKind::Dollar)
        {
            frame.openers.push(opener);
        }
    }
    frames.push(frame);
    *cursor += usize::from(display) + 1;
}

fn close_math_frame(frames: &mut Vec<MathFrame>, delimiter: MathDelimiter, group_depth: usize) {
    if frames
        .last()
        .is_some_and(|frame| frame.delimiter == delimiter && frame.group_depth == group_depth)
    {
        frames.pop();
    }
}

fn merge_unclosed_math_frame(frame: &MathFrame, occurrences: &mut LiteralTexSpecialOccurrences) {
    occurrences.review.merge(&frame.openers);
    occurrences.review.merge(&frame.deferred);
}

fn invalidate_math_frames_at_group_boundary(
    frames: &mut Vec<MathFrame>,
    closing_group_depth: usize,
    occurrences: &mut LiteralTexSpecialOccurrences,
) {
    while frames
        .last()
        .is_some_and(|frame| frame.group_depth >= closing_group_depth)
    {
        if let Some(frame) = frames.pop() {
            merge_unclosed_math_frame(&frame, occurrences);
        }
    }
}

fn close_ensuremath_group(
    frames: &mut Vec<MathFrame>,
    closing_group_depth: usize,
    occurrences: &mut LiteralTexSpecialOccurrences,
) {
    while frames.last().is_some_and(|frame| {
        frame.group_depth >= closing_group_depth
            && !(frame.group_depth == closing_group_depth
                && frame.delimiter == MathDelimiter::EnsureMath)
    }) {
        if let Some(frame) = frames.pop() {
            merge_unclosed_math_frame(&frame, occurrences);
        }
    }
    close_math_frame(frames, MathDelimiter::EnsureMath, closing_group_depth);
}

fn invalidate_all_math_frames(
    frames: &mut Vec<MathFrame>,
    occurrences: &mut LiteralTexSpecialOccurrences,
) {
    while let Some(frame) = frames.pop() {
        merge_unclosed_math_frame(&frame, occurrences);
    }
}

fn scan_tex_command(
    bytes: &[u8],
    cursor: usize,
    content_start: u32,
    occurrences: &mut LiteralTexSpecialOccurrences,
    nested_scan_depth: usize,
) -> (usize, Option<TexCommandKind>) {
    if cursor + 1 >= bytes.len() {
        return (cursor + 1, None);
    }
    let next = bytes[cursor + 1];
    if !next.is_ascii_alphabetic() && next != b'@' {
        return (cursor + 2, None);
    }

    let start = cursor + 1;
    if let Some((command, end)) = known_verbatim_tex_command_prefix(bytes, start) {
        return (
            scan_verbatim_tex_command(
                bytes,
                end,
                content_start,
                occurrences,
                command,
                nested_scan_depth,
            ),
            None,
        );
    }
    let mut end = start + 1;
    while end < bytes.len() && (bytes[end].is_ascii_alphabetic() || bytes[end] == b'@') {
        end += 1;
    }
    let command = &bytes[start..end];
    if is_verbatim_tex_command(command) {
        (
            scan_verbatim_tex_command(
                bytes,
                end,
                content_start,
                occurrences,
                command,
                nested_scan_depth,
            ),
            None,
        )
    } else {
        (end, Some(tex_command_kind(command)))
    }
}

fn known_verbatim_tex_command_prefix(bytes: &[u8], start: usize) -> Option<(&[u8], usize)> {
    for command in [
        b"lstinline".as_slice(),
        b"verb".as_slice(),
        b"Verb".as_slice(),
    ] {
        let end = start.checked_add(command.len())?;
        if bytes.get(start..end) != Some(command) {
            continue;
        }
        if bytes.get(end).is_some_and(u8::is_ascii_alphabetic) {
            continue;
        }
        return Some((command, end));
    }
    None
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum TexCommandKind {
    Other,
    Url,
    Math,
}

fn tex_command_kind(command: &[u8]) -> TexCommandKind {
    match command {
        b"url" | b"nolinkurl" | b"path" => TexCommandKind::Url,
        b"ensuremath" => TexCommandKind::Math,
        _ => TexCommandKind::Other,
    }
}

fn is_verbatim_tex_command(command: &[u8]) -> bool {
    matches!(command, b"verb" | b"Verb" | b"lstinline")
}

fn scan_verbatim_tex_command(
    bytes: &[u8],
    mut cursor: usize,
    content_start: u32,
    occurrences: &mut LiteralTexSpecialOccurrences,
    command: &[u8],
    nested_scan_depth: usize,
) -> usize {
    if bytes.get(cursor) == Some(&b'*') {
        cursor += 1;
    }
    if matches!(command, b"Verb" | b"lstinline") {
        while matches!(bytes.get(cursor), Some(b' ' | b'\t')) {
            cursor += 1;
        }
        if bytes.get(cursor) == Some(&b'[') {
            let (next, closed) = scan_optional_tex_argument(
                bytes,
                cursor,
                content_start,
                occurrences,
                nested_scan_depth,
            );
            cursor = next;
            if !closed {
                return cursor;
            }
            while matches!(bytes.get(cursor), Some(b' ' | b'\t')) {
                cursor += 1;
            }
        }
    }

    let Some(delimiter) = verbatim_delimiter(bytes, cursor) else {
        return cursor;
    };
    if delimiter.character.is_ascii_alphabetic() || delimiter.character.is_ascii_whitespace() {
        let end = line_end(bytes, cursor);
        record_command_argument_tex_specials(bytes, cursor, end, content_start, occurrences);
        return end;
    }

    let value_start = cursor + delimiter.len;
    let end = line_end(bytes, value_start);
    if let Some(relative) = bytes[value_start..end]
        .windows(delimiter.len)
        .position(|candidate| candidate == delimiter.bytes)
    {
        value_start + relative + delimiter.len
    } else {
        if let Some(kind) = TexSpecialKind::from_byte(bytes[cursor]) {
            record_tex_special_occurrence(
                cursor,
                content_start,
                kind,
                occurrences,
                TexContext::CommandArgument,
            );
        }
        record_command_argument_tex_specials(bytes, value_start, end, content_start, occurrences);
        end
    }
}

#[derive(Debug, Clone, Copy)]
struct VerbatimDelimiter<'a> {
    character: char,
    bytes: &'a [u8],
    len: usize,
}

fn verbatim_delimiter(bytes: &[u8], cursor: usize) -> Option<VerbatimDelimiter<'_>> {
    let character = std::str::from_utf8(bytes.get(cursor..)?)
        .ok()?
        .chars()
        .next()?;
    let len = character.len_utf8();
    Some(VerbatimDelimiter {
        character,
        bytes: bytes.get(cursor..cursor.checked_add(len)?)?,
        len,
    })
}

fn scan_optional_tex_argument(
    bytes: &[u8],
    mut cursor: usize,
    content_start: u32,
    occurrences: &mut LiteralTexSpecialOccurrences,
    nested_scan_depth: usize,
) -> (usize, bool) {
    let argument_content_start = cursor.saturating_add(1);
    let mut depth = 0_usize;
    while cursor < bytes.len() {
        match bytes[cursor] {
            b'\\' if cursor + 1 < bytes.len() => cursor += 2,
            b'[' => {
                depth += 1;
                cursor += 1;
            }
            b']' => {
                depth = depth.saturating_sub(1);
                let argument_content_end = cursor;
                cursor += 1;
                if depth == 0 {
                    scan_optional_tex_argument_content(
                        bytes,
                        argument_content_start,
                        argument_content_end,
                        content_start,
                        occurrences,
                        nested_scan_depth,
                    );
                    return (cursor, true);
                }
            }
            _ => cursor += 1,
        }
    }
    record_command_argument_tex_specials(
        bytes,
        argument_content_start,
        cursor,
        content_start,
        occurrences,
    );
    (cursor, false)
}

fn scan_optional_tex_argument_content(
    bytes: &[u8],
    start: usize,
    end: usize,
    content_start: u32,
    occurrences: &mut LiteralTexSpecialOccurrences,
    nested_scan_depth: usize,
) {
    if nested_scan_depth >= MAX_TEX_SPECIAL_NESTED_SCAN_DEPTH {
        record_command_argument_tex_specials(bytes, start, end, content_start, occurrences);
        return;
    }
    let Some(fragment) = bytes.get(start..end) else {
        return;
    };
    let fragment_start = content_start.saturating_add(u32::try_from(start).unwrap_or(u32::MAX));
    let mut fragment_occurrences = LiteralTexSpecialOccurrences::default();
    scan_literal_tex_special_atom_with_depth(
        fragment,
        fragment_start,
        &mut fragment_occurrences,
        nested_scan_depth + 1,
    );
    occurrences.review.merge(&fragment_occurrences.plain_safe);
    occurrences.review.merge(&fragment_occurrences.review);
}

fn is_ambiguous_tex_delimiter(byte: u8) -> bool {
    matches!(byte, b'|' | b'!' | b'+' | b'/' | b':' | b';')
}

fn scan_ambiguous_delimited_argument(
    bytes: &[u8],
    mut cursor: usize,
    content_start: u32,
    occurrences: &mut LiteralTexSpecialOccurrences,
) -> usize {
    let delimiter = bytes[cursor];
    cursor += 1;
    while cursor < bytes.len() && !matches!(bytes[cursor], b'\n' | b'\r') {
        match bytes[cursor] {
            byte if byte == delimiter => return cursor + 1,
            b'\\' if cursor + 1 < bytes.len() => cursor += 2,
            byte if TexSpecialKind::from_byte(byte).is_some() => {
                record_tex_special_occurrence(
                    cursor,
                    content_start,
                    TexSpecialKind::from_byte(byte).expect("matched TeX-special byte"),
                    occurrences,
                    TexContext::CommandArgument,
                );
                cursor += 1;
            }
            _ => cursor += 1,
        }
    }
    cursor
}

fn record_command_argument_tex_specials(
    bytes: &[u8],
    mut cursor: usize,
    end: usize,
    content_start: u32,
    occurrences: &mut LiteralTexSpecialOccurrences,
) {
    while cursor < end {
        match bytes[cursor] {
            b'\\' if cursor + 1 < end => cursor += 2,
            byte if TexSpecialKind::from_byte(byte).is_some() => {
                record_tex_special_occurrence(
                    cursor,
                    content_start,
                    TexSpecialKind::from_byte(byte).expect("matched TeX-special byte"),
                    occurrences,
                    TexContext::CommandArgument,
                );
                cursor += 1;
            }
            _ => cursor += 1,
        }
    }
}

fn tex_special_occurrence(
    cursor: usize,
    content_start: u32,
    kind: TexSpecialKind,
) -> Option<TexSpecialOccurrence> {
    let offset = u32::try_from(cursor).ok()?;
    let start = content_start.saturating_add(offset);
    Some(TexSpecialOccurrence {
        range: TextRange::new(start, start.saturating_add(1)),
        kind,
    })
}

fn record_tex_special_occurrence(
    cursor: usize,
    content_start: u32,
    kind: TexSpecialKind,
    occurrences: &mut LiteralTexSpecialOccurrences,
    context: TexContext,
) {
    if let Some(occurrence) = tex_special_occurrence(cursor, content_start, kind) {
        occurrences.record(occurrence, context);
    }
}

fn line_end(bytes: &[u8], start: usize) -> usize {
    bytes[start..]
        .iter()
        .position(|byte| matches!(*byte, b'\n' | b'\r'))
        .map_or(bytes.len(), |relative| start + relative)
}

#[derive(Debug)]
struct ReferencedStringTexSpecialIssue {
    occurrences: CappedTexSpecialOccurrences,
    macro_name: String,
    consumer_fields: BTreeSet<String>,
    applicability: Option<FixApplicability>,
}

#[derive(Debug)]
struct ReferencedStringTexSpecialUsage {
    macro_name: String,
    occurrences: CappedTexSpecialOccurrences,
    consumer_fields: BTreeSet<String>,
    has_diagnostic_consumer: bool,
    has_ignored_consumer: bool,
    requires_confirmation: bool,
}

impl ReferencedStringTexSpecialUsage {
    fn new(macro_name: &str, occurrences: &CappedTexSpecialOccurrences) -> Self {
        Self {
            macro_name: macro_name.to_owned(),
            occurrences: occurrences.clone(),
            consumer_fields: BTreeSet::new(),
            has_diagnostic_consumer: false,
            has_ignored_consumer: false,
            requires_confirmation: false,
        }
    }

    fn record(
        &mut self,
        field_name: &str,
        policy: TexSpecialConsumerPolicy,
        class: TexOccurrenceClass,
        expansion_risk: TexSpecialExpansionRisk,
    ) {
        self.consumer_fields.insert(field_name.to_ascii_lowercase());
        match policy {
            TexSpecialConsumerPolicy::Ignore => self.has_ignored_consumer = true,
            TexSpecialConsumerPolicy::PlainText => {
                self.has_diagnostic_consumer = true;
                self.requires_confirmation |= expansion_risk
                    == TexSpecialExpansionRisk::Concatenated
                    || class == TexOccurrenceClass::Review;
            }
            TexSpecialConsumerPolicy::Review => {
                self.has_diagnostic_consumer = true;
                self.requires_confirmation = true;
            }
        }
    }
}

#[derive(Debug)]
struct TexSpecialStringDefinition {
    range: TextRange,
    macro_name: String,
    occurrences: LiteralTexSpecialOccurrences,
    references: Vec<TexSpecialMacroReference>,
}

#[derive(Debug, Default)]
struct TexSpecialStringDefinitionGroup {
    definitions: Vec<TexSpecialStringDefinition>,
    concatenated: bool,
}

#[derive(Debug)]
struct TexSpecialConsumerContext {
    policy: TexSpecialConsumerPolicy,
    roots: BTreeMap<(String, TexSpecialExpansionRisk), TextRange>,
}

#[derive(Debug)]
struct TexSpecialMacroReference {
    name: String,
    range: TextRange,
}

#[derive(Debug)]
struct TexSpecialMacroQueueItem {
    macro_name: String,
    depth: usize,
    expansion_risk: TexSpecialExpansionRisk,
    origin_range: TextRange,
}

#[derive(Debug)]
struct ReferencedStringTexSpecialAnalysis {
    issues: Vec<ReferencedStringTexSpecialIssue>,
    completed_macro_visits: usize,
    incomplete_range: Option<TextRange>,
}

type TexSpecialStringDefinitions = BTreeMap<String, TexSpecialStringDefinitionGroup>;
type ReferencedStringTexSpecialUsages =
    BTreeMap<(TextRange, TexOccurrenceClass), ReferencedStringTexSpecialUsage>;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
enum TexSpecialFixDisposition {
    NoFix,
    Safe,
    RequiresConfirmation,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
enum TexSpecialExpansionRisk {
    Plain,
    Concatenated,
}

impl TexSpecialExpansionRisk {
    fn from_concatenated(concatenated: bool) -> Self {
        if concatenated {
            Self::Concatenated
        } else {
            Self::Plain
        }
    }

    fn merge(self, other: Self) -> Self {
        self.max(other)
    }
}

impl TexSpecialFixDisposition {
    fn applicability(self) -> Option<FixApplicability> {
        match self {
            Self::NoFix => None,
            Self::Safe => Some(FixApplicability::Safe),
            Self::RequiresConfirmation => Some(FixApplicability::RequiresConfirmation),
        }
    }
}

fn referenced_string_tex_special_analysis(
    syntax: &SyntaxDocument,
) -> ReferencedStringTexSpecialAnalysis {
    referenced_string_tex_special_analysis_with_limit(syntax, MAX_TEX_SPECIAL_MACRO_VISITS)
}

fn referenced_string_tex_special_analysis_with_limit(
    syntax: &SyntaxDocument,
    visit_limit: usize,
) -> ReferencedStringTexSpecialAnalysis {
    let definitions = tex_special_string_definitions(syntax);
    let consumer_contexts = tex_special_consumer_contexts(syntax);
    let (usages, completed_macro_visits, incomplete_range) =
        collect_referenced_string_tex_special_usages(&definitions, consumer_contexts, visit_limit);
    ReferencedStringTexSpecialAnalysis {
        issues: referenced_string_tex_special_issues_from_usages(usages),
        completed_macro_visits,
        incomplete_range,
    }
}

fn tex_special_string_definitions(syntax: &SyntaxDocument) -> TexSpecialStringDefinitions {
    let mut definitions = TexSpecialStringDefinitions::new();
    for definition in syntax.strings() {
        let concatenated = definition.value.is_concatenated();
        let mut references = BTreeMap::<String, TextRange>::new();
        for atom in &definition.value.atoms {
            if atom.kind != ValueAtomKind::Macro {
                continue;
            }
            let Some(name) = syntax.slice(atom.content_range) else {
                continue;
            };
            let Some(canonical) = canonical_tex_special_macro_name(name) else {
                continue;
            };
            references.entry(canonical).or_insert(atom.content_range);
        }
        let group = definitions
            .entry(definition.name.text.to_ascii_lowercase())
            .or_default();
        group.concatenated |= concatenated;
        group.definitions.push(TexSpecialStringDefinition {
            range: definition.range,
            macro_name: definition.name.text.clone(),
            occurrences: literal_tex_special_occurrences(syntax, &definition.value),
            references: references
                .into_iter()
                .map(|(name, range)| TexSpecialMacroReference { name, range })
                .collect(),
        });
    }
    definitions
}

fn tex_special_consumer_contexts(
    syntax: &SyntaxDocument,
) -> BTreeMap<String, TexSpecialConsumerContext> {
    let mut consumer_contexts = BTreeMap::<String, TexSpecialConsumerContext>::new();
    for entry in syntax.entries() {
        for field in &entry.fields {
            let policy = tex_special_consumer_policy(&field.name.text);
            let expansion_risk =
                TexSpecialExpansionRisk::from_concatenated(field.value.is_concatenated());
            let field_name = field.name.text.to_ascii_lowercase();
            let context =
                consumer_contexts
                    .entry(field_name)
                    .or_insert_with(|| TexSpecialConsumerContext {
                        policy,
                        roots: BTreeMap::new(),
                    });
            for atom in &field.value.atoms {
                if atom.kind != ValueAtomKind::Macro {
                    continue;
                }
                let Some(name) = syntax.slice(atom.content_range) else {
                    continue;
                };
                if let Some(canonical) = canonical_tex_special_macro_name(name) {
                    context
                        .roots
                        .entry((canonical, expansion_risk))
                        .or_insert(atom.content_range);
                }
            }
        }
    }
    consumer_contexts
}

fn collect_referenced_string_tex_special_usages(
    definitions: &TexSpecialStringDefinitions,
    consumer_contexts: BTreeMap<String, TexSpecialConsumerContext>,
    visit_limit: usize,
) -> (ReferencedStringTexSpecialUsages, usize, Option<TextRange>) {
    let mut usages = ReferencedStringTexSpecialUsages::new();
    let mut completed_macro_visits = 0_usize;
    let mut completed_work_units = 0_usize;
    let mut incomplete_range = None;
    'consumers: for (field_name, consumer) in consumer_contexts {
        let mut queue = VecDeque::<TexSpecialMacroQueueItem>::new();
        let mut scheduled = BTreeSet::<(String, TexSpecialExpansionRisk)>::new();
        let mut completed = BTreeSet::<(String, TexSpecialExpansionRisk)>::new();
        for ((root, expansion_risk), origin_range) in consumer.roots {
            enqueue_tex_special_macro(
                definitions,
                &mut queue,
                &mut scheduled,
                root,
                0,
                expansion_risk,
                origin_range,
            );
        }
        while let Some(item) = queue.pop_front() {
            let state = (item.macro_name.clone(), item.expansion_risk);
            if completed.contains(&state) {
                continue;
            }
            if item.depth >= MAX_TEX_SPECIAL_MACRO_EXPANSION_DEPTH {
                incomplete_range = Some(item.origin_range);
                break 'consumers;
            }
            if completed_work_units >= visit_limit {
                incomplete_range = Some(item.origin_range);
                break 'consumers;
            }
            completed.insert(state);
            completed_macro_visits = completed_macro_visits.saturating_add(1);
            completed_work_units = completed_work_units.saturating_add(1);
            let Some(group) = definitions.get(&item.macro_name) else {
                continue;
            };
            for (candidate_index, definition) in group.definitions.iter().enumerate() {
                // The macro-state work unit covers its first definition; duplicate
                // definitions consume additional units so fan-out cannot bypass the cap.
                if candidate_index > 0 {
                    if completed_work_units >= visit_limit {
                        incomplete_range = Some(item.origin_range);
                        break 'consumers;
                    }
                    completed_work_units = completed_work_units.saturating_add(1);
                }
                for (class, occurrences) in definition.occurrences.groups() {
                    if occurrences.is_empty() {
                        continue;
                    }
                    usages
                        .entry((definition.range, class))
                        .or_insert_with(|| {
                            ReferencedStringTexSpecialUsage::new(
                                &definition.macro_name,
                                occurrences,
                            )
                        })
                        .record(&field_name, consumer.policy, class, item.expansion_risk);
                }
                for reference in &definition.references {
                    enqueue_tex_special_macro(
                        definitions,
                        &mut queue,
                        &mut scheduled,
                        reference.name.clone(),
                        item.depth + 1,
                        item.expansion_risk,
                        reference.range,
                    );
                }
            }
        }
    }
    (usages, completed_macro_visits, incomplete_range)
}

fn enqueue_tex_special_macro(
    definitions: &TexSpecialStringDefinitions,
    queue: &mut VecDeque<TexSpecialMacroQueueItem>,
    scheduled: &mut BTreeSet<(String, TexSpecialExpansionRisk)>,
    macro_name: String,
    depth: usize,
    incoming_risk: TexSpecialExpansionRisk,
    origin_range: TextRange,
) {
    let definition_risk = TexSpecialExpansionRisk::from_concatenated(
        definitions
            .get(&macro_name)
            .is_some_and(|group| group.concatenated),
    );
    let expansion_risk = incoming_risk.merge(definition_risk);
    if scheduled.insert((macro_name.clone(), expansion_risk)) {
        queue.push_back(TexSpecialMacroQueueItem {
            macro_name,
            depth,
            expansion_risk,
            origin_range,
        });
    }
}

fn referenced_string_tex_special_issues_from_usages(
    usages: ReferencedStringTexSpecialUsages,
) -> Vec<ReferencedStringTexSpecialIssue> {
    let mut issues =
        BTreeMap::<(TextRange, TexSpecialFixDisposition), ReferencedStringTexSpecialIssue>::new();
    for ((definition_range, _), usage) in usages {
        if !usage.has_diagnostic_consumer {
            continue;
        }
        let disposition = if usage.has_ignored_consumer {
            TexSpecialFixDisposition::NoFix
        } else if usage.requires_confirmation {
            TexSpecialFixDisposition::RequiresConfirmation
        } else {
            TexSpecialFixDisposition::Safe
        };
        let issue = issues
            .entry((definition_range, disposition))
            .or_insert_with(|| ReferencedStringTexSpecialIssue {
                occurrences: CappedTexSpecialOccurrences::default(),
                macro_name: usage.macro_name.clone(),
                consumer_fields: BTreeSet::new(),
                applicability: disposition.applicability(),
            });
        issue.occurrences.merge(&usage.occurrences);
        issue.consumer_fields.extend(usage.consumer_fields);
    }
    issues.into_values().collect()
}

fn canonical_tex_special_macro_name(name: &str) -> Option<String> {
    let canonical = name.trim().to_ascii_lowercase();
    (!canonical.is_empty() && !is_builtin_month_macro(&canonical)).then_some(canonical)
}

fn tex_special_escape_edits(occurrences: &[TexSpecialOccurrence]) -> Vec<TextEdit> {
    occurrences
        .iter()
        .map(|occurrence| TextEdit {
            range: occurrence.range,
            replacement: String::from(occurrence.kind.replacement()),
        })
        .collect()
}

fn tex_special_labels(occurrences: &[TexSpecialOccurrence]) -> String {
    occurrences
        .iter()
        .map(|occurrence| occurrence.kind)
        .collect::<BTreeSet<_>>()
        .into_iter()
        .map(|kind| format!("`{}`", kind.symbol()))
        .collect::<Vec<_>>()
        .join(", ")
}

fn tex_special_note() -> String {
    String::from(
        "BibTeX retains these characters in database values, but TeX interprets `%`, `&`, `#`, `_`, `^`, and `$` as syntax when a bibliography style writes them to `.bbl`",
    )
}

fn tex_special_omission_note(shown: usize, omitted: usize) -> String {
    format!(
        "this diagnostic represents {} unescaped TeX-special characters; {omitted} additional ranges were omitted to keep validation output bounded, so no automatic fix is offered",
        shown.saturating_add(omitted)
    )
}

fn is_builtin_month_macro(name: &str) -> bool {
    matches!(
        name,
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

fn is_escaped_percent(bytes: &[u8], percent: usize) -> bool {
    let mut backslashes = 0;
    let mut cursor = percent;
    while cursor > 0 && bytes[cursor - 1] == b'\\' {
        backslashes += 1;
        cursor -= 1;
    }
    backslashes % 2 == 1
}

fn normalize_doi(value: &str) -> &str {
    let value = value.trim();
    let value = strip_ascii_prefix(value, "https://doi.org/");
    let value = strip_ascii_prefix(value, "http://doi.org/");
    let value = strip_ascii_prefix(value, "doi:");
    value.trim()
}

fn normalize_arxiv(value: &str) -> &str {
    let value = value.trim();
    strip_ascii_prefix(value, "arxiv:").trim()
}

fn strip_ascii_prefix<'a>(value: &'a str, prefix: &str) -> &'a str {
    value
        .get(..prefix.len())
        .filter(|candidate| candidate.eq_ignore_ascii_case(prefix))
        .map_or(value, |_| &value[prefix.len()..])
}

fn normalize_citation_key(value: &str) -> String {
    let mut normalized = String::with_capacity(value.len());
    let mut pending_separator = false;
    for character in value.chars() {
        if character.is_ascii_alphanumeric() {
            if pending_separator && !normalized.is_empty() {
                normalized.push('-');
            }
            normalized.push(character.to_ascii_lowercase());
            pending_separator = false;
        } else {
            pending_separator = !normalized.is_empty();
        }
    }

    if normalized.is_empty() {
        return String::from("ref");
    }
    if normalized
        .chars()
        .next()
        .is_some_and(|character| !character.is_ascii_alphabetic())
    {
        normalized.insert_str(0, "ref-");
    }
    normalized
}

fn entry_looks_like_preprint(syntax: &SyntaxDocument, entry: &EntryNode) -> bool {
    entry.field("eprint").is_some()
        || entry.field("archiveprefix").is_some()
        || ["journal", "howpublished"]
            .iter()
            .filter_map(|name| entry.field(name))
            .filter_map(|field| plain_value(syntax, field))
            .any(|(value, _)| value.to_ascii_lowercase().contains("arxiv"))
}

fn expected_field_spelling(value: &str, policy: FieldCase) -> String {
    match policy {
        FieldCase::Preserve => value.to_owned(),
        FieldCase::Lowercase => value.to_ascii_lowercase(),
        FieldCase::Canonical => match value.to_ascii_lowercase().as_str() {
            "archiveprefix" => String::from("archivePrefix"),
            "primaryclass" => String::from("primaryClass"),
            other => other.to_owned(),
        },
    }
}

fn is_field_name(value: &str) -> bool {
    !value.is_empty()
        && value
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || matches!(character, '_' | '-'))
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
        "year",
        "date",
        "doi",
        "eprint",
        "archiveprefix",
        "primaryclass",
        "url",
        "note",
    ]
    .into_iter()
    .map(str::to_owned)
    .collect()
}

fn default_required_fields() -> BTreeMap<String, Vec<String>> {
    [
        ("article", vec!["author", "title", "journal", "year"]),
        (
            "inproceedings",
            vec!["author", "title", "booktitle", "year"],
        ),
        ("book", vec!["title", "publisher", "year"]),
        ("phdthesis", vec!["author", "title", "school", "year"]),
        ("mastersthesis", vec!["author", "title", "school", "year"]),
        ("techreport", vec!["author", "title", "institution", "year"]),
    ]
    .into_iter()
    .map(|(entry_type, fields)| {
        (
            entry_type.to_owned(),
            fields.into_iter().map(str::to_owned).collect(),
        )
    })
    .collect()
}

fn migrate_deprecated_rule_settings(
    rules: &mut BTreeMap<RuleCode, RuleSetting>,
) -> Result<(), ConfigurationError> {
    for (deprecated, canonical) in RETIRED_RULE_CODE_ALIASES {
        let deprecated_code = RuleCode::new(*deprecated);
        let canonical_code = RuleCode::new(*canonical);
        let Some(setting) = rules.remove(&deprecated_code) else {
            continue;
        };
        if let Some(canonical_setting) = rules.get(&canonical_code) {
            if canonical_setting != &setting {
                return Err(ConfigurationError::ConflictingRuleAlias {
                    deprecated: deprecated_code,
                    canonical: canonical_code,
                });
            }
        } else {
            rules.insert(canonical_code, setting);
        }
    }
    Ok(())
}

fn migrate_deprecated_rule_set(rules: &mut BTreeSet<RuleCode>) {
    for (deprecated, canonical) in RETIRED_RULE_CODE_ALIASES {
        if rules.remove(&RuleCode::new(*deprecated)) {
            rules.insert(RuleCode::new(*canonical));
        }
    }
}

fn default_rule_settings() -> BTreeMap<RuleCode, RuleSetting> {
    REGISTERED_RULE_CODES
        .iter()
        .map(|code| (RuleCode::new(*code), default_rule_setting(code)))
        .collect()
}

fn default_rule_setting(code: &str) -> RuleSetting {
    let severity = match code {
        "BIB-SEMANTIC-001"
        | "BIB-SEMANTIC-002"
        | "BIB-SEMANTIC-006"
        | RULE_INLINE_PERCENT_COMMENT
        | RULE_UNESCAPED_TEX_SPECIAL => Severity::Warning,
        RULE_FIELD_CASE | RULE_TRAILING_COMMA => Severity::Hint,
        RULE_FIELD_ORDER
        | RULE_VALUE_DELIMITER
        | RULE_EQUALS_WHITESPACE
        | RULE_VALUE_LINE_BREAKS => Severity::Information,
        RULE_REQUIRED_DATA | RULE_IDENTIFIER_CONFLICT => Severity::Error,
        _ if is_parser_rule(code) => Severity::Error,
        _ => Severity::Warning,
    };
    RuleSetting {
        enabled: true,
        severity,
        blocking: is_parser_rule(code),
    }
}

fn is_parser_rule(code: &str) -> bool {
    code.strip_prefix("BIB-SYNTAX-")
        .and_then(|suffix| suffix.parse::<u16>().ok())
        .is_some_and(|number| (101..=112).contains(&number))
}

#[cfg(test)]
mod tests {
    use super::*;
    use bibmgr_edit::{apply_fix_plan, plan_fixes, FixSelection};
    use bibmgr_semantics::{analyze, RAW_IDENTIFIER_FIELD_NAMES};
    use bibmgr_syntax::{parse, ParseOptions};
    use std::fmt::Write as _;

    fn run(source: &str, policy: &ValidationPolicy) -> ValidationResult {
        let syntax = parse(source, ParseOptions::tolerant());
        let semantics = analyze(&syntax);
        validate(&syntax, &semantics, policy)
    }

    fn percent_macro_chain(nodes: usize) -> String {
        assert!(nodes > 0);
        let last = nodes - 1;
        let mut source = String::new();
        for index in 1..=last {
            writeln!(source, "@string{{m{index}=m{}}}", index - 1).unwrap();
        }
        writeln!(source, "@misc{{k, title=m{last},}}").unwrap();
        source.push_str("@string{m0={50%\n}}\n");
        source
    }

    #[test]
    fn policy_round_trips_through_toml() {
        let policy = ValidationPolicy::laboratory();
        let encoded = toml::to_string(&policy).unwrap();
        let decoded = ValidationPolicy::from_toml(&encoded).unwrap();
        assert_eq!(decoded, policy);
    }

    #[test]
    fn bundled_policy_files_are_accepted() {
        for source in [
            include_str!("../../../config/policies/archive.toml"),
            include_str!("../../../config/policies/modern.toml"),
            include_str!("../../../config/policies/laboratory.toml"),
            include_str!("../../../config/policies/acl.toml"),
            include_str!("../../../config/policies/classical-bst.toml"),
        ] {
            ValidationPolicy::from_toml(source).unwrap();
        }
    }

    #[test]
    fn convenience_profiles_match_the_embedded_policy_files() {
        for (profile, convenience) in [
            ("archive", ValidationPolicy::archive()),
            ("modern", ValidationPolicy::modern()),
            ("laboratory", ValidationPolicy::laboratory()),
            ("acl", ValidationPolicy::acl()),
            ("classical-bst", ValidationPolicy::classical_bst()),
        ] {
            assert_eq!(convenience, ValidationPolicy::builtin(profile).unwrap());
        }
        assert_eq!(ValidationPolicy::default(), ValidationPolicy::modern());
    }

    #[test]
    fn toml_loaders_migrate_retired_semantic_rule_codes() {
        let encoded = toml::to_string(&ValidationPolicy::default()).unwrap();
        let migrated =
            ValidationPolicy::from_toml(&encoded.replacen(RULE_DOI, "BIB-SEMANTIC-103", 1))
                .unwrap();
        assert!(migrated.rules.contains_key(&RuleCode::new(RULE_DOI)));
        assert!(!migrated
            .rules
            .contains_key(&RuleCode::new("BIB-SEMANTIC-103")));

        let registration = r#"
schema_version = "1"
validation_profile = "modern"
minimum_severity = "error"
allow_unresolved_semantics = false
apply_safe_fixes = false

[blocking_rules]
all = false
include = ["BIB-SEMANTIC-104"]
exclude = ["BIB-SEMANTIC-105"]
"#;
        let migrated = RegistrationPolicy::from_toml(registration).unwrap();
        assert!(migrated
            .blocking_rules
            .include
            .contains(&RuleCode::new(RULE_ARXIV)));
        assert!(migrated
            .blocking_rules
            .exclude
            .contains(&RuleCode::new(RULE_DATE)));
    }

    #[test]
    fn conflicting_retired_and_canonical_rule_settings_are_rejected() {
        let policy = r#"
schema_version = "1"
profile = "conflicting-aliases"

[rules."BIB-SEMANTIC-001"]
enabled = true
severity = "error"
blocking = true

[rules."BIB-SEMANTIC-103"]
enabled = false
severity = "warning"
blocking = false
"#;
        assert!(matches!(
            ValidationPolicy::from_toml(policy),
            Err(ConfigurationError::ConflictingRuleAlias { .. })
        ));
    }

    #[test]
    fn rejects_unknown_rule_and_duplicate_field_order() {
        let mut policy = ValidationPolicy::default();
        policy
            .rules
            .insert(RuleCode::new("NOT-A-RULE"), RuleSetting::default());
        assert!(matches!(
            policy.validate_configuration(),
            Err(ConfigurationError::UnknownRule(_))
        ));
        let policy = ValidationPolicy {
            field_order: vec![String::from("DOI"), String::from("doi")],
            ..ValidationPolicy::default()
        };
        assert!(matches!(
            policy.validate_configuration(),
            Err(ConfigurationError::DuplicateFieldOrder(_))
        ));

        let registration = r#"
schema_version = "1"
validation_profile = "modern"
minimum_severity = "warning"
allow_unresolved_semantics = false
apply_safe_fixes = false

[blocking_rules]
all = false
include = ["NOT-A-RULE"]
exclude = []
"#;
        assert!(matches!(
            RegistrationPolicy::from_toml(registration),
            Err(ConfigurationError::UnknownRule(_))
        ));
    }

    #[test]
    fn duplicate_field_has_stable_code_related_range_and_unsafe_fix() {
        let result = run(
            "@misc{k, title={first}, TITLE={second},}\n",
            &ValidationPolicy::default(),
        );
        let diagnostic = result
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code.as_str() == RULE_DUPLICATE_FIELD)
            .unwrap();
        assert_eq!(diagnostic.related_locations.len(), 1);
        let fix = result
            .fixes
            .iter()
            .find(|fix| fix.id == diagnostic.fixes[0])
            .unwrap();
        assert_eq!(fix.applicability, FixApplicability::Unsafe);
    }

    #[test]
    fn safe_style_fixes_are_revision_bound_and_deterministic() {
        let source = "@misc{k, TITLE=\"A\"}\n";
        let first = run(source, &ValidationPolicy::default());
        let second = run(source, &ValidationPolicy::default());
        assert_eq!(first, second);
        assert!(first
            .fixes
            .iter()
            .all(|fix| fix.source_revision == SourceRevision::of(source)));
        assert!(first
            .fixes
            .iter()
            .any(|fix| fix.applicability == FixApplicability::Safe));
    }

    #[test]
    fn safe_fix_revalidation_is_idempotent() {
        let source = "@misc{k, TITLE={A},}\n";
        let policy = ValidationPolicy::default();
        let first = run(source, &policy);
        let plan = plan_fixes(
            &SourceRevision::of(source),
            &first.fixes,
            &FixSelection::AllSafe,
        )
        .unwrap();
        let applied = apply_fix_plan(source, &plan).unwrap();
        let second = run(&applied.source, &policy);
        assert!(!second
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code.as_str() == RULE_FIELD_CASE));
        let second_plan = plan_fixes(
            &applied.source_revision,
            &second.fixes,
            &FixSelection::AllSafe,
        )
        .unwrap();
        let reapplied = apply_fix_plan(&applied.source, &second_plan).unwrap();
        assert_eq!(reapplied.source, applied.source);
    }

    #[test]
    fn field_order_fix_clears_its_diagnostic_after_revalidation() {
        let source = "@article{k, year={2024}, title={T}, author={Doe, J}, journal={J},}\n";
        let policy = ValidationPolicy::default();
        let first = run(source, &policy);
        let diagnostic = first
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code.as_str() == RULE_FIELD_ORDER)
            .unwrap();
        let plan = plan_fixes(
            &SourceRevision::of(source),
            &first.fixes,
            &FixSelection::Ids(diagnostic.fixes.clone()),
        )
        .unwrap();
        let applied = apply_fix_plan(source, &plan).unwrap();
        assert!(!run(&applied.source, &policy)
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code.as_str() == RULE_FIELD_ORDER));
    }

    #[test]
    fn inline_field_comments_never_offer_safe_reordering() {
        let source = "@article{k,\n  year={2024}, % describes the year\n  title={T},\n  author={Doe, J},\n  journal={J},\n}\n";
        let result = run(source, &ValidationPolicy::default());
        let field_order_fix_ids = result
            .diagnostics
            .iter()
            .filter(|diagnostic| diagnostic.code.as_str() == RULE_FIELD_ORDER)
            .flat_map(|diagnostic| diagnostic.fixes.iter())
            .collect::<BTreeSet<_>>();
        assert!(result
            .fixes
            .iter()
            .filter(|fix| field_order_fix_ids.contains(&fix.id))
            .all(|fix| fix.applicability != FixApplicability::Safe));
    }

    #[test]
    fn equals_whitespace_has_precise_range_safe_fix_and_is_idempotent() {
        let source = "@misc{k, title=  {T},}\n";
        let policy = ValidationPolicy::default();
        let first = run(source, &policy);
        let diagnostic = first
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code.as_str() == RULE_EQUALS_WHITESPACE)
            .unwrap();
        let start = u32::try_from(source.find("title").unwrap() + "title".len()).unwrap();
        let end = u32::try_from(source.find("{T}").unwrap()).unwrap();
        assert_eq!(
            diagnostic.primary_location.as_ref().unwrap().range,
            TextRange::new(start, end)
        );
        assert_eq!(diagnostic.severity, Severity::Information);
        assert!(!diagnostic.blocking);

        let fix = first
            .fixes
            .iter()
            .find(|fix| diagnostic.fixes.contains(&fix.id))
            .unwrap();
        assert_eq!(fix.applicability, FixApplicability::Safe);
        assert_eq!(fix.edits.len(), 1);
        let plan = plan_fixes(
            &SourceRevision::of(source),
            &first.fixes,
            &FixSelection::Ids(vec![fix.id.clone()]),
        )
        .unwrap();
        let applied = apply_fix_plan(source, &plan).unwrap();
        assert_eq!(applied.source, "@misc{k, title = {T},}\n");

        let second = run(&applied.source, &policy);
        assert!(!second
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code.as_str() == RULE_EQUALS_WHITESPACE));
        assert!(!second
            .fixes
            .iter()
            .any(|fix| fix.id.as_str().starts_with(RULE_EQUALS_WHITESPACE)));
    }

    #[test]
    fn equals_whitespace_fix_preserves_complex_gaps_and_percent_values() {
        let source = "@misc{k,\n  title\t=\n    {100\\% ready},\n}\n";
        let policy = ValidationPolicy::default();
        let result = run(source, &policy);
        let diagnostic = result
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code.as_str() == RULE_EQUALS_WHITESPACE)
            .unwrap();
        let fix = result
            .fixes
            .iter()
            .find(|fix| diagnostic.fixes.contains(&fix.id))
            .unwrap();
        assert_eq!(fix.edits.len(), 1);
        assert_eq!(
            result
                .diagnostics
                .iter()
                .filter(|diagnostic| { diagnostic.code.as_str() == RULE_INLINE_PERCENT_COMMENT })
                .count(),
            0
        );

        let plan = plan_fixes(
            &SourceRevision::of(source),
            &result.fixes,
            &FixSelection::Ids(vec![fix.id.clone()]),
        )
        .unwrap();
        let applied = apply_fix_plan(source, &plan).unwrap();
        assert_eq!(
            applied.source,
            "@misc{k,\n  title =\n    {100\\% ready},\n}\n"
        );
        assert!(!run(&applied.source, &policy)
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code.as_str() == RULE_EQUALS_WHITESPACE));
    }

    #[test]
    fn value_line_break_fix_preserves_bibtex_grouping_and_is_idempotent() {
        let source = concat!(
            "@misc{k,\n",
            "  title = {{D}iffu{S}eq-v2},\n",
            "  note = {first line  \r\n",
            "      second line\n",
            "      third line},\n",
            "}\n",
        );
        let policy = ValidationPolicy::default();
        let first = run(source, &policy);
        let diagnostic = first
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code.as_str() == RULE_VALUE_LINE_BREAKS)
            .unwrap();
        assert_eq!(diagnostic.severity, Severity::Information);
        assert!(!diagnostic.blocking);

        let fix = first
            .fixes
            .iter()
            .find(|fix| diagnostic.fixes.contains(&fix.id))
            .unwrap();
        assert_eq!(fix.applicability, FixApplicability::Safe);
        let plan = plan_fixes(
            &SourceRevision::of(source),
            &first.fixes,
            &FixSelection::Ids(vec![fix.id.clone()]),
        )
        .unwrap();
        let applied = apply_fix_plan(source, &plan).unwrap();
        assert!(applied.source.contains("title = {{D}iffu{S}eq-v2}"));
        assert!(applied
            .source
            .contains("note = {first line second line third line}"));

        let second = run(&applied.source, &policy);
        assert!(!second
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code.as_str() == RULE_VALUE_LINE_BREAKS));
        assert!(!second
            .fixes
            .iter()
            .any(|fix| fix.id.as_str().starts_with(RULE_VALUE_LINE_BREAKS)));
    }

    #[test]
    fn inline_percent_comment_has_precise_range_and_no_fix() {
        let source = "@misc{k,\n  title = {T}, % keep this outside the entry\n}\n";
        let result = run(source, &ValidationPolicy::default());
        let diagnostic = result
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code.as_str() == RULE_INLINE_PERCENT_COMMENT)
            .unwrap();
        let start = source.find('%').unwrap();
        let end = source[start..]
            .find('\n')
            .map_or(source.len(), |offset| start + offset);
        assert_eq!(
            diagnostic.primary_location.as_ref().unwrap().range,
            TextRange::checked(start, end).unwrap()
        );
        assert!(diagnostic.fixes.is_empty());
        assert!(!result
            .fixes
            .iter()
            .any(|fix| fix.id.as_str().starts_with(RULE_INLINE_PERCENT_COMMENT)));

        let outside = "% between entries\n@misc{k, title = {100% ready},}\n";
        assert!(!run(outside, &ValidationPolicy::default())
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code.as_str() == RULE_INLINE_PERCENT_COMMENT));
    }

    #[test]
    fn unescaped_percent_in_text_value_has_a_precise_safe_fix() {
        let source = "@misc{k,\n  title = {日本語 100% ready and 50\\% done},\n}\n";
        let result = run(source, &ValidationPolicy::laboratory());
        let diagnostics = result
            .diagnostics
            .iter()
            .filter(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_PERCENT)
            .collect::<Vec<_>>();
        assert_eq!(diagnostics.len(), 1);
        let diagnostic = diagnostics[0];
        let percent = source.find("100%").unwrap() + 3;
        assert_eq!(
            diagnostic.primary_location.as_ref().unwrap().range,
            TextRange::checked(percent, percent + 1).unwrap()
        );
        assert_eq!(diagnostic.severity, Severity::Error);
        assert!(diagnostic.blocking);

        let fix = result
            .fixes
            .iter()
            .find(|fix| diagnostic.fixes.contains(&fix.id))
            .unwrap();
        assert_eq!(fix.applicability, FixApplicability::Safe);
        let plan = plan_fixes(
            &SourceRevision::of(source),
            &result.fixes,
            &FixSelection::Ids(vec![fix.id.clone()]),
        )
        .unwrap();
        let applied = apply_fix_plan(source, &plan).unwrap();
        assert_eq!(
            applied.source,
            "@misc{k,\n  title = {日本語 100\\% ready and 50\\% done},\n}\n"
        );
        assert!(!run(&applied.source, &ValidationPolicy::laboratory())
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_PERCENT));
    }

    #[test]
    fn tex_special_rule_splits_safe_and_review_fixes_for_mixed_plain_text() {
        let source = "@misc{k, title={100% A&B #1 value_1 caret^ and cost$5},}\n";
        let result = run(source, &ValidationPolicy::laboratory());
        let diagnostics = result
            .diagnostics
            .iter()
            .filter(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_TEX_SPECIAL)
            .collect::<Vec<_>>();
        assert_eq!(diagnostics.len(), 2);
        assert!(diagnostics.iter().all(|diagnostic| diagnostic.blocking));
        assert!(diagnostics
            .iter()
            .all(|diagnostic| diagnostic.severity == Severity::Error));

        let fixes = diagnostics
            .iter()
            .map(|diagnostic| {
                result
                    .fixes
                    .iter()
                    .find(|fix| diagnostic.fixes.contains(&fix.id))
                    .unwrap()
            })
            .collect::<Vec<_>>();
        let safe = fixes
            .iter()
            .find(|fix| fix.applicability == FixApplicability::Safe)
            .unwrap();
        assert_eq!(
            safe.edits
                .iter()
                .map(|edit| edit.replacement.as_str())
                .collect::<Vec<_>>(),
            ["\\%", "\\&", "\\#", "\\_"]
        );
        let review = fixes
            .iter()
            .find(|fix| fix.applicability == FixApplicability::RequiresConfirmation)
            .unwrap();
        assert_eq!(
            review
                .edits
                .iter()
                .map(|edit| edit.replacement.as_str())
                .collect::<Vec<_>>(),
            ["\\textasciicircum{}", "\\$"]
        );
    }

    #[test]
    fn tex_special_scanner_observes_escaped_backslash_parity() {
        let source = r"@misc{k, title={escaped \% \& \# \_ \^ \$ raw \\% \\& \\# \\_ \\^ \\$},}
";
        let result = run(source, &ValidationPolicy::laboratory());
        let edits = result
            .fixes
            .iter()
            .filter(|fix| fix.id.as_str().starts_with(RULE_UNESCAPED_TEX_SPECIAL))
            .flat_map(|fix| &fix.edits)
            .collect::<Vec<_>>();
        assert_eq!(edits.len(), 6);
        assert_eq!(
            edits
                .iter()
                .map(|edit| edit.replacement.as_str())
                .collect::<BTreeSet<_>>(),
            BTreeSet::from(["\\%", "\\&", "\\#", "\\_", "\\textasciicircum{}", "\\$",])
        );
    }

    #[test]
    fn tex_special_rule_preserves_math_but_reviews_percent_and_hash_in_math() {
        let source = "@misc{k, title={text #1 and $x_1 & y^2 # 20%$ plus $$a_1 & b^2$$ plus \\(c_1 & d^2\\) plus \\[e_1 & f^2\\] plus \\ensuremath{g_1 & h^2}},}\n";
        let result = run(source, &ValidationPolicy::laboratory());
        let diagnostics = result
            .diagnostics
            .iter()
            .filter(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_TEX_SPECIAL)
            .collect::<Vec<_>>();
        assert_eq!(diagnostics.len(), 2);
        let fixes = diagnostics
            .iter()
            .map(|diagnostic| {
                result
                    .fixes
                    .iter()
                    .find(|fix| diagnostic.fixes.contains(&fix.id))
                    .unwrap()
            })
            .collect::<Vec<_>>();
        let safe = fixes
            .iter()
            .find(|fix| fix.applicability == FixApplicability::Safe)
            .unwrap();
        assert_eq!(safe.edits.len(), 1);
        assert_eq!(safe.edits[0].replacement, "\\#");
        let review = fixes
            .iter()
            .find(|fix| fix.applicability == FixApplicability::RequiresConfirmation)
            .unwrap();
        assert_eq!(
            review
                .edits
                .iter()
                .map(|edit| edit.replacement.as_str())
                .collect::<Vec<_>>(),
            ["\\#", "\\%"]
        );
    }

    #[test]
    fn tex_math_dollar_scanner_handles_adjacent_and_malformed_boundaries() {
        for value in ["$x$$y$", "$$x$$$y$", "$x\\$y$"] {
            let source = format!("@misc{{k, title={{{value}}},}}\n");
            assert!(run(&source, &ValidationPolicy::laboratory())
                .diagnostics
                .iter()
                .all(|diagnostic| diagnostic.code.as_str() != RULE_UNESCAPED_TEX_SPECIAL));
        }

        for (value, expected_edits) in [
            ("$x$$$", 2),
            ("$$x$", 3),
            ("$$x$y$$", 1),
            ("$$a_1 $b_2$", 6),
        ] {
            let source = format!("@misc{{k, title={{{value}}},}}\n");
            let result = run(&source, &ValidationPolicy::laboratory());
            let fixes = result
                .fixes
                .iter()
                .filter(|fix| fix.id.as_str().starts_with(RULE_UNESCAPED_TEX_SPECIAL))
                .collect::<Vec<_>>();
            assert_eq!(fixes.len(), 1, "{value}");
            assert_eq!(
                fixes[0].applicability,
                FixApplicability::RequiresConfirmation,
                "{value}"
            );
            assert_eq!(fixes[0].edits.len(), expected_edits, "{value}");
        }

        for value in ["\\(\\(x\\) y_1\\)", "\\[\\[x\\] y_1\\]"] {
            let source = format!("@misc{{k, title={{{value}}},}}\n");
            let result = run(&source, &ValidationPolicy::laboratory());
            let fixes = result
                .fixes
                .iter()
                .filter(|fix| fix.id.as_str().starts_with(RULE_UNESCAPED_TEX_SPECIAL))
                .collect::<Vec<_>>();
            assert_eq!(fixes.len(), 1, "{value}");
            assert_eq!(fixes[0].applicability, FixApplicability::Safe, "{value}");
            assert_eq!(fixes[0].edits.len(), 1, "{value}");
            assert_eq!(fixes[0].edits[0].replacement, "\\_", "{value}");
        }
    }

    #[test]
    fn math_delimiters_cannot_pair_across_brace_group_boundaries() {
        for (value, expected) in [
            ("{$x_1} prose $", vec!["$", "_", "$"]),
            ("\\foo{$x_1} prose $", vec!["$", "_", "$"]),
            ("{\\(x_1} prose \\)", vec!["_"]),
            ("{\\[x_1} prose \\]", vec!["_"]),
        ] {
            let source = format!("@misc{{k, title=\"{value}\",}}\n");
            let result = run(&source, &ValidationPolicy::laboratory());
            let diagnostic = result
                .diagnostics
                .iter()
                .find(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_TEX_SPECIAL)
                .unwrap();
            let fix = result
                .fixes
                .iter()
                .find(|fix| diagnostic.fixes.contains(&fix.id))
                .unwrap();
            assert_eq!(fix.applicability, FixApplicability::RequiresConfirmation);
            assert_eq!(
                fix.edits
                    .iter()
                    .map(|edit| &source[edit.range.start as usize..edit.range.end as usize])
                    .collect::<Vec<_>>(),
                expected,
                "{value}"
            );
        }
    }

    #[test]
    fn outer_math_survives_balanced_groups_but_reviews_wrong_depth_dollars() {
        for value in [
            "$ {x_1} y $",
            "\\({x_1} y\\)",
            "\\[{x_1} y\\]",
            "\\ensuremath{{z_2}}",
            "\\( {x \\) } y_1 \\)",
        ] {
            let source = format!("@misc{{k, title={{{value}}},}}\n");
            assert!(run(&source, &ValidationPolicy::laboratory())
                .diagnostics
                .iter()
                .all(|diagnostic| diagnostic.code.as_str() != RULE_UNESCAPED_TEX_SPECIAL));
        }

        let source = "@misc{k, title={$ {x $ } y $},}\n";
        let result = run(source, &ValidationPolicy::laboratory());
        let diagnostic = result
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_TEX_SPECIAL)
            .unwrap();
        let fix = result
            .fixes
            .iter()
            .find(|fix| diagnostic.fixes.contains(&fix.id))
            .unwrap();
        assert_eq!(fix.applicability, FixApplicability::RequiresConfirmation);
        assert_eq!(fix.edits.len(), 1);
        assert_eq!(
            &source[fix.edits[0].range.start as usize..fix.edits[0].range.end as usize],
            "$"
        );
    }

    #[test]
    fn ensuremath_closes_after_reviewing_nested_unmatched_math() {
        let source = "@misc{k, title={\\ensuremath{{x_1 $} y_2}},}\n";
        let result = run(source, &ValidationPolicy::laboratory());
        let diagnostic = result
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_TEX_SPECIAL)
            .unwrap();
        let fix = result
            .fixes
            .iter()
            .find(|fix| diagnostic.fixes.contains(&fix.id))
            .unwrap();
        assert_eq!(fix.applicability, FixApplicability::RequiresConfirmation);
        assert_eq!(fix.edits.len(), 1);
        assert_eq!(
            &source[fix.edits[0].range.start as usize..fix.edits[0].range.end as usize],
            "$"
        );
    }

    #[test]
    fn url_and_math_commands_require_an_immediate_unmodified_argument_form() {
        let source = "@misc{k, title={\\url {raw_%&#^$} \\url*{star_1} \\url[x]{option_1} \\ensuremath{math_1 & y^2} \\ensuremath*{star_math_1} \\ensuremath[x]{option_math_1}},}\n";
        let result = run(source, &ValidationPolicy::laboratory());
        let edits = result
            .fixes
            .iter()
            .filter(|fix| fix.id.as_str().starts_with(RULE_UNESCAPED_TEX_SPECIAL))
            .flat_map(|fix| &fix.edits)
            .collect::<Vec<_>>();
        let edited_source_characters = edits
            .iter()
            .map(|edit| &source[edit.range.start as usize..edit.range.end as usize])
            .collect::<Vec<_>>();
        assert_eq!(edited_source_characters, ["_", "_", "_", "_", "_", "_"]);
        assert!(edits.iter().all(|edit| edit.replacement == "\\_"));
    }

    #[test]
    fn only_complete_url_arguments_exclude_tex_special_validation() {
        let complete = "@misc{k, title=\"\\url{a_b%20&c#d^e$f}\",}\n";
        assert!(run(complete, &ValidationPolicy::laboratory())
            .diagnostics
            .iter()
            .all(|diagnostic| diagnostic.code.as_str() != RULE_UNESCAPED_TEX_SPECIAL));

        let incomplete = "@misc{k, title=\"\\url{a_b%20\",}\n";
        let result = run(incomplete, &ValidationPolicy::laboratory());
        let diagnostics = result
            .diagnostics
            .iter()
            .filter(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_TEX_SPECIAL)
            .collect::<Vec<_>>();
        assert_eq!(diagnostics.len(), 1);
        let fix = result
            .fixes
            .iter()
            .find(|fix| diagnostics[0].fixes.contains(&fix.id))
            .unwrap();
        assert_eq!(fix.applicability, FixApplicability::RequiresConfirmation);
        assert_eq!(
            fix.edits
                .iter()
                .map(|edit| &incomplete[edit.range.start as usize..edit.range.end as usize])
                .collect::<Vec<_>>(),
            ["_", "%"]
        );
    }

    #[test]
    fn nested_url_specials_remain_deferred_until_the_outer_argument_closes() {
        let complete = "@misc{k, title=\"\\url{pre \\url{inner_} post%20}\",}\n";
        assert!(run(complete, &ValidationPolicy::laboratory())
            .diagnostics
            .iter()
            .all(|diagnostic| diagnostic.code.as_str() != RULE_UNESCAPED_TEX_SPECIAL));

        let incomplete = "@misc{k, title=\"\\url{pre \\url{inner_} post%20\",}\n";
        let result = run(incomplete, &ValidationPolicy::laboratory());
        let diagnostic = result
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_TEX_SPECIAL)
            .unwrap();
        let fix = result
            .fixes
            .iter()
            .find(|fix| diagnostic.fixes.contains(&fix.id))
            .unwrap();
        assert_eq!(fix.applicability, FixApplicability::RequiresConfirmation);
        assert_eq!(
            fix.edits
                .iter()
                .map(|edit| &incomplete[edit.range.start as usize..edit.range.end as usize])
                .collect::<Vec<_>>(),
            ["_", "%"]
        );
    }

    #[test]
    fn outer_url_arguments_are_opaque_to_nested_command_syntax() {
        let complete =
            "@misc{k, title=\"\\url{\\foo[x_y] \\unknown|a_b| \\verb|inner_| post%20}\",}\n";
        assert!(run(complete, &ValidationPolicy::laboratory())
            .diagnostics
            .iter()
            .all(|diagnostic| diagnostic.code.as_str() != RULE_UNESCAPED_TEX_SPECIAL));

        let incomplete =
            "@misc{k, title=\"\\url{\\foo[x_y] \\unknown|a_b| \\verb|inner_| post%20\",}\n";
        let result = run(incomplete, &ValidationPolicy::laboratory());
        let diagnostic = result
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_TEX_SPECIAL)
            .unwrap();
        let fix = result
            .fixes
            .iter()
            .find(|fix| diagnostic.fixes.contains(&fix.id))
            .unwrap();
        assert_eq!(fix.applicability, FixApplicability::RequiresConfirmation);
        assert_eq!(
            fix.edits
                .iter()
                .map(|edit| &incomplete[edit.range.start as usize..edit.range.end as usize])
                .collect::<Vec<_>>(),
            ["_", "_", "_", "%"]
        );
    }

    #[test]
    fn closing_math_delimiters_clear_pending_command_context() {
        let source = "@misc{k, title={$\\url$ {outside_1} $\\verb|x|$|outside_2|},}\n";
        let result = run(source, &ValidationPolicy::laboratory());
        let fixes = result
            .fixes
            .iter()
            .filter(|fix| fix.id.as_str().starts_with(RULE_UNESCAPED_TEX_SPECIAL))
            .collect::<Vec<_>>();
        assert_eq!(fixes.len(), 1);
        assert_eq!(fixes[0].applicability, FixApplicability::Safe);
        assert_eq!(fixes[0].edits.len(), 2);
        for edit in &fixes[0].edits {
            assert_eq!(
                &source[edit.range.start as usize..edit.range.end as usize],
                "_"
            );
        }
    }

    #[test]
    fn unescaped_percent_rule_is_field_aware() {
        let source = "@misc{k, url={https://example.test/a%20b}, doi={10.1000/a%2Fb}, file={paper%20draft.pdf}, note={50% complete},}\n";
        let result = run(source, &ValidationPolicy::default());
        let diagnostics = result
            .diagnostics
            .iter()
            .filter(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_PERCENT)
            .collect::<Vec<_>>();
        assert_eq!(diagnostics.len(), 1);
        let range = diagnostics[0].primary_location.as_ref().unwrap().range;
        assert_eq!(
            &source[range.start as usize..range.end as usize],
            "%",
            "only the note value should be diagnosed"
        );
        let fix = result
            .fixes
            .iter()
            .find(|fix| diagnostics[0].fixes.contains(&fix.id))
            .unwrap();
        assert_eq!(fix.applicability, FixApplicability::RequiresConfirmation);
    }

    #[test]
    fn every_export_raw_identifier_field_excludes_tex_special_validation() {
        let mut direct_fields = String::new();
        let mut macro_fields = String::new();
        for field in RAW_IDENTIFIER_FIELD_NAMES {
            writeln!(direct_fields, "  {field} = {{raw%&#_^$}},").unwrap();
            writeln!(macro_fields, "  {field} = rawidentifier,").unwrap();
        }
        let source = format!(
            "@string{{rawidentifier={{raw%&#_^$}}}}\n@misc{{direct,\n{direct_fields}}}\n@misc{{macro,\n{macro_fields}}}\n"
        );
        assert!(run(&source, &ValidationPolicy::laboratory())
            .diagnostics
            .iter()
            .all(|diagnostic| diagnostic.code.as_str() != RULE_UNESCAPED_TEX_SPECIAL));
    }

    #[test]
    fn shared_tex_special_macro_uses_all_consumer_policies_and_withholds_fixes() {
        let source = "@string{shared={100% A&B #1 value_1 caret^ cost$5}}\n@misc{k, title=shared, url=shared,}\n";
        let result = run(source, &ValidationPolicy::laboratory());
        let diagnostics = result
            .diagnostics
            .iter()
            .filter(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_TEX_SPECIAL)
            .collect::<Vec<_>>();
        assert_eq!(diagnostics.len(), 1);
        assert!(diagnostics[0].message.contains("`title`"));
        assert!(diagnostics[0].message.contains("`url`"));
        assert!(diagnostics[0].fixes.is_empty());
    }

    #[test]
    fn unescaped_percent_rule_follows_direct_and_nested_string_macros() {
        for source in [
            "@string{percenttitle={100% Effective}}\n@misc{k, title=percenttitle,}\n",
            "@string{percenttitle={100% Effective}}\n@string{nested=percenttitle}\n@misc{k, title=nested,}\n",
        ] {
            let result = run(source, &ValidationPolicy::laboratory());
            let diagnostics = result
                .diagnostics
                .iter()
                .filter(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_PERCENT)
                .collect::<Vec<_>>();
            assert_eq!(diagnostics.len(), 1, "{source}");
            let percent = source.find("100%").unwrap() + 3;
            assert_eq!(
                diagnostics[0].primary_location.as_ref().unwrap().range,
                TextRange::checked(percent, percent + 1).unwrap()
            );
            let fix = result
                .fixes
                .iter()
                .find(|fix| diagnostics[0].fixes.contains(&fix.id))
                .unwrap();
            assert_eq!(fix.applicability, FixApplicability::Safe);
            let plan = plan_fixes(
                &SourceRevision::of(source),
                &result.fixes,
                &FixSelection::Ids(vec![fix.id.clone()]),
            )
            .unwrap();
            let applied = apply_fix_plan(source, &plan).unwrap();
            assert!(!run(&applied.source, &ValidationPolicy::laboratory())
                .diagnostics
                .iter()
                .any(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_PERCENT));
        }
    }

    #[test]
    fn referenced_string_percent_uses_every_consumer_field_context() {
        let source = "@string{urlonly={https://example.test/a%20b}}\n@string{shared={https://example.test/b%20c}}\n@string{urlcommand={See \\url{https://example.test/c%20d}}}\n@string{jan={100% shadowed definition}}\n@misc{k, title=shared, url=urlonly, note=urlcommand, month=jan,}\n@misc{k2, title={T}, url=shared,}\n";
        let result = run(source, &ValidationPolicy::laboratory());
        let diagnostics = result
            .diagnostics
            .iter()
            .filter(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_PERCENT)
            .collect::<Vec<_>>();
        assert_eq!(diagnostics.len(), 1);
        let percent = source.find("b%20c").unwrap() + 1;
        assert_eq!(
            diagnostics[0].primary_location.as_ref().unwrap().range,
            TextRange::checked(percent, percent + 1).unwrap()
        );
        assert!(diagnostics[0].message.contains("`title`"));
        assert!(diagnostics[0].message.contains("`url`"));
        assert!(diagnostics[0].fixes.is_empty());
    }

    #[test]
    fn percent_fix_applicability_uses_tex_command_context() {
        let source = "@misc{k, title={Plain 100% \\url{https://example.test/a%20b} \\nolinkurl{https://example.test/b%20c} \\path{paper%20draft.pdf} \\textbf{50% complete}},}\n";
        let result = run(source, &ValidationPolicy::laboratory());
        let diagnostics = result
            .diagnostics
            .iter()
            .filter(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_PERCENT)
            .collect::<Vec<_>>();
        assert_eq!(diagnostics.len(), 2);

        let cases = [
            ("100%", 3, FixApplicability::Safe),
            ("50%", 2, FixApplicability::RequiresConfirmation),
        ];
        for (text, relative, expected) in cases {
            let percent = source.find(text).unwrap() + relative;
            let range = TextRange::checked(percent, percent + 1).unwrap();
            let diagnostic = diagnostics
                .iter()
                .find(|diagnostic| diagnostic.primary_location.as_ref().unwrap().range == range)
                .unwrap();
            let fix = result
                .fixes
                .iter()
                .find(|fix| diagnostic.fixes.contains(&fix.id))
                .unwrap();
            assert_eq!(fix.applicability, expected);
        }
    }

    #[test]
    fn percent_scanner_skips_known_verbatim_commands_and_reviews_ambiguous_delimiters() {
        let source = "@misc{k, title={Code \\verb|100% ready| \\verb*+50%+ \\verb1digit 8%1 \\Verb!25%! \\lstinline[language=C]!10%! outside 5% \\unknown|2%|},}\n";
        let result = run(source, &ValidationPolicy::laboratory());
        let diagnostics = result
            .diagnostics
            .iter()
            .filter(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_PERCENT)
            .collect::<Vec<_>>();
        assert_eq!(diagnostics.len(), 2);

        for (prefix, applicability) in [
            ("outside 5", FixApplicability::Safe),
            ("\\unknown|2", FixApplicability::RequiresConfirmation),
        ] {
            let percent = source.find(prefix).unwrap() + prefix.len();
            let range = TextRange::checked(percent, percent + 1).unwrap();
            let diagnostic = diagnostics
                .iter()
                .find(|diagnostic| diagnostic.primary_location.as_ref().unwrap().range == range)
                .unwrap();
            let fix = result
                .fixes
                .iter()
                .find(|fix| diagnostic.fixes.contains(&fix.id))
                .unwrap();
            assert_eq!(fix.applicability, applicability);
        }
    }

    #[test]
    fn ambiguous_delimited_command_arguments_are_forced_text_context() {
        for (value, expected) in [
            ("\\unknown|$x_1 & y^2$|", vec!["$", "_", "&", "^", "$"]),
            ("$\\unknown|x_1 & y^2|$", vec!["_", "&", "^"]),
        ] {
            let source = format!("@misc{{k, title={{{value}}},}}\n");
            let result = run(&source, &ValidationPolicy::laboratory());
            let diagnostic = result
                .diagnostics
                .iter()
                .find(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_TEX_SPECIAL)
                .unwrap();
            let fix = result
                .fixes
                .iter()
                .find(|fix| diagnostic.fixes.contains(&fix.id))
                .unwrap();
            assert_eq!(fix.applicability, FixApplicability::RequiresConfirmation);
            assert_eq!(
                fix.edits
                    .iter()
                    .map(|edit| &source[edit.range.start as usize..edit.range.end as usize])
                    .collect::<Vec<_>>(),
                expected,
                "{value}"
            );
        }
    }

    #[test]
    fn tex_special_scanner_skips_every_target_inside_complete_verbatim_commands() {
        let source = "@misc{k, title={\\verb|%&#_^$| \\verb*+%&#_^$+ \\Verb[formatcom=small]!%&#_^$! \\lstinline*[language=TeX]/%&#_^$/},}\n";
        assert!(run(source, &ValidationPolicy::laboratory())
            .diagnostics
            .iter()
            .all(|diagnostic| diagnostic.code.as_str() != RULE_UNESCAPED_TEX_SPECIAL));
    }

    #[test]
    fn incomplete_verbatim_arguments_require_confirmation() {
        let source = "@misc{k, title=\"\\verb|%&#_^$\",}\n";
        let result = run(source, &ValidationPolicy::laboratory());
        let diagnostics = result
            .diagnostics
            .iter()
            .filter(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_TEX_SPECIAL)
            .collect::<Vec<_>>();
        assert_eq!(diagnostics.len(), 1);
        let fix = result
            .fixes
            .iter()
            .find(|fix| diagnostics[0].fixes.contains(&fix.id))
            .unwrap();
        assert_eq!(fix.applicability, FixApplicability::RequiresConfirmation);
        assert_eq!(fix.edits.len(), 6);
    }

    #[test]
    fn unicode_verbatim_delimiters_are_matched_as_characters() {
        let complete = "@misc{k, title=\"\\verbあい_うあ\",}\n";
        assert!(run(complete, &ValidationPolicy::laboratory())
            .diagnostics
            .iter()
            .all(|diagnostic| diagnostic.code.as_str() != RULE_UNESCAPED_TEX_SPECIAL));

        let incomplete = "@misc{k, title=\"\\verbあい_う\",}\n";
        let result = run(incomplete, &ValidationPolicy::laboratory());
        let diagnostic = result
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_TEX_SPECIAL)
            .unwrap();
        let fix = result
            .fixes
            .iter()
            .find(|fix| diagnostic.fixes.contains(&fix.id))
            .unwrap();
        assert_eq!(fix.applicability, FixApplicability::RequiresConfirmation);
        assert_eq!(fix.edits.len(), 1);
        assert_eq!(
            &incomplete[fix.edits[0].range.start as usize..fix.edits[0].range.end as usize],
            "_"
        );
    }

    #[test]
    fn at_sign_is_recognized_as_a_verbatim_delimiter() {
        let complete = "@misc{k, title=\"\\verb@a_b%@\",}\n";
        assert!(run(complete, &ValidationPolicy::laboratory())
            .diagnostics
            .iter()
            .all(|diagnostic| diagnostic.code.as_str() != RULE_UNESCAPED_TEX_SPECIAL));

        let incomplete = "@misc{k, title=\"\\verb@a_b%\",}\n";
        let result = run(incomplete, &ValidationPolicy::laboratory());
        let diagnostic = result
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_TEX_SPECIAL)
            .unwrap();
        let fix = result
            .fixes
            .iter()
            .find(|fix| diagnostic.fixes.contains(&fix.id))
            .unwrap();
        assert_eq!(fix.applicability, FixApplicability::RequiresConfirmation);
        assert_eq!(fix.edits.len(), 2);
    }

    #[test]
    fn incomplete_special_verbatim_delimiters_require_confirmation() {
        for delimiter in ['%', '$'] {
            let complete = format!("@misc{{k, title=\"\\verb{delimiter}abc{delimiter}\",}}\n");
            assert!(run(&complete, &ValidationPolicy::laboratory())
                .diagnostics
                .iter()
                .all(|diagnostic| diagnostic.code.as_str() != RULE_UNESCAPED_TEX_SPECIAL));

            let incomplete = format!("@misc{{k, title=\"\\verb{delimiter}abc\",}}\n");
            let result = run(&incomplete, &ValidationPolicy::laboratory());
            let diagnostic = result
                .diagnostics
                .iter()
                .find(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_TEX_SPECIAL)
                .unwrap();
            let fix = result
                .fixes
                .iter()
                .find(|fix| diagnostic.fixes.contains(&fix.id))
                .unwrap();
            assert_eq!(fix.applicability, FixApplicability::RequiresConfirmation);
            assert_eq!(fix.edits.len(), 1);
            assert_eq!(
                &incomplete[fix.edits[0].range.start as usize..fix.edits[0].range.end as usize],
                delimiter.to_string()
            );
        }
    }

    #[test]
    fn verbatim_options_use_the_normal_literal_and_math_scanner() {
        let source = "@misc{k, title={\\Verb[format=$x_1$ # 20%, url=\\url{a_b%20}, code=\\verb|x_y%|, raw=z_1]|ok|},}\n";
        let result = run(source, &ValidationPolicy::laboratory());
        let diagnostic = result
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_TEX_SPECIAL)
            .unwrap();
        let fix = result
            .fixes
            .iter()
            .find(|fix| diagnostic.fixes.contains(&fix.id))
            .unwrap();
        assert_eq!(fix.applicability, FixApplicability::RequiresConfirmation);
        assert_eq!(
            fix.edits
                .iter()
                .map(|edit| &source[edit.range.start as usize..edit.range.end as usize])
                .collect::<Vec<_>>(),
            ["#", "%", "_"]
        );
    }

    #[test]
    fn incomplete_verbatim_options_suppress_nested_math_recognition() {
        let source = "@misc{k, title=\"\\Verb[format=$x_1^2 & y # 20%$\",}\n";
        let result = run(source, &ValidationPolicy::laboratory());
        let diagnostic = result
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_TEX_SPECIAL)
            .unwrap();
        let fix = result
            .fixes
            .iter()
            .find(|fix| diagnostic.fixes.contains(&fix.id))
            .unwrap();
        assert_eq!(fix.applicability, FixApplicability::RequiresConfirmation);
        assert_eq!(
            fix.edits
                .iter()
                .map(|edit| &source[edit.range.start as usize..edit.range.end as usize])
                .collect::<Vec<_>>(),
            ["$", "_", "^", "&", "#", "%", "$"]
        );
    }

    #[test]
    fn optional_argument_math_is_scoped_to_the_argument() {
        let source = "@misc{k, title={\\Verb[$x_1]|body| $y_2},}\n";
        let result = run(source, &ValidationPolicy::laboratory());
        let diagnostic = result
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_TEX_SPECIAL)
            .unwrap();
        let fix = result
            .fixes
            .iter()
            .find(|fix| diagnostic.fixes.contains(&fix.id))
            .unwrap();
        assert_eq!(fix.applicability, FixApplicability::RequiresConfirmation);
        assert_eq!(
            fix.edits
                .iter()
                .map(|edit| &source[edit.range.start as usize..edit.range.end as usize])
                .collect::<Vec<_>>(),
            ["$", "_", "$", "_"]
        );
    }

    #[test]
    fn referenced_string_percent_propagates_concatenation_risk() {
        for (source, expected) in [
            (
                "@string{leaf={100% ready}}\n@string{nested=leaf}\n@misc{k, title=nested,}\n",
                FixApplicability::Safe,
            ),
            (
                "@string{urlcmd={\\url}}\n@string{urlarg={{https://example.test/a%20_b?x=1&anchor=#frag^$}}}\n@string{full=urlcmd # urlarg}\n@misc{k, title=full,}\n",
                FixApplicability::RequiresConfirmation,
            ),
            (
                "@string{leaf={50% ready}}\n@string{nested=leaf}\n@misc{k, title={Prefix} # nested,}\n",
                FixApplicability::RequiresConfirmation,
            ),
        ] {
            let result = run(source, &ValidationPolicy::laboratory());
            let diagnostics = result
                .diagnostics
                .iter()
                .filter(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_PERCENT)
                .collect::<Vec<_>>();
            assert_eq!(diagnostics.len(), 1, "{source}");
            let fix = result
                .fixes
                .iter()
                .find(|fix| diagnostics[0].fixes.contains(&fix.id))
                .unwrap();
            assert_eq!(fix.applicability, expected, "{source}");
        }
    }

    #[test]
    fn tex_special_macro_math_split_never_offers_a_safe_fix() {
        let source = "@string{open={$}}\n@string{body={x_1^2}}\n@string{close={$}}\n@string{full=open # body # close}\n@misc{k, title=full,}\n";
        let result = run(source, &ValidationPolicy::laboratory());
        let diagnostics = result
            .diagnostics
            .iter()
            .filter(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_TEX_SPECIAL)
            .collect::<Vec<_>>();
        assert_eq!(diagnostics.len(), 3);
        assert!(diagnostics.iter().all(|diagnostic| diagnostic.blocking));
        let fixes = diagnostics
            .iter()
            .flat_map(|diagnostic| &diagnostic.fixes)
            .map(|id| result.fixes.iter().find(|fix| &fix.id == id).unwrap())
            .collect::<Vec<_>>();
        assert_eq!(fixes.len(), 3);
        assert!(fixes
            .iter()
            .all(|fix| fix.applicability == FixApplicability::RequiresConfirmation));
    }

    #[test]
    fn archived_percent_values_are_url_like_and_shared_macros_have_no_fix() {
        let source = "@string{shared={https://example.test/shared%20copy}}\n@misc{k, archived={https://example.test/direct%20copy}, title=shared,}\n@misc{k2, archived=shared,}\n";
        let result = run(source, &ValidationPolicy::laboratory());
        let diagnostics = result
            .diagnostics
            .iter()
            .filter(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_PERCENT)
            .collect::<Vec<_>>();
        assert_eq!(diagnostics.len(), 1);
        let percent = source.find("shared%20").unwrap() + "shared".len();
        assert_eq!(
            diagnostics[0].primary_location.as_ref().unwrap().range,
            TextRange::checked(percent, percent + 1).unwrap()
        );
        assert!(diagnostics[0].message.contains("`archived`"));
        assert!(diagnostics[0].message.contains("`title`"));
        assert!(diagnostics[0].fixes.is_empty());
    }

    #[test]
    fn percent_diagnostics_aggregate_edits_and_bound_large_values() {
        let source = "@misc{k, title={10% ready and 20% complete},}\n";
        let result = run(source, &ValidationPolicy::laboratory());
        let diagnostics = result
            .diagnostics
            .iter()
            .filter(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_PERCENT)
            .collect::<Vec<_>>();
        assert_eq!(diagnostics.len(), 1);
        let fix = result
            .fixes
            .iter()
            .find(|fix| diagnostics[0].fixes.contains(&fix.id))
            .unwrap();
        assert_eq!(fix.edits.len(), 2);

        let many_percents = "%".repeat(MAX_TEX_SPECIAL_OCCURRENCES_PER_ISSUE + 32);
        for source in [
            format!("@misc{{k, title={{{many_percents}}},}}\n"),
            format!("@string{{many={{{many_percents}}}}}\n@misc{{k, title=many,}}\n"),
        ] {
            let result = run(&source, &ValidationPolicy::laboratory());
            let diagnostics = result
                .diagnostics
                .iter()
                .filter(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_PERCENT)
                .collect::<Vec<_>>();
            assert_eq!(diagnostics.len(), 1);
            assert!(diagnostics[0].fixes.is_empty());
            assert!(diagnostics[0]
                .notes
                .iter()
                .any(|note| note.contains("32 additional ranges were omitted")));
        }
    }

    #[test]
    fn percent_scanner_is_linear_and_has_bounded_output_for_deep_large_values() {
        let nesting = 16_384;
        let percent_count = 2 * 1024 * 1024;
        let mut value = Vec::with_capacity(nesting * 2 + percent_count + 9);
        value.extend_from_slice(b"\\textbf{");
        value.extend(std::iter::repeat_n(b'{', nesting));
        value.extend(std::iter::repeat_n(b'%', percent_count));
        value.extend(std::iter::repeat_n(b'}', nesting + 1));

        let mut occurrences = LiteralTexSpecialOccurrences::default();
        scan_literal_tex_special_atom(&value, 0, &mut occurrences);

        assert!(occurrences.plain_safe.is_empty());
        assert_eq!(
            occurrences.review.items.len(),
            MAX_TEX_SPECIAL_OCCURRENCES_PER_ISSUE
        );
        assert_eq!(
            occurrences.review.omitted,
            percent_count - MAX_TEX_SPECIAL_OCCURRENCES_PER_ISSUE
        );
    }

    #[test]
    fn tex_special_scanner_bounds_mixed_output_and_deep_incomplete_math() {
        let repeats = 512 * 1024;
        let mut mixed = Vec::with_capacity(repeats * 5 + 9);
        mixed.extend_from_slice(b"\\textbf{");
        for _ in 0..repeats {
            mixed.extend_from_slice(b"%&#_^");
        }
        mixed.push(b'}');
        let mut occurrences = LiteralTexSpecialOccurrences::default();
        scan_literal_tex_special_atom(&mixed, 0, &mut occurrences);
        assert!(occurrences.plain_safe.is_empty());
        assert_eq!(
            occurrences.review.len(),
            MAX_TEX_SPECIAL_OCCURRENCES_PER_ISSUE
        );
        assert_eq!(
            occurrences.review.omitted,
            repeats * 5 - MAX_TEX_SPECIAL_OCCURRENCES_PER_ISSUE
        );

        for opener in [b"\\(".as_slice(), b"\\[".as_slice()] {
            let mut incomplete = Vec::with_capacity(20_001 * opener.len());
            for _ in 0..20_000 {
                incomplete.extend_from_slice(opener);
                incomplete.push(b'_');
            }
            let mut occurrences = LiteralTexSpecialOccurrences::default();
            scan_literal_tex_special_atom(&incomplete, 0, &mut occurrences);
            assert_eq!(
                occurrences.review.len(),
                MAX_TEX_SPECIAL_OCCURRENCES_PER_ISSUE
            );
            assert_eq!(
                occurrences.review.omitted,
                20_000 - MAX_TEX_SPECIAL_OCCURRENCES_PER_ISSUE
            );
        }

        let mut ensuremath = Vec::new();
        for _ in 0..20_000 {
            ensuremath.extend_from_slice(b"\\ensuremath{");
            ensuremath.push(b'_');
        }
        let mut occurrences = LiteralTexSpecialOccurrences::default();
        scan_literal_tex_special_atom(&ensuremath, 0, &mut occurrences);
        assert_eq!(
            occurrences.review.len(),
            MAX_TEX_SPECIAL_OCCURRENCES_PER_ISSUE
        );
        assert_eq!(
            occurrences.review.omitted,
            20_000 - MAX_TEX_SPECIAL_OCCURRENCES_PER_ISSUE
        );
    }

    #[test]
    fn referenced_string_percent_traversal_is_memoized_cycle_safe_and_depth_bounded() {
        let mut dag = String::new();
        for index in 0..64 {
            writeln!(dag, "@string{{branch{index}=shared}}").unwrap();
        }
        for index in 0..64 {
            writeln!(dag, "@misc{{k{index}, title=branch{index},}}").unwrap();
        }
        dag.push_str("@string{shared={50%\n}}\n");
        let syntax = parse(&dag, ParseOptions::tolerant());
        let analysis = referenced_string_tex_special_analysis(&syntax);
        assert_eq!(analysis.issues.len(), 1);
        assert_eq!(analysis.issues[0].macro_name, "shared");
        assert_eq!(analysis.completed_macro_visits, 65);
        assert!(analysis.incomplete_range.is_none());

        let cycle = "@string{a=b # {50%\n}}\n@string{b=a}\n@misc{k, title=a,}\n";
        let syntax = parse(cycle, ParseOptions::tolerant());
        let analysis = referenced_string_tex_special_analysis(&syntax);
        assert_eq!(analysis.issues.len(), 1);
        assert_eq!(analysis.issues[0].macro_name, "a");
        assert_eq!(analysis.completed_macro_visits, 2);
        assert!(analysis.incomplete_range.is_none());

        let exact = percent_macro_chain(MAX_TEX_SPECIAL_MACRO_EXPANSION_DEPTH);
        let syntax = parse(&exact, ParseOptions::tolerant());
        let analysis = referenced_string_tex_special_analysis(&syntax);
        assert_eq!(analysis.issues.len(), 1);
        assert_eq!(analysis.issues[0].macro_name, "m0");
        assert_eq!(
            analysis.completed_macro_visits,
            MAX_TEX_SPECIAL_MACRO_EXPANSION_DEPTH
        );
        assert!(analysis.incomplete_range.is_none());

        let root = MAX_TEX_SPECIAL_MACRO_EXPANSION_DEPTH;
        let over = percent_macro_chain(root + 1).replacen(
            &format!("@string{{m{root}=m{}}}\n", root - 1),
            &format!("@string{{m{root}={{25%\n}} # m{}}}\n", root - 1),
            1,
        );
        let syntax = parse(&over, ParseOptions::tolerant());
        let analysis = referenced_string_tex_special_analysis(&syntax);
        assert_eq!(analysis.issues.len(), 1);
        assert_eq!(analysis.issues[0].macro_name, format!("m{root}"));
        assert_eq!(
            analysis.completed_macro_visits,
            MAX_TEX_SPECIAL_MACRO_EXPANSION_DEPTH
        );
        let incomplete_range = analysis.incomplete_range.unwrap();
        assert_eq!(syntax.slice(incomplete_range), Some("m0"));

        let semantics = analyze(&syntax);
        let registration = validate_for_registration(
            &syntax,
            &semantics,
            &ValidationPolicy::laboratory(),
            &RegistrationPolicy::laboratory(),
        );
        assert!(!registration.accepted);
        let percent_diagnostics = registration
            .diagnostics
            .iter()
            .filter(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_PERCENT)
            .collect::<Vec<_>>();
        assert_eq!(percent_diagnostics.len(), 2);
        assert!(percent_diagnostics
            .iter()
            .all(|diagnostic| diagnostic.fixes.is_empty()));
        let incomplete = registration
            .diagnostics
            .iter()
            .find(|diagnostic| {
                diagnostic.code.as_str() == RULE_UNESCAPED_PERCENT
                    && diagnostic.message.contains("incomplete")
            })
            .expect("depth-limit incomplete diagnostic");
        assert!(incomplete.blocking);
        assert!(incomplete.fixes.is_empty());
        assert_eq!(
            incomplete.primary_location.as_ref().unwrap().range,
            incomplete_range
        );
    }

    #[test]
    fn referenced_string_percent_visit_cap_is_blocking_and_disables_macro_fixes() {
        let source =
            "@string{root={50%\n} # child}\n@string{child={25%\n}}\n@misc{k, title=root,}\n";
        let syntax = parse(source, ParseOptions::tolerant());
        let analysis = referenced_string_tex_special_analysis_with_limit(&syntax, 1);
        assert_eq!(analysis.completed_macro_visits, 1);
        assert_eq!(analysis.issues.len(), 1);
        let incomplete_range = analysis.incomplete_range.unwrap();
        assert_eq!(syntax.slice(incomplete_range), Some("child"));

        let policy = ValidationPolicy::laboratory();
        let mut engine = Engine::new(&syntax, &policy);
        engine.validate_referenced_string_tex_specials_with_limit(1);
        let result = engine.finish();
        let diagnostics = result
            .diagnostics
            .iter()
            .filter(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_PERCENT)
            .collect::<Vec<_>>();
        assert_eq!(diagnostics.len(), 2);
        assert!(diagnostics.iter().all(|diagnostic| diagnostic.blocking));
        assert!(diagnostics
            .iter()
            .all(|diagnostic| diagnostic.fixes.is_empty()));
        assert!(diagnostics
            .iter()
            .any(|diagnostic| diagnostic.message.contains("incomplete")));
        assert!(result.has_blocking_diagnostics());
        assert!(result.fixes.is_empty());
    }

    #[test]
    fn duplicate_string_definition_candidates_consume_the_global_visit_budget() {
        let source =
            "@string{x={first_}}\n@string{x={second_}}\n@string{x={third_}}\n@misc{k, f0=x, f1=x,}\n";
        let syntax = parse(source, ParseOptions::tolerant());
        let analysis = referenced_string_tex_special_analysis_with_limit(&syntax, 4);
        assert_eq!(analysis.completed_macro_visits, 2);
        assert_eq!(analysis.issues.len(), 3);
        let incomplete_range = analysis.incomplete_range.unwrap();
        assert_eq!(syntax.slice(incomplete_range), Some("x"));

        let policy = ValidationPolicy::laboratory();
        let mut engine = Engine::new(&syntax, &policy);
        engine.validate_referenced_string_tex_specials_with_limit(4);
        let result = engine.finish();
        let diagnostics = result
            .diagnostics
            .iter()
            .filter(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_TEX_SPECIAL)
            .collect::<Vec<_>>();
        assert_eq!(diagnostics.len(), 4);
        assert!(diagnostics.iter().all(|diagnostic| diagnostic.blocking));
        assert!(diagnostics
            .iter()
            .all(|diagnostic| diagnostic.fixes.is_empty()));
        assert!(diagnostics
            .iter()
            .any(|diagnostic| diagnostic.message.contains("incomplete")));
        assert!(result.fixes.is_empty());
    }

    #[test]
    fn string_definition_index_precomputes_risk_and_deduplicates_reference_edges() {
        let source =
            "@string{x=y # Y # y}\n@string{x={plain}}\n@string{y={value_1}}\n@misc{k, title=x,}\n";
        let syntax = parse(source, ParseOptions::tolerant());
        let definitions = tex_special_string_definitions(&syntax);
        let x = definitions.get("x").unwrap();
        assert!(x.concatenated);
        assert_eq!(x.definitions.len(), 2);
        assert_eq!(x.definitions[0].references.len(), 1);
        assert_eq!(x.definitions[0].references[0].name, "y");

        let analysis = referenced_string_tex_special_analysis(&syntax);
        assert_eq!(analysis.completed_macro_visits, 2);
        assert!(analysis.incomplete_range.is_none());
    }

    #[test]
    fn syntax_style_severity_and_blocking_are_policy_controlled() {
        for (source, code) in [
            ("@misc{k,title={T},}\n", RULE_EQUALS_WHITESPACE),
            (
                "@misc{k, title = {T}, % misplaced\n}\n",
                RULE_INLINE_PERCENT_COMMENT,
            ),
        ] {
            let mut policy = ValidationPolicy::default();
            policy.rules.insert(
                RuleCode::new(code),
                RuleSetting {
                    enabled: true,
                    severity: Severity::Error,
                    blocking: true,
                },
            );
            let diagnostic = run(source, &policy)
                .diagnostics
                .into_iter()
                .find(|diagnostic| diagnostic.code.as_str() == code)
                .unwrap();
            assert_eq!(diagnostic.severity, Severity::Error);
            assert!(diagnostic.blocking);
        }
    }

    #[test]
    fn doi_and_arxiv_validation_normalizes_prefixes() {
        let result = run(
            "@misc{k, doi={https://doi.org/10.1000/ABC}, eprint={arXiv:1706.03762},}\n",
            &ValidationPolicy::default(),
        );
        assert!(result
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code.as_str() == RULE_DOI));
        assert!(result
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code.as_str() == RULE_ARXIV));
    }

    #[test]
    fn non_arxiv_eprint_is_not_validated_as_an_arxiv_identifier() {
        let result = run(
            "@misc{k, eprint={10.1101/123456}, archivePrefix={bioRxiv},}\n",
            &ValidationPolicy::default(),
        );
        assert!(!result
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code.as_str() == RULE_ARXIV));
    }

    #[test]
    fn repository_registry_patterns_validate_non_arxiv_eprints() {
        let valid = run(
            "@misc{k, eprint={10.1101/2025.01.02.123456}, archivePrefix={bioRxiv},}\n",
            &ValidationPolicy::default(),
        );
        assert!(!valid
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code.as_str() == RULE_REPOSITORY_IDENTIFIER));

        let invalid = run(
            "@misc{k, eprint={not-a-doi}, archivePrefix={bioRxiv},}\n",
            &ValidationPolicy::default(),
        );
        let diagnostic = invalid
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code.as_str() == RULE_REPOSITORY_IDENTIFIER)
            .unwrap();
        assert_eq!(diagnostic.related_locations.len(), 1);
        assert_eq!(
            &"@misc{k, eprint={not-a-doi}, archivePrefix={bioRxiv},}\n"[diagnostic
                .primary_location
                .as_ref()
                .unwrap()
                .range
                .start
                as usize
                ..diagnostic.primary_location.as_ref().unwrap().range.end as usize],
            "not-a-doi"
        );
    }

    #[test]
    fn unresolved_year_has_a_precise_policy_controlled_diagnostic() {
        let source = "@article{k, author={Doe, Jane}, title={T}, journal={J}, year={twenty},}\n";
        let mut policy = ValidationPolicy::default();
        policy.rules.insert(
            RuleCode::new(RULE_UNRESOLVED_SEMANTICS),
            RuleSetting {
                enabled: true,
                severity: Severity::Warning,
                blocking: false,
            },
        );
        let result = run(source, &policy);
        let diagnostic = result
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code.as_str() == RULE_UNRESOLVED_SEMANTICS)
            .unwrap();
        let range = diagnostic.primary_location.as_ref().unwrap().range;
        assert_eq!(
            &source[range.start as usize..range.end as usize],
            "{twenty}"
        );

        let syntax = parse(source, ParseOptions::tolerant());
        let semantics = analyze(&syntax);
        let registration_policy = RegistrationPolicy {
            minimum_severity: None,
            allow_unresolved_semantics: false,
            ..RegistrationPolicy::default()
        };
        let registration =
            validate_for_registration(&syntax, &semantics, &policy, &registration_policy);
        assert!(!registration.accepted);
        assert!(registration.unresolved_semantics);
        assert!(registration.diagnostics.iter().any(|diagnostic| {
            diagnostic.code.as_str() == RULE_UNRESOLVED_SEMANTICS && diagnostic.blocking
        }));
    }

    #[test]
    fn workshop_venue_mismatch_uses_venue_origin_and_confirmation_fix() {
        let source =
            "@article{k, author={Doe, Jane}, title={T}, journal={Workshop}, year={2024},}\n";
        let syntax = parse(source, ParseOptions::tolerant());
        let mut semantics = analyze(&syntax);
        let venue = semantics.records[0].venue.as_mut().unwrap();
        venue.value.kind = Some(VenueKind::Workshop);
        let venue_range = venue.origins[0].range;

        let result = validate(&syntax, &semantics, &ValidationPolicy::default());
        let diagnostic = result
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code.as_str() == RULE_TYPE_MISMATCH)
            .unwrap();
        let primary_range = diagnostic.primary_location.as_ref().unwrap().range;
        assert_eq!(
            &source[primary_range.start as usize..primary_range.end as usize],
            "article"
        );
        assert_eq!(diagnostic.related_locations[0].location.range, venue_range);
        assert_eq!(
            &source[venue_range.start as usize..venue_range.end as usize],
            "{Workshop}"
        );

        let fix = result
            .fixes
            .iter()
            .find(|fix| diagnostic.fixes.contains(&fix.id))
            .unwrap();
        assert_eq!(fix.applicability, FixApplicability::RequiresConfirmation);
        assert_eq!(fix.edits[0].replacement, "inproceedings");
    }

    #[test]
    fn duplicate_record_identities_have_cross_record_related_locations() {
        let source = "@article{Same, title={One}, journal={J}, year={2024}, doi={10.1000/X},}\n@misc{same, title={Two}, doi={https://doi.org/10.1000/x},}\n";
        let result = run(source, &ValidationPolicy::default());

        for code in [RULE_DUPLICATE_CITATION_KEY, RULE_DUPLICATE_DOI] {
            let diagnostic = result
                .diagnostics
                .iter()
                .find(|diagnostic| diagnostic.code.as_str() == code)
                .unwrap();
            assert!(diagnostic.blocking);
            assert_eq!(diagnostic.related_locations.len(), 1);
            assert_ne!(
                diagnostic.primary_location.as_ref().unwrap().range,
                diagnostic.related_locations[0].location.range
            );
        }
    }

    #[test]
    fn citation_key_fix_is_accepted_by_every_style_profile() {
        let source = "@misc{Bad_Key:2024, title={T},}\n";
        let laboratory = ValidationPolicy::builtin("laboratory").unwrap();
        let result = run(source, &laboratory);
        let diagnostic = result
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code.as_str() == RULE_CITATION_KEY)
            .unwrap();
        let fix = result
            .fixes
            .iter()
            .find(|fix| diagnostic.fixes.contains(&fix.id))
            .unwrap();
        let replacement = &fix.edits[0].replacement;

        assert_eq!(replacement, "bad-key-2024");
        assert_ne!(replacement, "Bad_Key:2024");
        for profile in ["default", "modern", "laboratory", "acl", "classical-bst"] {
            let policy = ValidationPolicy::builtin(profile).unwrap();
            assert!(Regex::new(&policy.citation_key_pattern)
                .unwrap()
                .is_match(replacement));
        }

        let plan = plan_fixes(
            &SourceRevision::of(source),
            &result.fixes,
            &FixSelection::Ids(vec![fix.id.clone()]),
        )
        .unwrap();
        let applied = apply_fix_plan(source, &plan).unwrap();
        assert!(!run(&applied.source, &laboratory)
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code.as_str() == RULE_CITATION_KEY));
    }

    #[test]
    fn citation_key_normalization_handles_nonportable_boundaries() {
        for (source, expected) in [
            ("123", "ref-123"),
            ("---", "ref"),
            ("A___B", "a-b"),
            (" é Example ", "example"),
        ] {
            let normalized = normalize_citation_key(source);
            assert_eq!(normalized, expected);
            for profile in ["default", "modern", "laboratory", "acl", "classical-bst"] {
                let policy = ValidationPolicy::builtin(profile).unwrap();
                assert!(Regex::new(&policy.citation_key_pattern)
                    .unwrap()
                    .is_match(&normalized));
            }
        }
    }

    #[test]
    fn archive_citation_key_fixes_are_only_offered_when_the_result_is_valid() {
        let policy = ValidationPolicy::archive();

        for citation_key in ["asada-2026any", "asada2026any", "asada-2026"] {
            let source = format!("@misc{{{citation_key}, title={{T}},}}\n");
            let result = run(&source, &policy);
            let diagnostic = result
                .diagnostics
                .iter()
                .find(|diagnostic| diagnostic.code.as_str() == RULE_CITATION_KEY)
                .unwrap();
            assert!(diagnostic.blocking);
            assert!(
                diagnostic.fixes.is_empty(),
                "`{citation_key}` received an invalid automatic fix"
            );
        }

        let source = "@misc{Asada-2026-Principled, title={T},}\n";
        let result = run(source, &policy);
        let diagnostic = result
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code.as_str() == RULE_CITATION_KEY)
            .unwrap();
        let fix = result
            .fixes
            .iter()
            .find(|fix| diagnostic.fixes.contains(&fix.id))
            .unwrap();
        assert_eq!(fix.edits[0].replacement, "asada-2026-principled");
    }

    #[test]
    fn laboratory_style_diagnostics_do_not_block_registration() {
        let source = "@article{smith2024, YEAR={2024}, journal=\"J\", author={Doe, Jane}, title={T}, url={https://example.test}}\n";
        let syntax = parse(source, ParseOptions::tolerant());
        let semantics = analyze(&syntax);
        let validation_policy = ValidationPolicy::laboratory();
        let registration_policy = RegistrationPolicy::laboratory();
        let result = validate_for_registration(
            &syntax,
            &semantics,
            &validation_policy,
            &registration_policy,
        );

        assert_eq!(registration_policy.minimum_severity, Some(Severity::Error));
        assert!(
            result.accepted,
            "unexpected blocking diagnostics: {:?}",
            result
                .diagnostics
                .iter()
                .filter(|diagnostic| diagnostic.blocking)
                .map(|diagnostic| diagnostic.code.as_str())
                .collect::<Vec<_>>()
        );
        for code in [
            RULE_FIELD_CASE,
            RULE_FIELD_ORDER,
            RULE_TRAILING_COMMA,
            RULE_VALUE_DELIMITER,
            RULE_EQUALS_WHITESPACE,
        ] {
            let diagnostic = result
                .diagnostics
                .iter()
                .find(|diagnostic| diagnostic.code.as_str() == code)
                .unwrap_or_else(|| panic!("missing expected style diagnostic {code}"));
            assert!(!diagnostic.blocking, "{code} should not block registration");
        }
        assert!(!result
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code.as_str() == RULE_URL_POLICY));
    }

    #[test]
    fn url_projection_guidance_never_offers_a_deletion_fix() {
        let source = "@misc{key, title = {T}, url = {https://example.test},}\n";

        for url_policy in [UrlPolicy::Discourage, UrlPolicy::Forbid] {
            let mut policy = ValidationPolicy::modern();
            policy.url_policy = url_policy;
            let result = run(source, &policy);
            let diagnostic = result
                .diagnostics
                .iter()
                .find(|diagnostic| diagnostic.code.as_str() == RULE_URL_POLICY)
                .expect("missing URL projection guidance");

            assert!(diagnostic.fixes.is_empty());
            assert!(result
                .fixes
                .iter()
                .all(|fix| fix.title != "Remove URL field"));
        }
    }

    #[test]
    fn laboratory_keeps_entry_internal_percent_comments_blocking() {
        let source = "@misc{key, title = {T}, % move this comment\n}\n";
        let syntax = parse(source, ParseOptions::tolerant());
        let semantics = analyze(&syntax);
        let result = validate_for_registration(
            &syntax,
            &semantics,
            &ValidationPolicy::laboratory(),
            &RegistrationPolicy::laboratory(),
        );

        assert!(!result.accepted);
        let comment = result
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code.as_str() == RULE_INLINE_PERCENT_COMMENT)
            .expect("entry-internal percent comment diagnostic");
        assert_eq!(comment.severity, Severity::Warning);
        assert!(comment.blocking);
    }

    #[test]
    fn laboratory_registration_rejects_an_unescaped_percent_value() {
        let source = "@article{smith2024,\n  title = {100% Effective},\n  author = {Doe, Jane},\n  journal = {J},\n  year = {2024},\n}\n";
        let syntax = parse(source, ParseOptions::tolerant());
        let semantics = analyze(&syntax);
        let result = validate_for_registration(
            &syntax,
            &semantics,
            &ValidationPolicy::laboratory(),
            &RegistrationPolicy::laboratory(),
        );

        assert!(!result.accepted);
        let diagnostic = result
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_PERCENT)
            .expect("unescaped percent diagnostic");
        assert_eq!(diagnostic.severity, Severity::Error);
        assert!(diagnostic.blocking);
        assert_eq!(diagnostic.fixes.len(), 1);
        assert!(result.safe_fix_ids.contains(&diagnostic.fixes[0]));
    }

    #[test]
    fn laboratory_registration_rejects_an_unescaped_percent_from_a_string_macro() {
        let source = "@string{percenttitle={100% Effective}}\n@article{smith2024,\n  title = percenttitle,\n  author = {Doe, Jane},\n  journal = {J},\n  year = {2024},\n}\n";
        let syntax = parse(source, ParseOptions::tolerant());
        let semantics = analyze(&syntax);
        let result = validate_for_registration(
            &syntax,
            &semantics,
            &ValidationPolicy::laboratory(),
            &RegistrationPolicy::laboratory(),
        );

        assert!(!result.accepted);
        let diagnostic = result
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code.as_str() == RULE_UNESCAPED_PERCENT)
            .expect("unescaped percent diagnostic from @string");
        assert_eq!(diagnostic.severity, Severity::Error);
        assert!(diagnostic.blocking);
        assert_eq!(diagnostic.fixes.len(), 1);
        assert!(result.safe_fix_ids.contains(&diagnostic.fixes[0]));
    }

    #[test]
    fn laboratory_rejects_a_malformed_url_without_retention_guidance() {
        let source = "@article{smith2024, title = {T}, author = {Doe, Jane}, journal = {J}, year = {2024}, url = {not a URL},}\n";
        let syntax = parse(source, ParseOptions::tolerant());
        let semantics = analyze(&syntax);
        let result = validate_for_registration(
            &syntax,
            &semantics,
            &ValidationPolicy::laboratory(),
            &RegistrationPolicy::laboratory(),
        );

        assert!(!result.accepted);
        let malformed = result
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code.as_str() == "BIB-SEMANTIC-106")
            .expect("malformed URL diagnostic");
        assert_eq!(malformed.severity, Severity::Error);
        assert!(malformed.blocking);
        assert!(!result
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code.as_str() == RULE_URL_POLICY));
    }

    #[test]
    fn canonical_validation_rules_replace_duplicate_semantic_diagnostics() {
        let policy = ValidationPolicy::laboratory();
        for (source, canonical, retired) in [
            (
                "@misc{key, title = {T}, doi = {not-a-doi},}\n",
                RULE_DOI,
                "BIB-SEMANTIC-103",
            ),
            (
                "@misc{key, title = {T}, eprint = {not-an-arxiv}, archiveprefix = {arXiv},}\n",
                RULE_ARXIV,
                "BIB-SEMANTIC-104",
            ),
            (
                "@article{key, title = {T}, author = {Doe, Jane}, journal = {J}, year = {2024}, date = {2023-01-01},}\n",
                RULE_DATE,
                "BIB-SEMANTIC-105",
            ),
        ] {
            let result = run(source, &policy);
            assert_eq!(
                result
                    .diagnostics
                    .iter()
                    .filter(|diagnostic| diagnostic.code.as_str() == canonical)
                    .count(),
                1,
                "{canonical} should be the only canonical diagnostic"
            );
            assert!(!result
                .diagnostics
                .iter()
                .any(|diagnostic| diagnostic.code.as_str() == retired));
        }
    }

    #[test]
    fn registration_separates_severity_from_blocking() {
        let source = "@misc{1key, TITLE={A},}\n";
        let syntax = parse(source, ParseOptions::tolerant());
        let semantics = analyze(&syntax);
        let validation_policy = ValidationPolicy::default();
        let permissive = RegistrationPolicy {
            minimum_severity: None,
            ..RegistrationPolicy::default()
        };
        let result =
            validate_for_registration(&syntax, &semantics, &validation_policy, &permissive);
        assert!(result.accepted);

        let strict = RegistrationPolicy {
            minimum_severity: Some(Severity::Hint),
            ..RegistrationPolicy::default()
        };
        let result = validate_for_registration(&syntax, &semantics, &validation_policy, &strict);
        assert!(!result.accepted);
        assert!(result
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.blocking));
    }

    #[test]
    fn registration_rejects_sources_without_semantic_records() {
        let validation_policy = ValidationPolicy::default();
        let registration_policy = RegistrationPolicy {
            minimum_severity: None,
            ..RegistrationPolicy::default()
        };

        for source in ["", "% comment only\n"] {
            let syntax = parse(source, ParseOptions::tolerant());
            let semantics = analyze(&syntax);
            let validation = validate(&syntax, &semantics, &validation_policy);
            assert!(semantics.records.is_empty());
            assert!(!registration_allowed(
                &validation.diagnostics,
                &semantics,
                &registration_policy,
            ));

            let registration = validate_for_registration(
                &syntax,
                &semantics,
                &validation_policy,
                &registration_policy,
            );
            assert!(!registration.accepted);
        }
    }

    #[test]
    fn bundled_registries_load_and_resolve_aliases() {
        let venues =
            VenueRegistry::from_toml(include_str!("../../../config/registries/venues.toml"))
                .unwrap();
        assert_eq!(
            venues.resolve("Proceedings of ACL").unwrap().id,
            "acl-annual-meeting"
        );
        assert_eq!(
            venues
                .resolve("Findings of the Association for Computational Linguistics: EMNLP 2023")
                .unwrap()
                .id,
            "findings-emnlp"
        );
        assert_eq!(
            venues
                .resolve(
                    "Proceedings of the 61st Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers)"
                )
                .unwrap()
                .id,
            "acl-annual-meeting"
        );
        assert_eq!(
            venues
                .resolve("Advances in Neural Information Processing Systems 2025")
                .unwrap()
                .id,
            "neurips"
        );

        let repositories = RepositoryRegistry::from_toml(include_str!(
            "../../../config/registries/repositories.toml"
        ))
        .unwrap();
        let arxiv = repositories.resolve("arXiv.org").unwrap();
        assert!(arxiv.accepts_identifier("1706.03762v2"));
        assert_eq!(
            arxiv.identifier_url("1706.03762").as_deref(),
            Some("https://arxiv.org/abs/1706.03762")
        );
    }

    #[test]
    fn registry_rejects_alias_conflicts_and_invalid_patterns() {
        let venues = r#"
schema_version = "1"
[[venues]]
id = "one"
full_name = "One"
short_name = "Shared"
aliases = []
kind = "journal"
[[venues]]
id = "two"
full_name = "Two"
short_name = "shared"
aliases = []
kind = "conference"
"#;
        assert!(matches!(
            VenueRegistry::from_toml(venues),
            Err(ConfigurationError::VenueAliasConflict { .. })
        ));

        let repositories = r#"
schema_version = "1"
[[repositories]]
id = "broken"
full_name = "Broken"
short_name = "Broken"
archive_prefix = "Broken"
identifier_pattern = "["
url_template = "https://example.test/{identifier}"
"#;
        assert!(matches!(
            RepositoryRegistry::from_toml(repositories),
            Err(ConfigurationError::InvalidRepositoryPattern { .. })
        ));
    }

    #[test]
    fn profile_registry_rejects_missing_parents_and_cycles() {
        let mut first = ValidationPolicy::modern();
        first.profile = ProfileId::new("first");
        first.extends = Some(ProfileId::new("second"));
        assert!(matches!(
            validate_policy_registry(&[first.clone()]),
            Err(ConfigurationError::MissingParentProfile { .. })
        ));

        let mut second = ValidationPolicy::modern();
        second.profile = ProfileId::new("second");
        second.extends = Some(ProfileId::new("first"));
        assert!(matches!(
            validate_policy_registry(&[first, second]),
            Err(ConfigurationError::InheritanceCycle(_))
        ));
    }
}
