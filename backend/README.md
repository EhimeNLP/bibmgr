# Backend

The FastAPI backend exposes the shared Rust BibTeX engine and a PostgreSQL-backed reference library. Python owns transport, authentication, persistence, and deployment integration; `bibmgr_native` remains authoritative for BibTeX interpretation, validation, fixes, registration decisions, and export.

## Responsibilities

- Store accepted BibTeX source without profile-driven rewriting.
- Project semantic records into searchable relational data while retaining complete snapshots in append-only history.
- Provide authenticated reference, BibTeX, configuration, and history APIs.
- Enforce session, CSRF, optimistic-revision, request-size, and rate-limit boundaries.
- Expose liveness, readiness, structured logs, and private Prometheus metrics for operations.

## Development

Run backend tasks from the repository root. Start PostgreSQL and Mailpit, apply migrations, and launch the reload-enabled server:

```bash
uv run poe dev-services-up
uv run poe db-migrate
uv run poe dev-backend
```

The backend listens at `http://127.0.0.1:8000/`; OpenAPI documentation is available at `http://127.0.0.1:8000/docs`. Mailpit exposes the development inbox at `http://127.0.0.1:8025/`.

Docker is optional. PostgreSQL 18 and Mailpit can also run directly on the development host. See the [local development guide](../docs/local-development.md) for the macOS Homebrew setup, first-account flow, and service lifecycle.

### Database lifecycle

The default development connection is:

```text
postgresql+psycopg://bibmgr:bibmgr@127.0.0.1:5432/bibmgr
```

Reset the local schema with `uv run poe db-reset`. The command accepts only localhost PostgreSQL targets and requires the database name to be typed before rebuilding the schema. Non-interactive development automation must opt in explicitly:

```bash
BIBMGR_ENV=development bibmgr-db reset --yes
```

Production startup must run `bibmgr-db upgrade` before starting the application. Migrations are packaged in the backend wheel; importing or starting the service never creates or migrates tables automatically.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `BIBMGR_DATABASE_URL` | Local `bibmgr` PostgreSQL database | Select the application database. |
| `BIBMGR_REGISTRATION_POLICY` | `archive` | Select the server-owned registration policy; API clients cannot override it during persistence. |
| `BIBMGR_AUTH_EMAIL_DOMAIN` | `example.test` in development | Select the exact login domain; production requires an explicit value. |
| `BIBMGR_AUTH_ALLOWED_EMAILS` | Empty | Add exact external addresses outside the configured domain. |
| `BIBMGR_SMTP_HOST` / `BIBMGR_SMTP_PORT` | `127.0.0.1:1025` | Select the email-code delivery service. |
| `BIBMGR_ENV` | Development behavior | Enable production-only security requirements when set to `production`. |

The default `archive` registration policy uses strict parsing while accepting incomplete metadata and unresolved semantic values without rewriting the submitted source. Standalone analysis, fixes, and export default to the `modern` profile. Production additionally requires `BIBMGR_AUTH_SECRET`, HTTPS, secure cookies, and explicit SMTP settings.

## Architecture

### Persistence

PostgreSQL 18 is the source of truth. Alembic migrations create normalized reference, contributor, identifier, URL, citation-context, configuration, and audit tables, enable `pg_trgm`, and install the required indexes and history protections.

Registration is atomic across every BibTeX entry in a request. DOI and arXiv identifiers are globally unique; a validation error, identifier conflict, or database failure rolls back the complete batch. Successful writes retain the exact source, semantic snapshot, relational projection, actor, and monotonically increasing revision. Deletes create tombstones, and restores append a new revision without rewriting prior history.

### HTTP interfaces

| Path group | Responsibility |
| --- | --- |
| `/references` | Search, register, read, revise, delete, restore, and attach citation contexts. |
| `/reference-history` | Browse active and deleted reference histories. |
| `/bibtex` | Analyze, apply fixes, validate registration, and export through the native engine. |
| `/settings` | Read and revision-check shared export-profile and venue configuration. |
| `/auth` | Start and verify email-code login, restore sessions, and sign out. |
| `/healthz` / `/readyz` | Report process liveness and database readiness. |
| `/metrics` | Expose private-network Prometheus metrics. |

All application data endpoints require a logged-in session. State-changing requests additionally require the session-bound `X-CSRF-Token`. Reference updates use `source_revision`; deletes use the same revision as a quoted `If-Match` value. Configuration writes use their loaded revision. Stale writes return HTTP 409 instead of overwriting concurrent changes.

### Security and operations

The transport bounds request bodies and BibTeX source size, applies layered client-IP and authenticated-user rate limits, and emits `X-Request-ID` with every response. Structured logs exclude request bodies, email addresses, and BibTeX content. Production Caddy configuration keeps `/metrics` private and applies the documented proxy, header, timeout, and resource boundaries.

## Verification

Build the native extension, run the backend tests, and build the backend wheel from the repository root:

```bash
uv run poe test-backend
uv run poe build-backend
```

PostgreSQL integration tests run when `BIBMGR_TEST_POSTGRES_URL` points to a disposable test database. The main CI workflow supplies this database automatically.

## Further reading

- [API and native boundary](../docs/api.md)
- [Authentication and CSRF](../docs/authentication.md)
- [Database schema and transactions](../docs/database.md)
- [Local development](../docs/local-development.md)
- [Production operations](../docs/operations.md)
