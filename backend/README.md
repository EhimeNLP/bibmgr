# bibmgr backend

The backend exposes the shared Rust BibTeX engine and a PostgreSQL-backed reference library through FastAPI. BibTeX interpretation and structural registration decisions remain owned by `bibmgr_native`; the Python layer stores the accepted BibTeX without rewriting it, maps semantic projections into relational storage, and retains complete snapshots in append-only history.

## Database

PostgreSQL 18 is the production database. The initial Alembic migration creates normalized reference, contributor, identifier, URL, and citation-context tables, enables `pg_trgm`, and adds trigram and strong-identifier indexes.

Start the development database and email inbox, then apply migrations from the repository root:

```bash
uv run poe dev-services-up
uv run poe db-migrate
```

Docker is optional. PostgreSQL 18 and Mailpit can also run directly on the development host. See the [local development guide](../docs/local-development.md) for the macOS Homebrew setup, account creation flow, and service lifecycle.

Reset the local development schema with `uv run poe db-reset`. The command only accepts PostgreSQL targets on localhost and requires the database name to be typed before it downgrades to `base` and upgrades to `head`.

For non-interactive development automation, both safeguards must be explicit:

```bash
BIBMGR_ENV=development bibmgr-db reset --yes
```

`BIBMGR_DATABASE_URL` selects the connection. It defaults to:

```text
postgresql+psycopg://bibmgr:bibmgr@127.0.0.1:5432/bibmgr
```

`BIBMGR_REGISTRATION_POLICY` selects the server-owned registration policy and defaults to `archive`. That policy uses strict parsing but does not reject profile conventions, missing profile-required metadata, or unresolved semantic values. API clients cannot override the policy during persistence.

Production startup must run `bibmgr-db upgrade` before starting the application. Migrations are packaged in the backend wheel; the service intentionally does not create or migrate tables at import time.

## Reference API

| Method and path | Purpose |
| --- | --- |
| `GET /references?query=&limit=50&offset=0` | Compatibility search/list endpoint |
| `GET /references/page` | Paginated structured search with total count |
| `GET /references/{id}` | Fetch one reference |
| `POST /references` | Validate and atomically register all BibTeX entries |
| `PUT /references/{id}` | Replace one reference after revision checking |
| `POST /references/{id}/citation-contexts` | Append citation contexts as a new history revision |
| `DELETE /references/{id}` | Revision-checked delete of a reference and dependent rows |
| `GET /reference-history` | List active and deleted reference histories |
| `GET /reference-history/page` | Paginated history index with total count |
| `GET /references/{id}/history` | Fetch the ordered revisions of one reference |
| `POST /references/{id}/revert` | Restore a revision as a new head revision |

Reference search and detail are public. History reads require a logged-in session because they expose operator identities. Reference writes and revision restore additionally require a valid `X-CSRF-Token` header.

Registration accepts:

```json
{
  "bibtex": "@article{...}",
  "source": "manual"
}
```

The response contains `reference` for compatibility with the existing UI and `references` for the complete batch. DOI and arXiv identifiers are globally unique. A conflicting batch returns HTTP 409 and the whole transaction is rolled back.

Editing accepts exactly one BibTeX entry and requires the `sourceRevision` returned by the read API:

```json
{
  "bibtex": "@article{...}",
  "source_revision": "sha256:..."
}
```

Stale edits return HTTP 409 with the current revision in `error.details.source_revision`.

Deletion requires the latest `sourceRevision` in an `If-Match` header. Stale deletes return HTTP 409 instead of deleting a concurrently edited record.

Every successful reference write appends a per-reference, monotonically increasing history revision containing the exact stored BibTeX, semantic data, and a complete relational snapshot. Legacy snapshot field names `submitted_bibtex` and `canonical_bibtex` remain for compatibility; new writes contain the same source in both. Citation-context additions are recorded as `context` revisions. Deletion leaves a permanent history head and tombstone, so a preceding revision can recreate the same reference ID. Restore requires the history head revision observed by the caller and returns HTTP 409 if another write has advanced it. The PostgreSQL audit table rejects `UPDATE` and `DELETE` through a database trigger.

## Native BibTeX API

The service also exposes:

- `POST /bibtex/analyze`
- `POST /bibtex/fixes/apply`
- `POST /bibtex/registration/validate`
- `POST /bibtex/registration/canonicalize`
- `GET /bibtex/export/profiles`
- `POST /bibtex/export`

`GET /healthz` is a process liveness check. `GET /readyz` verifies database connectivity. `GET /metrics` exposes Prometheus text metrics. Every HTTP response includes `X-Request-ID`, and the backend writes structured request logs without request bodies, email addresses, or BibTeX content.

## Email authentication

`POST /auth/email/start` sends an eight-digit, single-use code to an address whose domain exactly matches `BIBMGR_AUTH_EMAIL_DOMAIN`, which defaults to `ai.cs.ehime-u.ac.jp`. Exact complete addresses outside that domain can be added with `BIBMGR_AUTH_ALLOWED_EMAILS`; domain entries and wildcard patterns are not supported. `POST /auth/email/verify` creates the user on first verification and issues an opaque seven-day database session. `GET /auth/session` restores browser state and `POST /auth/logout` revokes the session.

Development SMTP defaults to Mailpit at `127.0.0.1:1025`; its inbox is exposed at `http://127.0.0.1:8025/`. Production requires `BIBMGR_ENV=production`, `BIBMGR_AUTH_SECRET`, HTTPS, secure cookies, and the SMTP settings documented in [`docs/authentication.md`](../docs/authentication.md).

Account status, session revocation, expired-auth cleanup, backup, restore, deployment, and monitoring procedures are documented in [`docs/operations.md`](../docs/operations.md). The complete schema and transaction rationale is documented in [`docs/database.md`](../docs/database.md).
