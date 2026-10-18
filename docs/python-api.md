# Python API (PyO3)

`bibmgr_native` exposes `bibmgr-core` through PyO3, converting Rust results and errors into Python objects.

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

Fix IDs are scoped to the returned source revision. Explicit selection requires that revision and raises `EditConflictError` if it does not match `source`. Reanalyze after changing the editor buffer to obtain current fix IDs.

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

`export_source_workflow()` returns exported BibTeX together with input and output diagnostics. It first requires syntactically valid BibTeX, applies every safe fix for the export profile's validation policy to a fixed point, exports without treating remaining validation diagnostics as a gate, and safe-fixes the generated output. Automatic changes are limited to safe fixes. Use `export_source()` when remaining blocking diagnostics should reject export.

```python
report = bibmgr_native.export_source_workflow(source)
print(report.source)
print(report.input_applied_fix_ids)
for diagnostic in report.input_diagnostics + report.output_diagnostics:
    print(diagnostic.code, diagnostic.message)
```

Use `decision.accepted` for registration eligibility; diagnostic severity controls presentation independently. The default `archive` policy rejects structural parse failures but disables optional profile conventions and accepts incomplete metadata and unresolved semantic values without rewriting `source`. Analysis, fixes, sessions, and export default to `modern`. Call `canonicalize_for_storage` to request safe CST normalization.

Export returns newly generated target BibTeX while preserving `source`. Venue naming accepts `full` or `abbreviated` and defaults to `full` independently of the profile. `export_profiles()` provides the profile IDs and descriptions for application selectors in stable display order.

Host applications may pass validated `profile_json` and `venue_registry_json` snapshots; the bundled web backend uses these parameters for database-backed configuration overrides. See [Configuration](configuration.md#custom-export-profile-example) for a complete custom profile definition and application example.

## Sessions

`DocumentSession(source, ...)` is opaque. Its `update` method accepts the expected revision and one `TextEdit`, then returns the new revision/analysis.

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

See [`backend/`](../backend) for an HTTP integration using this API.

## Duplicate comparison

`bibmgr_native.comparison_records(records_json)` accepts the serialized semantic record array from core analysis and returns `{"records": [...]}`. Pass that array to `bibmgr_native.assess_duplicates(incoming_json, candidates_json, policy_json="{}")`. The result contains `findings` and the resolved `policy`; normalization and comparison execute in Rust with the GIL released. Candidate indices identify records in the supplied arrays, not database IDs. The backend adds database IDs and source revisions for its warning/confirmation workflow.
