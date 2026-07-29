//! Stable, high-level orchestration API shared by the CLI and `PyO3` adapters.
//!
//! Callers intentionally cannot reorder parse, semantic analysis, validation,
//! editing, or post-edit validation: this facade owns the complete pipeline.

pub use bibmgr_edit::{EditError, FixPlan, FixPlanError, FixSelection};
pub use bibmgr_export::{
    ExportError, ExportProfile, ExportResult, PreprintRepresentation, VenueStyle,
};
pub use bibmgr_model::{
    Diagnostic, DiagnosticId, Fix, FixApplicability, FixId, RuleCode, SourceId, SourceRevision,
    TextEdit, TextRange, SCHEMA_VERSION,
};
pub use bibmgr_model::{ProfileId, Severity};
pub use bibmgr_semantics::Bibliography;
pub use bibmgr_syntax::{ParseMode, ParseOptions, SyntaxSummary};
pub use bibmgr_validation::{
    RegistrationPolicy, RepositoryRegistry, ValidationPolicy, VenueRegistry,
};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use std::sync::OnceLock;

pub use bibmgr_edit::{FixPlan as PlannedFixes, FixSelection as SelectedFixes};
pub use bibmgr_export::{ExportProfile as BibTeXExportProfile, ExportResult as BibTeXExportResult};
pub use bibmgr_validation::{
    RegistrationPolicy as BibTeXRegistrationPolicy, ValidationPolicy as BibTeXValidationPolicy,
};

/// Versioned, core-owned envelope returned by `bibmgr inspect --cst`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CstInspection {
    pub schema_version: String,
    pub source_revision: SourceRevision,
    pub document: bibmgr_syntax::SyntaxDocument,
}

/// Versioned, core-owned envelope returned by `bibmgr inspect --ast`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AstInspection {
    pub schema_version: String,
    pub source_revision: SourceRevision,
    pub bibliography: Bibliography,
}

/// Inspect the lossless syntax snapshot through the stable core facade.
pub fn inspect_cst(source: &str, options: ParseOptions) -> CstInspection {
    CstInspection {
        schema_version: SCHEMA_VERSION.to_owned(),
        source_revision: SourceRevision::of(source),
        document: bibmgr_syntax::parse(source, options),
    }
}

/// Inspect semantic records through the stable core facade.
pub fn inspect_ast(source: &str, options: ParseOptions) -> AstInspection {
    let syntax = bibmgr_syntax::parse(source, options);
    let mut bibliography = bibmgr_semantics::analyze(&syntax);
    enrich_from_builtin_registries(&mut bibliography);
    AstInspection {
        schema_version: SCHEMA_VERSION.to_owned(),
        source_revision: SourceRevision::of(source),
        bibliography,
    }
}

/// Options for the full analysis pipeline.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AnalysisOptions {
    pub parse_mode: ParseMode,
    pub source_id: SourceId,
    pub validation_policy: ValidationPolicy,
    /// Optional immutable registry snapshots. `None` selects the embedded
    /// registry; `Some(empty_registry)` explicitly disables that registry.
    #[serde(default)]
    pub venue_registry: Option<VenueRegistry>,
    #[serde(default)]
    pub repository_registry: Option<RepositoryRegistry>,
}

impl Default for AnalysisOptions {
    fn default() -> Self {
        Self {
            parse_mode: ParseMode::Tolerant,
            source_id: SourceId::from("source:0"),
            validation_policy: ValidationPolicy::default(),
            venue_registry: None,
            repository_registry: None,
        }
    }
}

/// Versioned result returned identically through Rust, JSON, and Python.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AnalysisResult {
    pub schema_version: String,
    pub source_revision: SourceRevision,
    pub syntax: SyntaxSummary,
    pub bibliography: Bibliography,
    pub diagnostics: Vec<Diagnostic>,
    pub available_fixes: Vec<Fix>,
}

impl AnalysisResult {
    pub fn has_blocking_diagnostics(&self) -> bool {
        self.diagnostics
            .iter()
            .any(|diagnostic| diagnostic.blocking)
    }
}

/// Analyze one complete BibTeX document. This function does not panic for user input.
pub fn analyze(source: &str, options: &AnalysisOptions) -> AnalysisResult {
    let syntax = bibmgr_syntax::parse(
        source,
        ParseOptions {
            mode: options.parse_mode,
            source_id: options.source_id.clone(),
        },
    );
    let mut bibliography = bibmgr_semantics::analyze(&syntax);
    let venue_registry: Option<&VenueRegistry> = match options.venue_registry.as_ref() {
        Some(registry) => Some(registry),
        None => builtin_venue_registry(),
    };
    let repository_registry: Option<&RepositoryRegistry> =
        match options.repository_registry.as_ref() {
            Some(registry) => Some(registry),
            None => builtin_repository_registry(),
        };
    enrich_from_registries(&mut bibliography, venue_registry, repository_registry);
    let validation =
        bibmgr_validation::validate(&syntax, &bibliography, &options.validation_policy);

    // The validation engine deliberately includes syntax and semantic diagnostics
    // so policy-specific blocking is applied exactly once.
    let mut diagnostics = validation.diagnostics;
    normalize_diagnostics(&mut diagnostics);

    let mut available_fixes = validation.fixes;
    available_fixes.sort_by(|left, right| left.id.cmp(&right.id));

    AnalysisResult {
        schema_version: SCHEMA_VERSION.to_owned(),
        source_revision: SourceRevision::of(source),
        syntax: syntax.summary().clone(),
        bibliography,
        diagnostics,
        available_fixes,
    }
}

