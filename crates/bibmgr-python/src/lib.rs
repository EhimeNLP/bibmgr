//! Thin Python DTO and exception adapter over [`bibmgr_core`].

use bibmgr_core::{
    AnalysisOptions, DocumentSession as CoreDocumentSession, ExportProfile, FixId, FixSelection,
    ParseMode, ProfileId, RegistrationPolicy, SourceRevision, TextEdit, TextRange,
    ValidationPolicy, SCHEMA_VERSION,
};
use pyo3::create_exception;
use pyo3::exceptions::PyException;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyModule};
use serde::Serialize;
use serde_json::Value;

create_exception!(bibmgr_native, BibmgrError, PyException);
create_exception!(bibmgr_native, ParseError, BibmgrError);
create_exception!(bibmgr_native, ValidationError, BibmgrError);
create_exception!(bibmgr_native, EditConflictError, BibmgrError);
create_exception!(bibmgr_native, ExportError, BibmgrError);
create_exception!(bibmgr_native, ConfigurationError, BibmgrError);

macro_rules! json_dto {
    ($rust:ident, $python:literal) => {
        #[pyclass(name = $python, module = "bibmgr_native", frozen, skip_from_py_object)]
        #[derive(Debug, Clone)]
        pub struct $rust {
            value: Value,
        }

        impl $rust {
            #[allow(dead_code)]
            fn from_serializable(value: &impl Serialize) -> PyResult<Self> {
                Ok(Self {
                    value: serde_json::to_value(value).map_err(json_error)?,
                })
            }
        }
    };
}

json_dto!(PyDiagnostic, "Diagnostic");
json_dto!(PyRelatedLocation, "RelatedLocation");
json_dto!(PyFix, "Fix");
json_dto!(PyBibliographicRecord, "BibliographicRecord");
json_dto!(PyAnalysisResult, "AnalysisResult");
json_dto!(PyApplyFixResult, "ApplyFixResult");
json_dto!(PyRegistrationValidation, "RegistrationValidation");
json_dto!(PyExportResult, "ExportResult");
json_dto!(PyExportProfileCatalog, "ExportProfileCatalog");
json_dto!(PyAnalysisDelta, "AnalysisDelta");

#[pyclass(
    name = "TextEdit",
    module = "bibmgr_native",
    frozen,
    skip_from_py_object
)]
#[derive(Debug, Clone)]
pub struct PyTextEdit {
    #[pyo3(get)]
    pub start: u32,
    #[pyo3(get)]
    pub end: u32,
    #[pyo3(get)]
    pub replacement: String,
}

#[pymethods]
impl PyTextEdit {
    #[new]
    fn new(start: u32, end: u32, replacement: String) -> PyResult<Self> {
        if start > end {
            return Err(EditConflictError::new_err("edit start is after its end"));
        }
        Ok(Self {
            start,
            end,
            replacement,
        })
    }

    fn to_dict(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        value_to_dict(
            py,
            &serde_json::json!({
                "range": {"start": self.start, "end": self.end},
                "replacement": self.replacement,
            }),
        )
    }

    fn __repr__(&self) -> String {
        format!(
            "TextEdit({}..{}, {:?})",
            self.start, self.end, self.replacement
        )
    }
}

#[pymethods]
impl PyDiagnostic {
    #[getter]
    fn id(&self) -> String {
        string_at(&self.value, &["id"])
    }

    #[getter]
    fn code(&self) -> String {
        string_at(&self.value, &["code"])
    }

    #[getter]
    fn severity(&self) -> String {
        string_at(&self.value, &["severity"])
    }

    #[getter]
    fn blocking(&self) -> bool {
        self.value["blocking"].as_bool().unwrap_or(false)
    }

    #[getter]
    fn message(&self) -> String {
        string_at(&self.value, &["message"])
    }

    #[getter]
    fn range(&self) -> Option<(u32, u32)> {
        range_at(&self.value, &["primary_location", "range"])
    }

