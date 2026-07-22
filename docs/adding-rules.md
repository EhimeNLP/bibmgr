# Adding a validation rule

A rule is implemented once in `bibmgr-validation` and is consumed unchanged by the CLI, PyO3, backend, and GUI.

## Stable code and category

Choose a code in the appropriate namespace:

| Prefix | Input used by the rule |
| --- | --- |
| `BIB-SYNTAX-` | Lossless syntax/CST |
| `BIB-SEMANTIC-` | Semantic bibliography and provenance |
| `LAB-` | Laboratory policy convention |
| `EXPORT-` | Readiness for a named export representation |

Codes are permanent identifiers. Do not reuse a retired code or encode the severity in it. Add the code and metadata to the validation rule catalog so configuration validation can reject misspellings.

## Implementation checklist

1. Decide whether the rule consumes syntax, semantic values, or both. Keep all parser-backend types inside `bibmgr-syntax`.
2. Emit deterministic results: never rely on hash-map iteration, locale, wall clock time, random IDs, or external network calls.
3. Point the primary location to the smallest useful UTF-8 byte range. Add related locations for duplicates or conflicts.
4. Set default severity and default blocking independently. Active policy may override blocking without rewriting the rule.
5. If a repair is possible, return a revision-bound fix made only of text edits. Classify it `Safe`, `RequiresConfirmation`, or `Unsafe` based on semantic risk.
6. Register the rule in the catalog and add it only to appropriate policies.
7. Document the user-facing meaning and any policy parameters.

## Required tests

Each rule should have valid and invalid fixtures and assert code, message, primary and related ranges, severity, blocking decision, fix applicability, and deterministic ordering. A fixable rule also needs tests for byte preservation, post-fix revalidation, idempotence of a safe fix, stale revision rejection, and multi-byte UTF-8 boundaries.

Add an adapter parity fixture: core output, CLI JSON, PyO3 DTO, and backend JSON must contain the same normalized diagnostic and fix information. Frontend tests should only test DTO rendering/transport; they must not duplicate the rule.

## Changing a rule

A clearer message is additive. Changing what a code detects can affect stored suppressions and registration decisions, so note it in release documentation and update golden fixtures. A fundamentally different condition receives a new code. Breaking DTO changes require a new schema version.