/// Build an atomic plan from fixes returned by [`analyze`].
pub fn plan_fixes(
    analysis: &AnalysisResult,
    selection: &FixSelection,
) -> Result<FixPlan, FixPlanError> {
    bibmgr_edit::plan_fixes(
        &analysis.source_revision,
        &analysis.available_fixes,
        selection,
    )
}

/// Source-preserving edit result including mandatory post-edit reanalysis.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ApplyFixResult {
    pub schema_version: String,
    pub source: String,
    pub source_revision: SourceRevision,
    pub applied_fix_ids: Vec<FixId>,
    pub diff: String,
    pub analysis: AnalysisResult,
}

/// Apply a plan and re-run the complete pipeline with default analysis options.
pub fn apply_fix_plan(source: &str, plan: &FixPlan) -> Result<ApplyFixResult, EditError> {
    apply_fix_plan_with_options(source, plan, &AnalysisOptions::default())
}

/// Apply a plan and re-run the complete pipeline with the caller's original options.
pub fn apply_fix_plan_with_options(
    source: &str,
    plan: &FixPlan,
    options: &AnalysisOptions,
) -> Result<ApplyFixResult, EditError> {
    let applied = bibmgr_edit::apply_fix_plan(source, plan)?;
    let analysis = analyze(&applied.source, options);
    Ok(ApplyFixResult {
        schema_version: SCHEMA_VERSION.to_owned(),
        source: applied.source,
        source_revision: applied.source_revision,
        applied_fix_ids: applied.applied_fix_ids,
        diff: applied.diff,
        analysis,
    })
}