    #[getter]
    fn related_locations(&self) -> Vec<PyRelatedLocation> {
        array_at(&self.value, &["related_locations"])
            .into_iter()
            .map(|value| PyRelatedLocation { value })
            .collect()
    }

    #[getter]
    fn notes(&self) -> Vec<String> {
        strings_at(&self.value, &["notes"])
    }

    #[getter]
    fn fixes(&self) -> Vec<String> {
        strings_at(&self.value, &["fixes"])
    }

    fn to_dict(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        value_to_dict(py, &self.value)
    }

    fn __repr__(&self) -> String {
        format!("Diagnostic({:?}, {:?})", self.code(), self.message())
    }
}

#[pymethods]
impl PyRelatedLocation {
    #[getter]
    fn message(&self) -> String {
        string_at(&self.value, &["message"])
    }

    #[getter]
    fn range(&self) -> Option<(u32, u32)> {
        range_at(&self.value, &["location", "range"])
    }

    fn to_dict(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        value_to_dict(py, &self.value)
    }
}

#[pymethods]
impl PyFix {
    #[getter]
    fn id(&self) -> String {
        string_at(&self.value, &["id"])
    }

    #[getter]
    fn title(&self) -> String {
        string_at(&self.value, &["title"])
    }

    #[getter]
    fn applicability(&self) -> String {
        string_at(&self.value, &["applicability"])
    }

    #[getter]
    fn edits(&self) -> Vec<PyTextEdit> {
        array_at(&self.value, &["edits"])
            .into_iter()
            .filter_map(|value| {
                let (start, end) = range_at(&value, &["range"])?;
                Some(PyTextEdit {
                    start,
                    end,
                    replacement: string_at(&value, &["replacement"]),
                })
            })
            .collect()
    }

    fn to_dict(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        value_to_dict(py, &self.value)
    }

    fn __repr__(&self) -> String {
        format!("Fix({:?}, {:?})", self.id(), self.title())
    }
}

#[pymethods]
impl PyBibliographicRecord {
    #[getter]
    fn citation_key(&self) -> Option<String> {
        sourced_string_at(&self.value, &["citation_key"])
    }

    #[getter]
    fn entry_type(&self) -> Option<String> {
        sourced_string_at(&self.value, &["entry_type"])
    }

    #[getter]
    fn title(&self) -> Option<String> {
        sourced_string_at(&self.value, &["title"])
    }

    #[getter]
    fn work_type(&self) -> Option<String> {
        sourced_string_at(&self.value, &["work_type"])
    }

    fn to_dict(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        value_to_dict(py, &self.value)
    }

    fn __repr__(&self) -> String {
        format!("BibliographicRecord({:?})", self.citation_key())
    }
}

#[pymethods]
impl PyAnalysisResult {
    #[getter]
    fn schema_version(&self) -> String {
        string_at(&self.value, &["schema_version"])
    }

    #[getter]
    fn source_revision(&self) -> String {
        string_at(&self.value, &["source_revision"])
    }

    #[getter]
    fn diagnostics(&self) -> Vec<PyDiagnostic> {
        array_at(&self.value, &["diagnostics"])
            .into_iter()
            .map(|value| PyDiagnostic { value })
            .collect()
    }

    #[getter]
    fn available_fixes(&self) -> Vec<PyFix> {
        array_at(&self.value, &["available_fixes"])
            .into_iter()
            .map(|value| PyFix { value })
            .collect()
    }

    #[getter]
    fn records(&self) -> Vec<PyBibliographicRecord> {
        array_at(&self.value, &["bibliography", "records"])
            .into_iter()
            .map(|value| PyBibliographicRecord { value })
            .collect()
    }

    #[getter]
    fn syntax(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        value_to_dict(py, get_at(&self.value, &["syntax"]).unwrap_or(&Value::Null))
    }

    #[getter]
    fn bibliography(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        value_to_dict(
            py,
            get_at(&self.value, &["bibliography"]).unwrap_or(&Value::Null),
        )
    }

    fn to_dict(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        value_to_dict(py, &self.value)
    }

