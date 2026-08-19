# Public Rust API

Consumers should depend on `bibmgr-core`, not call parser, semantic, validation, edit, or export crates in sequence themselves. Exact Rust signatures are in the generated crate documentation; this page describes the stable high-level contract.

## Analyze

```rust
let options = AnalysisOptions::default();
let result = bibmgr_core::analyze(source, &options);
```

Analysis always treats the input as a complete BibTeX document, including when it contains one entry. The result includes:

- schema version and source revision;
- syntax/recovery summary;
- semantic bibliography with provenance;
- deterministic diagnostics;
- fix descriptions and revision-bound text edits.

During semantic analysis, aliases in the embedded venue and repository registries are resolved to canonical venue metadata or repository prefixes. The source spelling and provenance remain available. Export callers choose full or abbreviated venue names independently from the output profile.

Use strict parsing for registration, CI, and export readiness. Use tolerant parsing for an editor buffer that may be temporarily incomplete.

## Plan and apply fixes

```rust
let plan = bibmgr_core::plan_fixes(&analysis, &selection)?;
let applied = bibmgr_core::apply_fix_plan(source, &plan)?;

// Apply all unattended fixes, including safe fixes that initially overlap.
let applied = bibmgr_core::apply_safe_fixes(source, &options)?;
```

Planning rejects unknown, conflicting, or disallowed fix IDs. Application rejects a stale source revision, overlapping ranges, and ranges that split a UTF-8 code point. The returned value contains the changed source and a fresh analysis. Persist only after successful application.

`Safe` fixes may be selected automatically. `RequiresConfirmation` must be shown to the user. `Unsafe` is explanatory and is never automatically applied.

`apply_safe_fixes` applies a deterministic non-conflicting batch, reanalyzes the changed source, and repeats until no safe fix remains. This is necessary when two individually safe fixes overlap, because each later batch must be planned against the new source revision. The operation returns one cumulative diff and the final analysis, or a typed error if it cannot make progress or converge.

## Inspection

```rust
let cst = bibmgr_core::inspect_cst(source, parse_options);
let ast = bibmgr_core::inspect_ast(source, parse_options);
```

Both inspection APIs return a core-owned envelope with `schema_version` and `source_revision`. The CST payload is under `document`; the semantic AST payload is under `bibliography`. Consumers should not depend on parser-backend types.

## Registration

```rust
let decision = bibmgr_core::validate_for_registration(source, &policy);
if !decision.accepted {
    // Return decision.diagnostics; do not reconstruct the decision here.
}
```

Registration eligibility is a policy result, not `severity == Error`. Consumers must use the returned `accepted`/`blocking` decision and preserve diagnostics. Database ingest uses `RegistrationPolicy::archive()`, which forces strict parsing, disables `LAB-*` conventions, and leaves incomplete metadata and unresolved semantics non-blocking. Hosts that load policies and registries externally can call `validate_for_registration_with_options`; the supplied validation profile must match `RegistrationPolicy.validation_profile`. The core validates both configurations and forces strict parsing before deciding.

## Export

```rust
let catalog = bibmgr_core::export_profiles()?;
let output = bibmgr_core::export_source(source, &profile)?;

let abbreviated = bibmgr_core::export_source_with_options(
    source,
    &profile,
    &ExportSourceOptions {
        venue_name_style: VenueNameStyle::Abbreviated,
        ..ExportSourceOptions::default()
    },
)?;
```

`export_profiles` returns the canonical built-in targets and their display metadata in stable order; compatibility aliases are intentionally omitted. Export analyzes the source and serializes the semantic bibliography. Blocking syntax, unresolved values, ambiguous macro expansions, or conflicting semantic state produces a typed export error. The exporter first generates semantic candidate fields, then applies the profile's case-insensitive allowlist and denylist to all structured and extra fields, normalizes names, applies configured whole-value case-protection groups, orders the survivors, and serializes them. `ExportSourceOptions.venue_name_style` applies full or abbreviated naming to conference, journal, and other venue-derived fields and defaults to full. A built-in or custom profile may case-protect the complete `title` value so traditional BST case conversion cannot rewrite its characters. The generated document is then re-analyzed under `ExportProfile.validation_profile`, so representation changes cannot silently violate target-profile requirements. Export output is deterministic and does not mutate the input or citation identity.

## Editing session

`DocumentSession::open` owns source, options, revision, and current analysis. `update(expected_revision, edit)` rejects stale editor events and returns a new revision plus analysis delta. The CST remains private, including through PyO3.

## DTO rules

- `schema_version` is the string `"1"`.
- `TextRange` is half-open UTF-8 bytes.
- IDs and rule codes are opaque stable strings.
- DTO collections have deterministic ordering.
- Optional values are absent/`null`; an unknown semantic value is not replaced with an empty string.
- Consumers ignore unknown fields for forward-compatible additions.

The machine-readable definition is [`schemas/bibmgr-v1.schema.json`](../schemas/bibmgr-v1.schema.json).

## Errors

Public entry points return typed errors rather than panic:

```text
BibmgrError
|- Parse
|- Semantic
|- Validation
|- FixPlan (including unknown IDs and conflicts)
|- Edit (including stale revision and conflict)
|- Export
`- Configuration
```

An analysis diagnostic is a problem in the user's document. An API error means the requested operation could not be carried out; adapters should not collapse the two. `apply_safe_fixes` additionally reports a typed no-progress or pass limit error if repeated safe batches fail to reach a fixed point.