/// Apply every currently available safe fix, reanalyzing between conflicting
/// batches until the source reaches a fixed point.
///
/// Some individually safe fixes necessarily overlap. For example, a field
/// ordering fix replaces a complete field block while a field-case fix edits a
/// token inside that block. Such fixes must never share one atomic plan. This
/// helper selects a deterministic non-conflicting batch, applies it, and then
/// plans the remaining fixes against the new source revision.
pub fn apply_safe_fixes(
    source: &str,
    options: &AnalysisOptions,
) -> Result<ApplyFixResult, ApplySafeFixesError> {
    const MAX_PASSES: usize = 128;

    let mut current_source = source.to_owned();
    let mut analysis = analyze(&current_source, options);
    let mut applied_fix_ids = Vec::new();

    for _ in 0..MAX_PASSES {
        let selected_ids = non_conflicting_safe_fix_ids(&analysis.available_fixes);
        if selected_ids.is_empty() {
            return Ok(ApplyFixResult {
                schema_version: SCHEMA_VERSION.to_owned(),
                source_revision: analysis.source_revision.clone(),
                diff: bibmgr_edit::unified_diff(source, &current_source),
                source: current_source,
                applied_fix_ids,
                analysis,
            });
        }

        let plan = plan_fixes(&analysis, &FixSelection::Ids(selected_ids))?;
        let applied = bibmgr_edit::apply_fix_plan(&current_source, &plan)?;
        if applied.source == current_source {
            return Err(ApplySafeFixesError::NoProgress);
        }
        applied_fix_ids.extend(applied.applied_fix_ids);
        current_source = applied.source;
        analysis = analyze(&current_source, options);
    }

    Err(ApplySafeFixesError::PassLimit { passes: MAX_PASSES })
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum ApplySafeFixesError {
    #[error(transparent)]
    FixPlan(#[from] FixPlanError),
    #[error(transparent)]
    Edit(#[from] EditError),
    #[error("a safe fix produced no source change")]
    NoProgress,
    #[error("safe fixes did not converge after {passes} passes")]
    PassLimit { passes: usize },
}

fn non_conflicting_safe_fix_ids(fixes: &[Fix]) -> Vec<FixId> {
    let mut safe = fixes
        .iter()
        .filter(|fix| fix.applicability == FixApplicability::Safe)
        .collect::<Vec<_>>();
    safe.sort_by(|left, right| left.id.cmp(&right.id));

    let mut selected = Vec::<Fix>::new();
    for fix in safe {
        let mut candidate = selected.clone();
        candidate.push(fix.clone());
        if bibmgr_edit::detect_conflicts(&candidate).is_empty() {
            selected.push(fix.clone());
        }
    }
    selected.into_iter().map(|fix| fix.id).collect()
}

/// Registration decision produced by the same analyzer used for linting.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RegistrationValidation {
    pub schema_version: String,
    pub accepted: bool,
    pub source: String,
    pub source_revision: SourceRevision,
    pub diagnostics: Vec<Diagnostic>,
    pub bibliography: Bibliography,
    pub applied_fix_ids: Vec<FixId>,
    pub unresolved_semantics: bool,
}

/// Validate a document for registration under a named policy.
pub fn validate_for_registration(
    source: &str,
    policy: &RegistrationPolicy,
) -> RegistrationValidation {
    let validation_policy = match policy
        .validate_configuration()
        .and_then(|()| ValidationPolicy::for_profile(&policy.validation_profile))
    {
        Ok(policy) => policy,
        Err(error) => return registration_configuration_failure(source, &error.to_string()),
    };
    let options = AnalysisOptions {
        parse_mode: ParseMode::Strict,
        validation_policy,
        ..AnalysisOptions::default()
    };
    validate_for_registration_with_options(source, policy, &options)
}

/// Produce the information-preserving source representation stored by the
/// reference library.
///
/// Registration validation remains a read-only decision. Storage
/// canonicalization is an explicit second operation that applies only fixes
/// classified as safe, revalidates the result, and refuses any rewrite that
/// changes the document's entry/field inventory.
pub fn canonicalize_for_storage(
    source: &str,
    policy: &RegistrationPolicy,
) -> RegistrationValidation {
    let mut validation_policy = policy.clone();
    validation_policy.apply_safe_fixes = false;
    let initial = validate_for_registration(source, &validation_policy);
    if !initial.accepted {
        return initial;
    }

    let original_inventory = storage_inventory(source);
    let mut canonicalization_policy = policy.clone();
    canonicalization_policy.apply_safe_fixes = true;
    let mut canonicalized = validate_for_registration(source, &canonicalization_policy);

    if canonicalized.accepted
        && original_inventory != storage_inventory(canonicalized.source.as_str())
    {
        canonicalized.accepted = false;
        canonicalized.diagnostics.push(Diagnostic::new(
            "storage:BIB-STORAGE-001:0",
            RuleCode::new("BIB-STORAGE-001"),
            bibmgr_model::Severity::Error,
            true,
            "storage canonicalization would change the document's bibliographic field inventory",
            None,
        ));
        normalize_diagnostics(&mut canonicalized.diagnostics);
    }

    canonicalized
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct StorageInventory {
    entries: Vec<(String, Vec<String>, usize)>,
    strings: Vec<String>,
    preambles: usize,
    comments: usize,
}

fn storage_inventory(source: &str) -> StorageInventory {
    let document = bibmgr_syntax::parse(source, ParseOptions::strict());
    let entries = document
        .entries()
        .iter()
        .map(|entry| {
            let mut fields = entry
                .fields
                .iter()
                .map(|field| field.name.text.to_ascii_lowercase())
                .collect::<Vec<_>>();
            fields.sort();
            (
                entry.entry_type.text.to_ascii_lowercase(),
                fields,
                entry.inline_comments.len(),
            )
        })
        .collect();
    let mut strings = document
        .strings()
        .iter()
        .map(|definition| definition.name.text.to_ascii_lowercase())
        .collect::<Vec<_>>();
    strings.sort();

    StorageInventory {
        entries,
        strings,
        preambles: document.preambles().len(),
        comments: document.comments().len(),
    }
}

/// Validate registration with an externally loaded validation policy and
/// optional registry snapshots. Registration always forces strict parsing.
pub fn validate_for_registration_with_options(
    source: &str,
    policy: &RegistrationPolicy,
    options: &AnalysisOptions,
) -> RegistrationValidation {
    if let Err(error) = policy.validate_configuration() {
        return registration_configuration_failure(source, &error.to_string());
    }
    if let Err(error) = options.validation_policy.validate_configuration() {
        return registration_configuration_failure(source, &error.to_string());
    }
    let registration_profile = policy.validation_profile.as_str();
    let analysis_profile = options.validation_policy.profile.as_str();
    if registration_profile != analysis_profile
        && !(registration_profile == "default" && analysis_profile == "modern")
    {
        return registration_configuration_failure(
            source,
            &format!(
                "registration profile `{registration_profile}` does not match analysis profile `{analysis_profile}`"
            ),
        );
    }

    let mut options = options.clone();
    options.parse_mode = ParseMode::Strict;
    let initial = analyze(source, &options);

    let (effective_source, applied_fix_ids, analysis) = if policy.apply_safe_fixes {
        match apply_safe_fixes(source, &options) {
            Ok(applied) => (applied.source, applied.applied_fix_ids, applied.analysis),
            Err(error) => {
                let mut analysis = initial;
                analysis.diagnostics.push(Diagnostic::new(
                    "edit:BIB-EDIT-001:0",
                    RuleCode::new("BIB-EDIT-001"),
                    bibmgr_model::Severity::Error,
                    true,
                    format!("safe fixes could not be applied: {error}"),
                    None,
                ));
                normalize_diagnostics(&mut analysis.diagnostics);
                (source.to_owned(), Vec::new(), analysis)
            }
        }
    } else {
        (source.to_owned(), Vec::new(), initial)
    };

    let mut analysis = analysis;
    bibmgr_validation::apply_registration_blocking(&mut analysis.diagnostics, policy);
    let unresolved_semantics = analysis.bibliography.has_unresolved_semantics();
    let accepted = bibmgr_validation::registration_allowed(
        &analysis.diagnostics,
        &analysis.bibliography,
        policy,
    );
    RegistrationValidation {
        schema_version: SCHEMA_VERSION.to_owned(),
        accepted,
        source_revision: SourceRevision::of(&effective_source),
        source: effective_source,
        diagnostics: analysis.diagnostics,
        bibliography: analysis.bibliography,
        applied_fix_ids,
        unresolved_semantics,
    }
}

fn registration_configuration_failure(source: &str, message: &str) -> RegistrationValidation {
    let options = AnalysisOptions {
        parse_mode: ParseMode::Strict,
        ..AnalysisOptions::default()
    };
    let mut analysis = analyze(source, &options);
    analysis.diagnostics.push(Diagnostic::new(
        "configuration:BIB-CONFIG-001:0",
        RuleCode::new("BIB-CONFIG-001"),
        bibmgr_model::Severity::Error,
        true,
        message,
        None,
    ));
    normalize_diagnostics(&mut analysis.diagnostics);
    let unresolved_semantics = analysis.bibliography.has_unresolved_semantics();
    RegistrationValidation {
        schema_version: SCHEMA_VERSION.to_owned(),
        accepted: false,
        source: source.to_owned(),
        source_revision: SourceRevision::of(source),
        diagnostics: analysis.diagnostics,
        bibliography: analysis.bibliography,
        applied_fix_ids: Vec::new(),
        unresolved_semantics,
    }
}

/// Public metadata for one canonical built-in export profile.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ExportProfileSummary {
    pub id: ProfileId,
    pub display_name: String,
    pub description: String,
    pub validation_profile: ProfileId,
    pub preprint_representation: PreprintRepresentation,
}

/// Versioned catalog used by adapters to present the available export targets.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ExportProfileCatalog {
    pub schema_version: String,
    pub profiles: Vec<ExportProfileSummary>,
}

/// Return the canonical built-in export profiles in their stable presentation order.
pub fn export_profiles() -> Result<ExportProfileCatalog, ExportError> {
    let profiles = ExportProfile::builtins()?
        .into_iter()
        .map(|profile| ExportProfileSummary {
            id: profile.profile,
            display_name: profile.display_name,
            description: profile.description,
            validation_profile: profile.validation_profile,
            preprint_representation: profile.preprint_representation,
        })
        .collect();
    Ok(ExportProfileCatalog {
        schema_version: SCHEMA_VERSION.to_owned(),
        profiles,
    })
}

/// Analyze strictly and serialize the semantic records using an export profile.
pub fn export_source(source: &str, profile: &ExportProfile) -> Result<ExportResult, ExportError> {
    let options = AnalysisOptions {
        parse_mode: ParseMode::Strict,
        ..AnalysisOptions::default()
    };
    let analysis = analyze(source, &options);
    let mut blocking_codes = analysis
        .diagnostics
        .iter()
        .filter(|diagnostic| diagnostic.blocking)
        .map(|diagnostic| diagnostic.code.clone())
        .collect::<Vec<_>>();
    blocking_codes.sort();
    blocking_codes.dedup();
    if !blocking_codes.is_empty() {
        return Err(ExportError::BlockingDiagnostics(blocking_codes));
    }
    let exported = bibmgr_export::export(&analysis.bibliography, profile)?;

    // Validate the generated representation, not the input spelling, against
    // the export profile's explicit target policy. This lets profiles
    // intentionally transform e.g. eprint input into classical `howpublished`
    // while still rejecting output that violates target blocking rules.
    let validation_policy =
        ValidationPolicy::for_profile(&profile.validation_profile).map_err(|error| {
            ExportError::InvalidProfile(format!(
                "target validation profile `{}` is unavailable: {error}",
                profile.validation_profile
            ))
        })?;
    let target = analyze(
        &exported.source,
        &AnalysisOptions {
            parse_mode: ParseMode::Strict,
            validation_policy,
            ..AnalysisOptions::default()
        },
    );
    let mut target_blocking_codes = target
        .diagnostics
        .iter()
        .filter(|diagnostic| diagnostic.blocking)
        .map(|diagnostic| diagnostic.code.clone())
        .collect::<Vec<_>>();
    target_blocking_codes.sort();
    target_blocking_codes.dedup();
    if !target_blocking_codes.is_empty() {
        return Err(ExportError::BlockingDiagnostics(target_blocking_codes));
    }

    Ok(exported)
}

/// Incremental-ready document API. The current implementation reparses in full.
#[derive(Debug, Clone)]
pub struct DocumentSession {
    source: String,
    options: AnalysisOptions,
    analysis: AnalysisResult,
}

impl DocumentSession {
    pub fn open(source: String, options: AnalysisOptions) -> Self {
        let analysis = analyze(&source, &options);
        Self {
            source,
            options,
            analysis,
        }
    }

    pub const fn analysis(&self) -> &AnalysisResult {
        &self.analysis
    }

    pub fn source(&self) -> &str {
        &self.source
    }

    pub fn update(
        &mut self,
        revision: SourceRevision,
        edit: TextEdit,
    ) -> Result<AnalysisDelta, SessionError> {
        if revision != self.analysis.source_revision {
            return Err(SessionError::StaleRevision {
                expected: self.analysis.source_revision.clone(),
                actual: revision,
            });
        }
        let plan = FixPlan {
            source_revision: revision,
            fixes: Vec::new(),
            edits: vec![edit],
        };
        let applied = bibmgr_edit::apply_fix_plan(&self.source, &plan)?;
        let previous = self.analysis.clone();
        let next = analyze(&applied.source, &self.options);
        let delta = AnalysisDelta::between(&previous, &next);
        self.source = applied.source;
        self.analysis = next;
        Ok(delta)
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AnalysisDelta {
    pub schema_version: String,
    pub previous_revision: SourceRevision,
    pub source_revision: SourceRevision,
    pub added_diagnostics: Vec<Diagnostic>,
    pub removed_diagnostic_ids: Vec<DiagnosticId>,
    pub analysis: AnalysisResult,
}

impl AnalysisDelta {
    fn between(previous: &AnalysisResult, next: &AnalysisResult) -> Self {
        let previous_ids: BTreeSet<_> = previous
            .diagnostics
            .iter()
            .map(|diagnostic| diagnostic.id.clone())
            .collect();
        let next_ids: BTreeSet<_> = next
            .diagnostics
            .iter()
            .map(|diagnostic| diagnostic.id.clone())
            .collect();
        let added_diagnostics = next
            .diagnostics
            .iter()
            .filter(|diagnostic| !previous_ids.contains(&diagnostic.id))
            .cloned()
            .collect();
        let removed_diagnostic_ids = previous_ids.difference(&next_ids).cloned().collect();
        Self {
            schema_version: SCHEMA_VERSION.to_owned(),
            previous_revision: previous.source_revision.clone(),
            source_revision: next.source_revision.clone(),
            added_diagnostics,
            removed_diagnostic_ids,
            analysis: next.clone(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum SessionError {
    #[error("session revision is stale: expected {expected}, got {actual}")]
    StaleRevision {
        expected: SourceRevision,
        actual: SourceRevision,
    },
    #[error(transparent)]
    Edit(#[from] EditError),
}

/// Typed umbrella error for consumers that prefer one error channel.
#[derive(Debug, thiserror::Error)]
pub enum BibmgrError {
    #[error("parse failed: {0}")]
    Parse(String),
    #[error("semantic analysis failed: {0}")]
    Semantic(String),
    #[error("validation failed: {0}")]
    Validation(String),
    #[error(transparent)]
    FixPlan(#[from] FixPlanError),
    #[error(transparent)]
    Edit(#[from] EditError),
    #[error(transparent)]
    Export(#[from] ExportError),
    #[error("configuration failed: {0}")]
    Configuration(String),
}

fn normalize_diagnostics(diagnostics: &mut Vec<Diagnostic>) {
    diagnostics.sort_by(|left, right| left.sort_key().cmp(&right.sort_key()));
    diagnostics.dedup_by(|left, right| left.id == right.id);
}

fn enrich_from_builtin_registries(bibliography: &mut Bibliography) {
    enrich_from_registries(
        bibliography,
        builtin_venue_registry(),
        builtin_repository_registry(),
    );
}

fn builtin_venue_registry() -> Option<&'static VenueRegistry> {
    static VENUES: OnceLock<Option<VenueRegistry>> = OnceLock::new();
    VENUES
        .get_or_init(|| VenueRegistry::builtin().ok())
        .as_ref()
}

fn builtin_repository_registry() -> Option<&'static RepositoryRegistry> {
    static REPOSITORIES: OnceLock<Option<RepositoryRegistry>> = OnceLock::new();
    REPOSITORIES
        .get_or_init(|| RepositoryRegistry::builtin().ok())
        .as_ref()
}

fn enrich_from_registries(
    bibliography: &mut Bibliography,
    venues: Option<&VenueRegistry>,
    repositories: Option<&RepositoryRegistry>,
) {
    if let Some(venues) = venues {
        for record in &mut bibliography.records {
            let Some(venue) = &mut record.venue else {
                continue;
            };
            let Some(entity) = venues.resolve(&venue.value.raw) else {
                continue;
            };
            venue.value.venue_id = Some(entity.id.clone());
            venue.value.full_name = Some(entity.full_name.clone());
            venue.value.short_name = Some(entity.short_name.clone());
            venue.value.kind = Some(entity.kind);
            venue.status = bibmgr_semantics::ValueStatus::Resolved;
            venue.confidence = bibmgr_semantics::Confidence::High;
        }
    }

    if let Some(repositories) = repositories {
        for record in &mut bibliography.records {
            let Some(preprint) = &mut record.preprint else {
                continue;
            };
            let bibmgr_semantics::Repository::Other(name) = &mut preprint.value.repository else {
                continue;
            };
            let Some(entity) = repositories.resolve(name) else {
                continue;
            };
            if !entity.accepts_identifier(&preprint.value.identifier) {
                continue;
            }
            *name = entity.archive_prefix.clone();
            preprint.status = bibmgr_semantics::ValueStatus::Resolved;
            preprint.confidence = bibmgr_semantics::Confidence::High;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn export_profile_catalog_contains_only_canonical_builtins() {
        let catalog = export_profiles().unwrap();
        let ids = catalog
            .profiles
            .iter()
            .map(|profile| profile.id.as_str())
            .collect::<Vec<_>>();

        assert_eq!(catalog.schema_version, SCHEMA_VERSION);
        assert_eq!(ids, bibmgr_export::BUILTIN_EXPORT_PROFILE_IDS);
        assert!(!ids.contains(&"default"));
        assert!(!ids.contains(&"article-journal"));

        for summary in &catalog.profiles {
            let profile = ExportProfile::for_profile(&summary.id).unwrap();
            assert_eq!(summary.display_name, profile.display_name);
            assert_eq!(summary.description, profile.description);
            assert_eq!(summary.validation_profile, profile.validation_profile);
            assert_eq!(
                summary.preprint_representation,
                profile.preprint_representation
            );
        }
    }

    #[test]
    fn export_profile_catalog_has_the_public_json_shape() {
        let value = serde_json::to_value(export_profiles().unwrap()).unwrap();
        let first = &value["profiles"][0];

        assert_eq!(value["schema_version"], "1");
        assert_eq!(first["id"], "modern");
        assert!(first["display_name"]
            .as_str()
            .is_some_and(|name| !name.is_empty()));
        assert!(first["description"]
            .as_str()
            .is_some_and(|description| !description.is_empty()));
        assert_eq!(first["validation_profile"], "modern");
        assert_eq!(first["preprint_representation"], "misc-eprint");
    }

    #[test]
    fn artifact_profiles_export_bst_native_entry_types_through_target_validation() {
        let cases = [
            (
                "lrec",
                "@languageresource{probe, author={Doe, Jane}, title={Corpus}, year={2026}, islrn={42-123-456-789-0}, pid={lrec_123},}\n",
                "@languageresource{probe,",
                "islrn = {42-123-456-789-0}",
            ),
            (
                "ieee-publications",
                "@patent{probe, author={Doe, Jane}, nationality={Japanese}, number={12345}, title={Widget}, year={2026},}\n",
                "@patent{probe,",
                "nationality = {Japanese}",
            ),
        ];

        for (profile_id, source, entry, field) in cases {
            let profile = ExportProfile::builtin(profile_id).unwrap();
            let output = export_source(source, &profile).unwrap().source;
            assert!(
                output.starts_with(entry),
                "profile `{profile_id}`: {output}"
            );
            assert!(output.contains(field), "profile `{profile_id}`: {output}");
        }
    }

    #[test]
    fn session_rejects_stale_edits_and_returns_deltas() {
        let source = "@article{key, title={Title}, year={2026}}".to_owned();
        let mut session = DocumentSession::open(source.clone(), AnalysisOptions::default());
        let stale = SourceRevision::of("other");
        assert!(matches!(
            session.update(
                stale,
                TextEdit {
                    range: bibmgr_model::TextRange::new(0, 0),
                    replacement: "% ".to_owned(),
                }
            ),
            Err(SessionError::StaleRevision { .. })
        ));

        let revision = SourceRevision::of(&source);
        let delta = session
            .update(
                revision,
                TextEdit {
                    range: bibmgr_model::TextRange::new(0, 0),
                    replacement: "% comment\n".to_owned(),
                },
            )
            .unwrap();
        assert_eq!(delta.source_revision, SourceRevision::of(session.source()));
    }

    #[test]
    fn bulk_safe_fixes_reanalyze_between_overlapping_batches() {
        let source = "@article{k, year={2024}, TITLE=\"T\", author={Doe, Jane}, journal={J},}\n";
        let options = AnalysisOptions {
            validation_policy: ValidationPolicy::for_profile(&ProfileId::new("laboratory"))
                .unwrap(),
            ..AnalysisOptions::default()
        };

        let applied = apply_safe_fixes(source, &options).unwrap();

        assert!(applied.source.contains("title = {T}"));
        assert!(applied.source.find("title =").unwrap() < applied.source.find("author =").unwrap());
        assert!(applied
            .analysis
            .available_fixes
            .iter()
            .all(|fix| fix.applicability != FixApplicability::Safe));

        let repeated = apply_safe_fixes(&applied.source, &options).unwrap();
        assert_eq!(repeated.source, applied.source);
        assert!(repeated.applied_fix_ids.is_empty());
        assert!(repeated.diff.is_empty());
    }

    #[test]
    fn builtin_venue_registry_enriches_analysis_and_drives_export_style() {
        let source =
            "@inproceedings{k, author={Doe, Jane}, title={T}, booktitle={ACL}, year={2024},}\n";
        let analysis = analyze(source, &AnalysisOptions::default());
        let venue = analysis.bibliography.records[0].venue.as_ref().unwrap();
        assert_eq!(venue.value.venue_id.as_deref(), Some("acl-annual-meeting"));
        assert_eq!(venue.value.short_name.as_deref(), Some("ACL"));
        assert_eq!(
            venue.value.kind,
            Some(bibmgr_semantics::VenueKind::Conference)
        );

        let full = export_source(source, &ExportProfile::laboratory())
            .unwrap()
            .source;
        assert!(full.contains(
            "booktitle = {Annual Meeting of the Association for Computational Linguistics}"
        ));

        let mut short_profile = ExportProfile::modern();
        short_profile.venue_style = VenueStyle::Short;
        let short = export_source(source, &short_profile).unwrap().source;
        assert!(short.contains("booktitle = {ACL}"));
    }

    #[test]
    fn laboratory_export_case_protects_the_complete_title() {
        let source = "@article{k, author={Doe, Jane}, title={An LLM Study}, journal={Journal}, year={2026},}\n";

        let laboratory = export_source(source, &ExportProfile::laboratory())
            .unwrap()
            .source;
        let modern = export_source(source, &ExportProfile::modern())
            .unwrap()
            .source;

        assert!(laboratory.contains("title = {{An LLM Study}}"));
        assert!(modern.contains("title = {An LLM Study}"));
        assert_eq!(
            export_source(&laboratory, &ExportProfile::laboratory())
                .unwrap()
                .source,
            laboratory
        );
    }

    #[test]
    fn resolved_venue_kind_reports_entry_type_mismatches_with_confirmed_fixes() {
        for (source, expected_kind, expected_type, venue_source) in [
            (
                "@article{k, author={Doe, Jane}, title={T}, journal={ACL}, year={2024},}\n",
                bibmgr_semantics::VenueKind::Conference,
                "inproceedings",
                "{ACL}",
            ),
            (
                "@inproceedings{k, author={Doe, Jane}, title={T}, booktitle={TACL}, year={2024},}\n",
                bibmgr_semantics::VenueKind::Journal,
                "article",
                "{TACL}",
            ),
        ] {
            let analysis = analyze(source, &AnalysisOptions::default());
            let venue = analysis.bibliography.records[0].venue.as_ref().unwrap();
            assert_eq!(venue.value.kind, Some(expected_kind));

            let diagnostic = analysis
                .diagnostics
                .iter()
                .find(|diagnostic| diagnostic.code.as_str() == "BIB-SEMANTIC-004")
                .unwrap();
            let related = &diagnostic.related_locations[0].location;
            assert_eq!(
                &source[related.range.start as usize..related.range.end as usize],
                venue_source
            );

            let fix = analysis
                .available_fixes
                .iter()
                .find(|fix| diagnostic.fixes.contains(&fix.id))
                .unwrap();
            assert_eq!(fix.applicability, FixApplicability::RequiresConfirmation);
            assert_eq!(fix.edits[0].replacement, expected_type);

            let plan = plan_fixes(
                &analysis,
                &FixSelection::Ids(vec![fix.id.clone()]),
            )
            .unwrap();
            let applied = apply_fix_plan(source, &plan).unwrap();
            assert!(!applied
                .analysis
                .diagnostics
                .iter()
                .any(|diagnostic| diagnostic.code.as_str() == "BIB-SEMANTIC-004"));
        }
    }

    #[test]
    fn builtin_repository_registry_canonicalizes_aliases_for_export() {
        let source =
            "@misc{k, title={T}, eprint={10.1101/123456}, archivePrefix={bioRxiv preprint},}\n";
        let analysis = analyze(source, &AnalysisOptions::default());
        let preprint = analysis.bibliography.records[0].preprint.as_ref().unwrap();
        assert_eq!(
            preprint.value.repository,
            bibmgr_semantics::Repository::Other(String::from("bioRxiv"))
        );
        assert_eq!(preprint.status, bibmgr_semantics::ValueStatus::Resolved);

        let exported = export_source(source, &ExportProfile::modern()).unwrap();
        assert!(exported.source.contains("archivePrefix = {bioRxiv}"));

        let inspected = inspect_ast(source, ParseOptions::tolerant());
        let inspected_preprint = inspected.bibliography.records[0].preprint.as_ref().unwrap();
        assert_eq!(
            inspected_preprint.value.repository,
            bibmgr_semantics::Repository::Other(String::from("bioRxiv"))
        );
    }

    #[test]
    fn analysis_accepts_external_registry_snapshots_without_adapter_rules() {
        let venues = VenueRegistry::from_toml(
            r#"
schema_version = "1"

[[venues]]
id = "custom-symposium"
full_name = "Custom Symposium on Parsing"
short_name = "CSP"
aliases = ["Parsing Symposium"]
kind = "conference"
"#,
        )
        .unwrap();
        let source = "@inproceedings{k, title={T}, booktitle={Parsing Symposium}, year={2024},}\n";
        let analysis = analyze(
            source,
            &AnalysisOptions {
                venue_registry: Some(venues),
                ..AnalysisOptions::default()
            },
        );

        let venue = analysis.bibliography.records[0].venue.as_ref().unwrap();
        assert_eq!(venue.value.venue_id.as_deref(), Some("custom-symposium"));
        assert_eq!(venue.value.short_name.as_deref(), Some("CSP"));

        let disabled = analyze(
            source,
            &AnalysisOptions {
                venue_registry: Some(VenueRegistry {
                    schema_version: SCHEMA_VERSION.to_owned(),
                    venues: Vec::new(),
                }),
                ..AnalysisOptions::default()
            },
        );
        assert_eq!(
            disabled.bibliography.records[0]
                .venue
                .as_ref()
                .unwrap()
                .value
                .venue_id,
            None
        );
    }

    #[test]
    fn export_rejects_ambiguous_semantics_even_when_lint_policy_only_warns() {
        let source = "@misc{k, title={T}, eprint={10.1101/123456}, archivePrefix={bioRxiv}, eprintType={medRxiv},}\n";

        assert!(matches!(
            export_source(source, &ExportProfile::modern()),
            Err(ExportError::AmbiguousSemantics {
                record_index: 0,
                ..
            })
        ));

        let macro_source = "@string{x={One}}\n@string{x={Two}}\n@misc{k, title=x,}\n";
        assert!(matches!(
            export_source(macro_source, &ExportProfile::modern()),
            Err(ExportError::AmbiguousSemantics {
                record_index: 0,
                ..
            })
        ));
    }

    #[test]
    fn export_validates_the_generated_document_against_the_target_profile() {
        let incomplete = "@article{k, title={T}, journal={J}, year={2024},}\n";
        assert!(matches!(
            export_source(incomplete, &ExportProfile::laboratory()),
            Err(ExportError::BlockingDiagnostics(ref codes))
                if codes.iter().any(|code| code.as_str() == "LAB-ENTRY-003")
        ));

        let preprint = "@misc{k, author={Doe, Jane}, title={T}, eprint={2401.01234}, archivePrefix={arXiv}, year={2024},}\n";
        let exported = export_source(preprint, &ExportProfile::classical_bst()).unwrap();
        assert!(exported
            .source
            .contains("howpublished = {arXiv:2401.01234}"));
        assert!(!exported.source.contains("eprint ="));
        assert!(!exported.source.contains("url ="));

        let mut custom = ExportProfile::modern();
        custom.profile = ProfileId::new("custom-output");
        custom.validation_profile = ProfileId::new("missing-policy");
        assert!(matches!(
            export_source(preprint, &custom),
            Err(ExportError::InvalidProfile(message))
                if message.contains("missing-policy")
        ));
    }

    #[test]
    fn registration_returns_registration_specific_blocking_flags() {
        let source = "@misc{key, TITLE = {T},}\n";
        let policy = RegistrationPolicy {
            validation_profile: ProfileId::new("modern"),
            minimum_severity: Some(Severity::Warning),
            ..RegistrationPolicy::default()
        };

        let result = validate_for_registration(source, &policy);

        assert!(!result.accepted);
        assert!(result.diagnostics.iter().any(|diagnostic| {
            diagnostic.code.as_str() == "BIB-SYNTAX-002" && diagnostic.blocking
        }));

        let mut invalid_policy = RegistrationPolicy::default();
        invalid_policy
            .blocking_rules
            .include
            .insert(RuleCode::new("NOT-A-RULE"));
        let invalid = validate_for_registration(source, &invalid_policy);
        assert!(!invalid.accepted);
        assert!(invalid
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code.as_str() == "BIB-CONFIG-001"));
    }

    #[test]
    fn strict_registration_rejects_unresolved_sourced_values() {
        let source =
            "@article{key, title = {T}, author = {Doe, Jane}, journal = {J}, year = {twenty},}\n";
        let policy = RegistrationPolicy {
            validation_profile: ProfileId::new("modern"),
            minimum_severity: None,
            allow_unresolved_semantics: false,
            ..RegistrationPolicy::default()
        };

        let result = validate_for_registration(source, &policy);

        assert!(!result.accepted);
        assert!(result.unresolved_semantics);
        assert_eq!(
            result.bibliography.records[0].date.as_ref().unwrap().status,
            bibmgr_semantics::ValueStatus::Unresolved
        );
    }

    #[test]
    fn archive_registration_preserves_rich_sources_without_profile_gating() {
        let source = "@inproceedings{Gong_2023,\n  title = {{D}iffu{S}eq-v2},\n  year = unknownYear,\n  archivePrefix = {arXiv},\n  primaryClass = {cs.CL},\n  url = {https://example.test/paper},\n  abstract = {A long abstract\n    kept across lines.},\n}\n";

        let result = validate_for_registration(source, &RegistrationPolicy::archive());

        assert!(result.accepted);
        assert_eq!(result.source, source);
        assert_eq!(result.bibliography.records.len(), 1);
        assert!(result.unresolved_semantics);
        assert!(result
            .diagnostics
            .iter()
            .all(|diagnostic| !diagnostic.blocking));
        assert!(result.applied_fix_ids.is_empty());
    }

    #[test]
    fn archive_registration_still_rejects_structurally_invalid_bibtex() {
        let source = "@misc{key, title={Unclosed}\n";

        let result = validate_for_registration(source, &RegistrationPolicy::archive());

        assert!(!result.accepted);
        assert!(result
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.blocking));
    }

    #[test]
    fn registration_accepts_an_external_validated_policy_snapshot() {
        let source = "@article{key, title={T}, author={Doe, Jane}, journal={J}, year={2024},}\n";
        let mut validation_policy = ValidationPolicy::modern();
        validation_policy.profile = ProfileId::new("external-policy");
        let registration_policy = RegistrationPolicy {
            validation_profile: ProfileId::new("external-policy"),
            minimum_severity: None,
            ..RegistrationPolicy::default()
        };

        let result = validate_for_registration_with_options(
            source,
            &registration_policy,
            &AnalysisOptions {
                parse_mode: ParseMode::Tolerant,
                validation_policy,
                ..AnalysisOptions::default()
            },
        );

        assert!(result.accepted);
        assert!(!result
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code.as_str() == "BIB-CONFIG-001"));
    }

    #[test]
    fn storage_canonicalization_applies_safe_laboratory_style_without_losing_url() {
        let source = "@misc{smith-2024, author={Smith, Jane}, Title={T}, year={2024}, eprint={2401.01234}, archiveprefix={arXiv}, primaryclass={cs.CL}, URL={https://example.test/paper}}\n";

        let result = canonicalize_for_storage(source, &RegistrationPolicy::laboratory());

        assert!(result.accepted);
        assert_ne!(result.source, source);
        assert!(result.source.contains("title = {T}"));
        assert!(result.source.contains("archivePrefix = {arXiv}"));
        assert!(result.source.contains("primaryClass = {cs.CL}"));
        assert!(result.source.contains("url = {https://example.test/paper}"));
        assert!(!result.applied_fix_ids.is_empty());

        let repeated = canonicalize_for_storage(&result.source, &RegistrationPolicy::laboratory());
        assert!(repeated.accepted);
        assert_eq!(repeated.source, result.source);
        assert!(repeated.applied_fix_ids.is_empty());
    }

    #[test]
    fn storage_canonicalization_normalizes_value_lines_without_changing_title_groups() {
        let source = concat!(
            "@inproceedings{gong-etal-2023-diffuseq,\n",
            "  title = {{D}iffu{S}eq-v2: Bridging Text Spaces},\n",
            "  author = {Gong, Shansan and\n",
            "    Li, Mukai},\n",
            "  booktitle = {Findings of ACL},\n",
            "  year = {2023},\n",
            "  abstract = {First sentence.\n",
            "    Second sentence.},\n",
            "}\n",
        );

        let result = canonicalize_for_storage(source, &RegistrationPolicy::laboratory());

        assert!(
            result.accepted,
            "unexpected diagnostics: {:?}",
            result.diagnostics
        );
        assert!(result
            .source
            .contains("title = {{D}iffu{S}eq-v2: Bridging Text Spaces}"));
        assert!(result
            .source
            .contains("author = {Gong, Shansan and Li, Mukai}"));
        assert!(result
            .source
            .contains("abstract = {First sentence. Second sentence.}"));
    }

    #[test]
    fn storage_inventory_detects_field_or_comment_loss() {
        let complete = "% retained\n@misc{k, title={T}, url={https://example.test},}\n";
        let missing_url = "% retained\n@misc{k, title={T},}\n";
        let missing_comment = "@misc{k, title={T}, url={https://example.test},}\n";

        assert_ne!(storage_inventory(complete), storage_inventory(missing_url));
        assert_ne!(
            storage_inventory(complete),
            storage_inventory(missing_comment)
        );
    }
}
