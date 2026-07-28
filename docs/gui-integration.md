# GUI and backend integration

The integration path is fixed:

```text
Vue -> Python HTTP API -> bibmgr_native -> bibmgr-core
```

The frontend never parses BibTeX to produce diagnostics or decide whether a record can be registered. It may perform transport-level checks such as an empty input or file-size limit.

## Endpoints

The example backend exposes schema-v1 JSON:

| Method and path | Purpose |
| --- | --- |
| `POST /bibtex/analyze` | Strict/tolerant lint and available fixes |
| `POST /bibtex/fixes/apply` | Apply selected revision-bound fix IDs and reanalyze |
| `POST /bibtex/registration/validate` | Authoritative registration decision |
| `POST /bibtex/registration/canonicalize` | Explicit opt-in CST normalization utility |
| `GET /bibtex/export/profiles` | Server-owned output profile catalog |
| `POST /bibtex/export` | Profile-driven semantic export preview |
| `POST /auth/email/start` | Send a passwordless login code |
| `POST /auth/email/verify` | Verify a code and create a session |
| `GET /auth/session` | Restore the current browser session |
| `POST /auth/logout` | Revoke the current session |
| `GET /references` | Search or list persisted references |
| `GET /references/{id}` | Fetch one persisted reference |
| `GET /reference-history` | List histories, including deleted references |
| `GET /references/{id}/history` | Fetch ordered revisions and operators |
| `POST /references` | Atomically validate and register BibTeX |
| `PUT /references/{id}` | Revision-checked replacement |
| `DELETE /references/{id}` | Delete a reference |
| `POST /references/{id}/revert` | Restore a prior state as a new revision |

BibTeX processing and reference reads are public. Reference registration, replacement, and deletion require the HttpOnly session cookie plus the session-bound `X-CSRF-Token`. The frontend restores that token from `GET /auth/session`; it never stores a reusable API key.

History reads require login because they include actor email addresses. The history catalog retains deleted reference IDs and titles. Restoring sends both the selected revision and the currently displayed head revision; `stale_reference_history` means the client must reload rather than retry with an obsolete head.

Every request carries `source`; relevant requests also carry `profile`, `policy`, `mode`, `fix_ids`, or `source_revision`. An explicit fix request must send the revision returned by the analysis that exposed its IDs. Every success carries `schema_version`. Errors use a stable code/message DTO and do not masquerade as diagnostics. Transport-level request validation uses `invalid_request` without copying framework-owned input values into the response.

## Editor lifecycle

```mermaid
sequenceDiagram
    participant U as User
    participant V as Vue editor
    participant B as Backend
    participant R as Rust core
    U->>V: Edit source
    V->>B: analyze(source, tolerant)
    B->>R: analyze
    R-->>V: revision, diagnostics, fixes
    U->>V: Select fix
    V->>B: apply(source, revision, fix IDs)
    B->>R: plan + apply + reanalyze
    R-->>V: changed source and fresh analysis
```

The supplied validation panel debounces real-time tolerant analysis (350 ms by default). A source or profile change cancels the in-flight request and advances a local generation; responses from an older generation are ignored even if transport cancellation races with completion. The same stale-source check is performed before accepting a fix response, so an edit made while a fix is in flight is never overwritten.

Render a result only when it belongs to the current editor buffer and profile. Core ranges are UTF-8 bytes, whereas JavaScript string and editor offsets are UTF-16 code units. Convert each primary and related range at the view boundary before highlighting; never pass byte offsets directly to `slice`, selection, or decoration APIs.

## Diagnostic presentation

Use `severity` for icon/color/order and `blocking` for the registration state. Display related locations and notes when present. The supplied editor decorates both the primary and same-source related locations, using the most severe overlapping diagnostic for presentation. A fix button uses the fix ID and applicability supplied by the backend. The UI must request confirmation for `requires_confirmation` and must not apply `unsafe` automatically.

## Registration

Before persistence, the backend calls `validate_for_registration` with the server-selected `archive` policy. This forces strict parsing while leaving profile conventions, missing metadata, and unresolved semantics non-blocking. The registration and edit UIs run tolerant `archive` analysis for advisory diagnostics and show one read-only output preview generated through the export endpoint. That preview selects `laboratory` by default and regenerates when the user chooses another profile. Saving remains a single action and sends the current editor bytes directly; neither the selected output profile nor its preview changes the persistence payload. The backend does not call `canonicalize_for_storage`. Authoritative structural rejection is returned by the persistence endpoint, and the editor keeps its content.

`POST /references` accepts the complete submitted source and stores every exact UTF-8 entry slice plus its semantic projection in one transaction. The compatibility field `reference` contains the first stored record, while `references` contains the complete batch. DOI and arXiv conflicts reject and roll back the complete batch. Each history revision retains the stored source and full semantic snapshot.

`PUT /references/{id}` accepts exactly one entry and requires the current `source_revision`. A mismatch returns `stale_reference` with the current revision, so clients must reload instead of overwriting a concurrent edit.

The reference detail groups `Edit…` and `Delete…` in a compact More menu instead of giving secondary and destructive actions permanent emphasis in the header. The menu lists Edit first and visually distinguishes Delete after a separator. An unauthenticated action opens login instead of attempting a write. Edit first fetches the latest reference, shows advisory archive diagnostics, and sends the exact edited source with that latest `source_revision`. Delete uses a concise confirmation dialog before calling the endpoint. After either operation, the application updates the selected reference and library list without a full-page reload. A deleted item remains restorable from History.

Sign out also requires explicit confirmation. Opening the confirmation does not revoke the session; only its final `Sign out` action calls `POST /auth/logout`.

## BibTeX preview and profiles

The reference detail has one BibTeX preview and selects the `laboratory` profile by default. Every selected profile, including `laboratory`, is rendered through the export endpoint from the stored source. Selecting another profile replaces the contents of the same preview; returning to `laboratory` generates the laboratory representation again. Export warnings never change the database value. Profile and source generations are checked when each request completes, so a stale response cannot replace a newer preview. The authenticated history view labels the persisted value as Stored BibTeX and can still show separate submitted/stored values for legacy normalized revisions.

## Frontend modules

`frontend/src/types/bibtex.ts` mirrors the stable DTO subset, and `frontend/src/api/bibtex.ts` owns transport. Components consume those modules; they should not add regex-based validation rules. The API base URL and optional API key use the same environment configuration as registration. `frontend/src/utils/bibtexDiagnostics.ts` is the single UTF-8-byte to UTF-16-index conversion boundary used by editor diagnostics.