    fn to_json(&self) -> PyResult<String> {
        serde_json::to_string(&self.value).map_err(json_error)
    }

    fn __repr__(&self) -> String {
        format!(
            "AnalysisResult(diagnostics={}, fixes={})",
            self.diagnostics().len(),
            self.available_fixes().len()
        )
    }
}

#[pymethods]
impl PyApplyFixResult {
    #[getter]
    fn schema_version(&self) -> String {
        string_at(&self.value, &["schema_version"])
    }

    #[getter]
    fn source(&self) -> String {
        string_at(&self.value, &["source"])
    }

    #[getter]
    fn source_revision(&self) -> String {
        string_at(&self.value, &["source_revision"])
    }

    #[getter]
    fn applied_fix_ids(&self) -> Vec<String> {
        strings_at(&self.value, &["applied_fix_ids"])
    }

    #[getter]
    fn diff(&self) -> String {
        string_at(&self.value, &["diff"])
    }

    #[getter]
    fn analysis(&self) -> PyAnalysisResult {
        PyAnalysisResult {
            value: self.value["analysis"].clone(),
        }
    }

    #[getter]
    fn diagnostics(&self) -> Vec<PyDiagnostic> {
        array_at(&self.value, &["analysis", "diagnostics"])
            .into_iter()
            .map(|value| PyDiagnostic { value })
            .collect()
    }

    fn to_dict(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        value_to_dict(py, &self.value)
    }

    fn to_json(&self) -> PyResult<String> {
        serde_json::to_string(&self.value).map_err(json_error)
    }
}

#[pymethods]
impl PyRegistrationValidation {
    #[getter]
    fn schema_version(&self) -> String {
        string_at(&self.value, &["schema_version"])
    }

    #[getter]
    fn accepted(&self) -> bool {
        self.value["accepted"].as_bool().unwrap_or(false)
    }

    #[getter]
    fn unresolved_semantics(&self) -> bool {
        self.value["unresolved_semantics"]
            .as_bool()
            .unwrap_or(false)
    }

    #[getter]
    fn source(&self) -> String {
        string_at(&self.value, &["source"])
    }

    #[getter]
    fn source_revision(&self) -> String {
        string_at(&self.value, &["source_revision"])
    }

    #[getter]
    fn diagnostics(&self) -> Vec<PyDiagnostic> {
        array_at(&self.value, &["diagnostics"])
            .into_iter()
            .map(|value| PyDiagnostic { value })
            .collect()
    }

    #[getter]
    fn records(&self) -> Vec<PyBibliographicRecord> {
        array_at(&self.value, &["bibliography", "records"])
            .into_iter()
            .map(|value| PyBibliographicRecord { value })
            .collect()
    }

    #[getter]
    fn bibliography(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        value_to_dict(
            py,
            get_at(&self.value, &["bibliography"]).unwrap_or(&Value::Null),
        )
    }

    #[getter]
    fn applied_fix_ids(&self) -> Vec<String> {
        strings_at(&self.value, &["applied_fix_ids"])
    }

    fn to_dict(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        value_to_dict(py, &self.value)
    }
}

#[pymethods]
impl PyExportResult {
    #[getter]
    fn schema_version(&self) -> String {
        string_at(&self.value, &["schema_version"])
    }

    #[getter]
    fn source(&self) -> String {
        string_at(&self.value, &["source"])
    }

    #[getter]
    fn profile(&self) -> String {
        string_at(&self.value, &["profile"])
    }

    #[getter]
    fn record_count(&self) -> usize {
        get_at(&self.value, &["record_count"])
            .and_then(Value::as_u64)
            .and_then(|count| usize::try_from(count).ok())
            .unwrap_or_default()
    }

    #[getter]
    fn warnings(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        value_to_dict(
            py,
            get_at(&self.value, &["warnings"]).unwrap_or(&Value::Null),
        )
    }

    fn to_dict(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        value_to_dict(py, &self.value)
    }
}

#[pymethods]
impl PyExportProfileCatalog {
    #[getter]
    fn schema_version(&self) -> String {
        string_at(&self.value, &["schema_version"])
    }

