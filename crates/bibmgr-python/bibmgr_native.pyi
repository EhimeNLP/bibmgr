from __future__ import annotations
from typing import Any

SCHEMA_VERSION: str

class BibmgrError(Exception): ...
class ParseError(BibmgrError): ...
class ValidationError(BibmgrError): ...
class EditConflictError(BibmgrError): ...
class ExportError(BibmgrError): ...
class ConfigurationError(BibmgrError): ...

class TextEdit:
    start: int
    end: int
    replacement: str
    def __init__(self, start: int, end: int, replacement: str) -> None: ...
    def to_dict(self) -> dict[str, Any]: ...

class RelatedLocation:
    message: str
    range: tuple[int, int] | None
    def to_dict(self) -> dict[str, Any]: ...

class Diagnostic:
    id: str
    code: str
    severity: str
    blocking: bool
    message: str
    range: tuple[int, int] | None
    related_locations: list[RelatedLocation]
    notes: list[str]
    fixes: list[str]
    def to_dict(self) -> dict[str, Any]: ...

class Fix:
    id: str
    title: str
    applicability: str
    edits: list[TextEdit]
    def to_dict(self) -> dict[str, Any]: ...

class BibliographicRecord:
    citation_key: str | None
    entry_type: str | None
    title: str | None
    work_type: str | None
    def to_dict(self) -> dict[str, Any]: ...

class AnalysisResult:
    schema_version: str
    source_revision: str
    diagnostics: list[Diagnostic]
    available_fixes: list[Fix]
    records: list[BibliographicRecord]
    syntax: dict[str, Any]
    bibliography: dict[str, Any]
    def to_dict(self) -> dict[str, Any]: ...
    def to_json(self) -> str: ...

class ApplyFixResult:
    schema_version: str
    source: str
    source_revision: str
    applied_fix_ids: list[str]
    diff: str
    analysis: AnalysisResult
    diagnostics: list[Diagnostic]
    def to_dict(self) -> dict[str, Any]: ...
    def to_json(self) -> str: ...

class RegistrationValidation:
    schema_version: str
    accepted: bool
    source: str
    source_revision: str
    unresolved_semantics: bool
    diagnostics: list[Diagnostic]
    records: list[BibliographicRecord]
    bibliography: dict[str, Any]
    applied_fix_ids: list[str]
    def to_dict(self) -> dict[str, Any]: ...

class ExportResult:
    schema_version: str
    source: str
    profile: str
    record_count: int
    warnings: list[dict[str, Any]]
    def to_dict(self) -> dict[str, Any]: ...

class ExportProfileCatalog:
    schema_version: str
    profiles: list[dict[str, str]]
    def to_dict(self) -> dict[str, Any]: ...

class AnalysisDelta:
    source_revision: str
    added_diagnostics: list[Diagnostic]
    removed_diagnostic_ids: list[str]
    analysis: AnalysisResult
    def to_dict(self) -> dict[str, Any]: ...

class DocumentSession:
    source: str
    analysis: AnalysisResult
    def __init__(self, source: str, profile: str = "laboratory", tolerant: bool = True) -> None: ...
    def update(self, revision: str, edit: TextEdit) -> AnalysisDelta: ...

def analyze(source: str, profile: str = "laboratory", tolerant: bool = True, *, mode: str | None = None) -> AnalysisResult: ...
def apply_fixes(source: str, fix_ids: list[str] | None = None, profile: str = "laboratory", *, source_revision: str | None = None) -> ApplyFixResult: ...
def validate_for_registration(source: str, policy: str = "laboratory") -> RegistrationValidation: ...
def canonicalize_for_storage(source: str, policy: str = "laboratory") -> RegistrationValidation: ...
def export(source: str, profile: str = "laboratory") -> ExportResult: ...
def export_source(source: str, profile: str = "laboratory") -> ExportResult: ...
def export_profiles() -> ExportProfileCatalog: ...
