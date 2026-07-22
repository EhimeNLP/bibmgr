//! Shared deterministic validation and registration policy engine.

use bibmgr_model::{
    Diagnostic, DiagnosticId, Fix, FixApplicability, FixId, ProfileId, RelatedLocation, RuleCode,
    Severity, SourceLocation, SourceRevision, TextEdit, TextRange,
};
pub use bibmgr_semantics::VenueKind;
use bibmgr_semantics::{Bibliography, WorkType};
use bibmgr_syntax::{EntryNode, FieldNode, SyntaxDocument, ValueAtomKind};
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::sync::OnceLock;

pub const RULE_DUPLICATE_FIELD: &str = "BIB-SYNTAX-001";
pub const RULE_FIELD_CASE: &str = "BIB-SYNTAX-002";
pub const RULE_FIELD_ORDER: &str = "BIB-SYNTAX-003";
pub const RULE_TRAILING_COMMA: &str = "BIB-SYNTAX-004";
pub const RULE_VALUE_DELIMITER: &str = "BIB-SYNTAX-005";
pub const RULE_EQUALS_WHITESPACE: &str = "BIB-SYNTAX-006";
pub const RULE_INLINE_PERCENT_COMMENT: &str = "BIB-SYNTAX-007";
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
                register_alias(&mut names, name, &id, |alias, first, second| {
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
        let normalized = normalize_alias(name);
        self.venues.iter().find(|venue| {
            normalize_alias(&venue.id) == normalized
                || normalize_alias(&venue.full_name) == normalized
                || normalize_alias(&venue.short_name) == normalized
                || venue
                    .aliases
                    .iter()
                    .any(|alias| normalize_alias(alias) == normalized)
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

fn register_alias(
    aliases: &mut BTreeMap<String, String>,
    alias: &str,
    id: &str,
    conflict: impl FnOnce(String, String, String) -> ConfigurationError,
) -> Result<(), ConfigurationError> {
    let alias = normalize_alias(alias);
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
        if Regex::new(&self.policy.citation_key_pattern)
            .ok()
            .is_some_and(|regex| !regex.is_match(&entry.citation_key.text))
        {
            let replacement = normalize_citation_key(&entry.citation_key.text);
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
                (!replacement.is_empty()).then_some(FixDraft {
                    title: format!("Change citation key to `{replacement}`"),
                    applicability: FixApplicability::RequiresConfirmation,
                    edits: vec![TextEdit {
                        range: entry.citation_key.range,
                        replacement,
                    }],
                }),
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
                let applicability = if self.policy.url_policy == UrlPolicy::Forbid {
                    FixApplicability::Unsafe
                } else {
                    FixApplicability::RequiresConfirmation
                };
                self.emit(
                    RULE_URL_POLICY,
                    String::from("URL retention conflicts with the configured profile"),
                    field.name.range,
                    vec![],
                    vec![],
                    Some(FixDraft {
                        title: String::from("Remove URL field"),
                        applicability,
                        edits: vec![TextEdit {
                            range: field.range,
                            replacement: String::new(),
                        }],
                    }),
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
        | RULE_INLINE_PERCENT_COMMENT => Severity::Warning,
        RULE_FIELD_CASE | RULE_TRAILING_COMMA => Severity::Hint,
        RULE_FIELD_ORDER | RULE_VALUE_DELIMITER | RULE_EQUALS_WHITESPACE => Severity::Information,
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
    use bibmgr_semantics::analyze;
    use bibmgr_syntax::{parse, ParseOptions};

    fn run(source: &str, policy: &ValidationPolicy) -> ValidationResult {
        let syntax = parse(source, ParseOptions::tolerant());
        let semantics = analyze(&syntax);
        validate(&syntax, &semantics, policy)
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
    fn citation_key_fix_is_accepted_by_every_builtin_profile() {
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
            RULE_URL_POLICY,
        ] {
            let diagnostic = result
                .diagnostics
                .iter()
                .find(|diagnostic| diagnostic.code.as_str() == code)
                .unwrap_or_else(|| panic!("missing expected style diagnostic {code}"));
            assert!(!diagnostic.blocking, "{code} should not block registration");
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
    fn laboratory_rejects_a_malformed_url_but_not_url_retention() {
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
        let retention = result
            .diagnostics
            .iter()
            .find(|diagnostic| diagnostic.code.as_str() == RULE_URL_POLICY)
            .expect("URL retention guidance");
        assert_eq!(retention.severity, Severity::Information);
        assert!(!retention.blocking);
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