    #[getter]
    fn profiles(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        value_to_dict(
            py,
            get_at(&self.value, &["profiles"]).unwrap_or(&Value::Null),
        )
    }

    fn to_dict(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        value_to_dict(py, &self.value)
    }

    fn __repr__(&self) -> String {
        format!(
            "ExportProfileCatalog(profiles={})",
            array_at(&self.value, &["profiles"]).len()
        )
    }
}

#[pymethods]
impl PyAnalysisDelta {
    #[getter]
    fn source_revision(&self) -> String {
        string_at(&self.value, &["source_revision"])
    }

    #[getter]
    fn added_diagnostics(&self) -> Vec<PyDiagnostic> {
        array_at(&self.value, &["added_diagnostics"])
            .into_iter()
            .map(|value| PyDiagnostic { value })
            .collect()
    }

    #[getter]
    fn removed_diagnostic_ids(&self) -> Vec<String> {
        strings_at(&self.value, &["removed_diagnostic_ids"])
    }

    #[getter]
    fn analysis(&self) -> PyAnalysisResult {
        PyAnalysisResult {
            value: self.value["analysis"].clone(),
        }
    }

    fn to_dict(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        value_to_dict(py, &self.value)
    }
}

#[pyclass(name = "DocumentSession", module = "bibmgr_native")]
#[derive(Debug)]
pub struct PyDocumentSession {
    inner: CoreDocumentSession,
}

#[pymethods]
impl PyDocumentSession {
    #[new]
    #[pyo3(signature = (source, profile="laboratory", tolerant=true))]
    fn new(py: Python<'_>, source: String, profile: &str, tolerant: bool) -> PyResult<Self> {
        let options = options_for(profile, tolerant)?;
        let inner = py.detach(move || CoreDocumentSession::open(source, options));
        Ok(Self { inner })
    }

    #[getter]
    fn source(&self) -> String {
        self.inner.source().to_owned()
    }

    #[getter]
    fn analysis(&self) -> PyResult<PyAnalysisResult> {
        PyAnalysisResult::from_serializable(self.inner.analysis())
    }

    fn update(
        &mut self,
        py: Python<'_>,
        revision: String,
        edit: &PyTextEdit,
    ) -> PyResult<PyAnalysisDelta> {
        let edit = TextEdit {
            range: TextRange::new(edit.start, edit.end),
            replacement: edit.replacement.clone(),
        };
        let delta = py
            .detach(|| self.inner.update(SourceRevision(revision), edit))
            .map_err(|error| EditConflictError::new_err(error.to_string()))?;
        PyAnalysisDelta::from_serializable(&delta)
    }
}

#[pyfunction(name = "analyze", signature = (source, profile="laboratory", tolerant=true, *, mode=None))]
fn py_analyze(
    py: Python<'_>,
    source: String,
    profile: &str,
    tolerant: bool,
    mode: Option<&str>,
) -> PyResult<PyAnalysisResult> {
    let tolerant = mode.map_or(Ok(tolerant), |mode| match mode {
        "tolerant" => Ok(true),
        "strict" => Ok(false),
        other => Err(ConfigurationError::new_err(format!(
            "unknown parse mode `{other}`"
        ))),
    })?;
    let options = options_for(profile, tolerant)?;
    let result = py.detach(move || bibmgr_core::analyze(&source, &options));
    PyAnalysisResult::from_serializable(&result)
}

