# Python API (PyO3)

`bibmgr_native` is a thin PyO3 adapter over `bibmgr-core`. It contains DTO and error conversion only; all BibTeX interpretation and policy decisions execute in Rust.

From the repository root, build and install the native extension into the uv-managed development environment:

```console
uv run poe setup-native
```

## Analysis

```python
import bibmgr_native

result = bibmgr_native.analyze(source, mode="tolerant")
assert result.schema_version == "1"
for diagnostic in result.diagnostics:
    print(diagnostic.code, diagnostic.severity, diagnostic.range)
```

Ranges are half-open UTF-8 byte offsets. Do not index a Python Unicode string with them directly; encode to UTF-8 or use the provided line/column presentation helper.

## Fixes

```python
fixed = bibmgr_native.apply_fixes(
    source,
    fix_ids=["BIB-SYNTAX-004:0"],
    source_revision=result.source_revision,
)
print(fixed.source)
```

Fix IDs are scoped to the returned source revision. Explicit selection requires that revision and raises `EditConflictError` if it does not match `source`. Reanalyze after changing the editor buffer and never apply IDs from an older result.

Omitting `fix_ids` (or passing `None`) applies every available safe fix. The core uses deterministic non-conflicting batches, reanalyzing between batches until no safe fix remains, and returns the cumulative diff plus final analysis. Passing a list is an explicit selection; an empty list applies nothing, while confirmation-required or unsafe IDs are accepted only as an explicit caller choice. Python or UI callers must obtain any required confirmation themselves.

## Registration and export

```python
decision = bibmgr_native.validate_for_registration(
    source,
    policy="archive",
)
if decision.accepted:
    persist(decision.bibliography.records, source)

output = bibmgr_native.export_source(
    source,
    profile="classical-bst",
    venue_name_style="abbreviated",
)
print(output.source)

catalog = bibmgr_native.export_profiles()
for profile in catalog.profiles:
    print(profile["id"], profile["display_name"])
```

Interactive adapters that deliberately continue past target-policy diagnostics can use `export_source_workflow()`. It first requires syntactically valid BibTeX, applies every safe fix for the export profile's validation policy to a fixed point, exports without treating remaining validation diagnostics as a gate, safe-fixes the generated output, and returns both input and output diagnostics. Confirmation-required and unsafe fixes are never applied. The CLI and web backend continue to use the strict `export_source()` contract.

```python
report = bibmgr_native.export_source_workflow(source)
print(report.source)
print(report.input_applied_fix_ids)
for diagnostic in report.input_diagnostics + report.output_diagnostics:
    print(diagnostic.code, diagnostic.message)
```

Use `decision.accepted`; do not infer registration from diagnostic severity in Python. The default `archive` policy rejects structural parse failures but disables `LAB-*` conventions and accepts incomplete metadata and unresolved semantic values without rewriting `source`. Analysis, fixes, sessions, and export default to `modern`, which also excludes `LAB-*` rules; pass `profile="laboratory"` only when those conventions are wanted. `canonicalize_for_storage` remains an explicit opt-in CST normalization utility; database persistence does not call it. Export returns newly generated target BibTeX and never edits `source`. Venue naming accepts `full` or `abbreviated` and defaults to `full` independently of the profile. `export_profiles()` returns canonical built-in profile metadata in stable display order, so applications do not hardcode the selectable targets or their descriptions. Host applications may pass validated `profile_json` and `venue_registry_json` snapshots; the bundled web backend uses these parameters for database-backed configuration overrides.

## Sessions

`DocumentSession(source, ...)` is opaque. Its `update` method accepts the expected revision and one `TextEdit`, then returns the new revision/analysis. Internal CST and parser nodes are intentionally unavailable to Python.

## Exceptions

```text
BibmgrError
|- ParseError
|- ValidationError
|- EditConflictError
|- ExportError
`- ConfigurationError
```

Document diagnostics are regular successful results. Exceptions represent an operation/configuration failure. CPU-heavy core calls release the GIL, so the same extension can be used from a threaded HTTP service.

The backend in [`backend/`](../backend) performs DTO conversion without reimplementing any rule.