#[pyfunction(signature = (source, fix_ids=None, profile="laboratory", *, source_revision=None))]
fn apply_fixes(
    py: Python<'_>,
    source: String,
    fix_ids: Option<Vec<String>>,
    profile: &str,
    source_revision: Option<String>,
) -> PyResult<PyApplyFixResult> {
    let options = options_for(profile, true)?;
    let result = py.detach(move || {
        if fix_ids.is_some() && source_revision.is_none() {
            return Err(EditConflictError::new_err(
                "source_revision is required when fix_ids are selected explicitly",
            ));
        }
        if let Some(expected) = source_revision {
            let actual = SourceRevision::of(&source);
            if expected != actual.as_str() {
                return Err(EditConflictError::new_err(format!(
                    "source revision is stale: expected {expected}, got {actual}"
                )));
            }
        }
        let Some(fix_ids) = fix_ids else {
            return bibmgr_core::apply_safe_fixes(&source, &options)
                .map_err(|error| EditConflictError::new_err(error.to_string()));
        };

        let analysis = bibmgr_core::analyze(&source, &options);
        let selection = FixSelection::Ids(fix_ids.into_iter().map(FixId::new).collect());
        let plan = bibmgr_core::plan_fixes(&analysis, &selection)
            .map_err(|error| ValidationError::new_err(error.to_string()))?;
        bibmgr_core::apply_fix_plan_with_options(&source, &plan, &options)
            .map_err(|error| EditConflictError::new_err(error.to_string()))
    })?;
    PyApplyFixResult::from_serializable(&result)
}

#[pyfunction(name = "validate_for_registration", signature = (source, policy="archive"))]
fn py_validate_for_registration(
    py: Python<'_>,
    source: String,
    policy: &str,
) -> PyResult<PyRegistrationValidation> {
    let policy = RegistrationPolicy::for_profile(&ProfileId::from(policy))
        .map_err(|error| ConfigurationError::new_err(error.to_string()))?;
    let result = py.detach(move || bibmgr_core::validate_for_registration(&source, &policy));
    PyRegistrationValidation::from_serializable(&result)
}

#[pyfunction(name = "canonicalize_for_storage", signature = (source, policy="archive"))]
fn py_canonicalize_for_storage(
    py: Python<'_>,
    source: String,
    policy: &str,
) -> PyResult<PyRegistrationValidation> {
    let policy = RegistrationPolicy::for_profile(&ProfileId::from(policy))
        .map_err(|error| ConfigurationError::new_err(error.to_string()))?;
    let result = py.detach(move || bibmgr_core::canonicalize_for_storage(&source, &policy));
    PyRegistrationValidation::from_serializable(&result)
}

#[pyfunction(name = "export", signature = (source, profile="laboratory"))]
fn py_export(py: Python<'_>, source: String, profile: &str) -> PyResult<PyExportResult> {
    let profile = ExportProfile::for_profile(&ProfileId::from(profile))
        .map_err(|error| ConfigurationError::new_err(error.to_string()))?;
    let result = py
        .detach(move || bibmgr_core::export_source(&source, &profile))
        .map_err(|error| ExportError::new_err(error.to_string()))?;
    PyExportResult::from_serializable(&result)
}

#[pyfunction(signature = (source, profile="laboratory"))]
fn export_source(py: Python<'_>, source: String, profile: &str) -> PyResult<PyExportResult> {
    py_export(py, source, profile)
}

#[pyfunction]
fn export_profiles(py: Python<'_>) -> PyResult<PyExportProfileCatalog> {
    let result = py
        .detach(bibmgr_core::export_profiles)
        .map_err(|error| ConfigurationError::new_err(error.to_string()))?;
    PyExportProfileCatalog::from_serializable(&result)
}

fn options_for(profile: &str, tolerant: bool) -> PyResult<AnalysisOptions> {
    let validation_policy = ValidationPolicy::for_profile(&ProfileId::from(profile))
        .map_err(|error| ConfigurationError::new_err(error.to_string()))?;
    Ok(AnalysisOptions {
        parse_mode: if tolerant {
            ParseMode::Tolerant
        } else {
            ParseMode::Strict
        },
        validation_policy,
        ..AnalysisOptions::default()
    })
}

fn get_at<'a>(value: &'a Value, path: &[&str]) -> Option<&'a Value> {
    path.iter().try_fold(value, |current, key| current.get(key))
}

fn string_at(value: &Value, path: &[&str]) -> String {
    get_at(value, path)
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_owned()
}

fn sourced_string_at(value: &Value, path: &[&str]) -> Option<String> {
    let sourced = get_at(value, path)?;
    let inner = sourced.get("value").unwrap_or(sourced);
    if let Some(text) = inner.as_str() {
        return Some(text.to_owned());
    }
    inner
        .get("value")
        .and_then(Value::as_str)
        .map(str::to_owned)
}

fn range_at(value: &Value, path: &[&str]) -> Option<(u32, u32)> {
    let range = get_at(value, path)?;
    let start = u32::try_from(range.get("start")?.as_u64()?).ok()?;
    let end = u32::try_from(range.get("end")?.as_u64()?).ok()?;
    Some((start, end))
}

fn array_at(value: &Value, path: &[&str]) -> Vec<Value> {
    get_at(value, path)
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
}

fn strings_at(value: &Value, path: &[&str]) -> Vec<String> {
    array_at(value, path)
        .into_iter()
        .filter_map(|value| value.as_str().map(str::to_owned))
        .collect()
}

fn value_to_dict(py: Python<'_>, value: &Value) -> PyResult<Py<PyAny>> {
    let serialized = serde_json::to_string(value).map_err(json_error)?;
    let json = PyModule::import(py, "json")?;
    Ok(json.call_method1("loads", (serialized,))?.unbind())
}

#[allow(clippy::needless_pass_by_value)]
fn json_error(error: serde_json::Error) -> PyErr {
    BibmgrError::new_err(format!("failed to serialize Rust DTO: {error}"))
}

#[pymodule]
fn bibmgr_native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("SCHEMA_VERSION", SCHEMA_VERSION)?;
    module.add("BibmgrError", module.py().get_type::<BibmgrError>())?;
    module.add("ParseError", module.py().get_type::<ParseError>())?;
    module.add("ValidationError", module.py().get_type::<ValidationError>())?;
    module.add(
        "EditConflictError",
        module.py().get_type::<EditConflictError>(),
    )?;
    module.add("ExportError", module.py().get_type::<ExportError>())?;
    module.add(
        "ConfigurationError",
        module.py().get_type::<ConfigurationError>(),
    )?;

    module.add_class::<PyTextEdit>()?;
    module.add_class::<PyDiagnostic>()?;
    module.add_class::<PyRelatedLocation>()?;
    module.add_class::<PyFix>()?;
    module.add_class::<PyBibliographicRecord>()?;
    module.add_class::<PyAnalysisResult>()?;
    module.add_class::<PyApplyFixResult>()?;
    module.add_class::<PyRegistrationValidation>()?;
    module.add_class::<PyExportResult>()?;
    module.add_class::<PyExportProfileCatalog>()?;
    module.add_class::<PyAnalysisDelta>()?;
    module.add_class::<PyDocumentSession>()?;
    module.add_function(wrap_pyfunction!(py_analyze, module)?)?;
    module.add_function(wrap_pyfunction!(apply_fixes, module)?)?;
    module.add_function(wrap_pyfunction!(py_validate_for_registration, module)?)?;
    module.add_function(wrap_pyfunction!(py_canonicalize_for_storage, module)?)?;
    module.add_function(wrap_pyfunction!(py_export, module)?)?;
    module.add_function(wrap_pyfunction!(export_source, module)?)?;
    module.add_function(wrap_pyfunction!(export_profiles, module)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn export_profile_catalog_dto_preserves_public_metadata() {
        let catalog = bibmgr_core::export_profiles().unwrap();
        let dto = PyExportProfileCatalog::from_serializable(&catalog).unwrap();
        let profiles = dto.value["profiles"].as_array().unwrap();

        assert_eq!(dto.value["schema_version"], "1");
        assert_eq!(
            profiles.len(),
            bibmgr_core::ExportProfile::builtins().unwrap().len()
        );
        assert_eq!(profiles[0]["id"], "modern");
        assert_eq!(profiles[1]["id"], "laboratory");
        assert!(profiles.iter().all(|profile| {
            profile["display_name"]
                .as_str()
                .is_some_and(|name| !name.is_empty())
                && profile["description"]
                    .as_str()
                    .is_some_and(|description| !description.is_empty())
        }));
    }
}
