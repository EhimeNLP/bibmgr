# Authentication and audit

## Access policy

Reference search, reference detail, BibTeX analysis, fix calculation, registration validation, and export are public because they do not change server state. `POST /references`, `PUT /references/{id}`, and `DELETE /references/{id}` require authentication even though other computational endpoints also use `POST`.

## Passwordless email login

The same email-code flow handles account creation and later login:

1. `POST /auth/email/start` accepts an email address and always returns the same HTTP 202 success payload for an ineligible address.
2. The parsed domain must exactly equal `BIBMGR_AUTH_EMAIL_DOMAIN`, which defaults to `ai.cs.ehime-u.ac.jp`, or the complete normalized address must appear in `BIBMGR_AUTH_ALLOWED_EMAILS`.
3. An eight-digit code is sent by SMTP. Its HMAC digest, not the code, is stored.
4. `POST /auth/email/verify` accepts the code once within ten minutes and creates the user on first verification.
5. The backend creates a random opaque session, stores only its SHA-256 digest, and sets the raw value in an HttpOnly browser cookie.

Each code permits at most five failed verification attempts. Requests have a per-address cooldown and an hourly per-IP limit. PostgreSQL transaction-scoped advisory locks serialize reservation of the address and IP request slots, and the challenge is committed before SMTP delivery begins. A newer code invalidates older unused codes. If SMTP delivery fails, the reserved challenge is marked consumed while its request continues to count toward the cooldown and hourly limit.

## Browser session and CSRF

Sessions expire after seven days and can be revoked by `POST /auth/logout`. `GET /auth/session` returns the authenticated user and a session-bound CSRF token so the Vue client can restore its in-memory authentication state after a reload.

The frontend never invokes logout directly from the account button. It first presents a confirmation dialog and calls `POST /auth/logout` only after explicit confirmation; cancellation leaves the session unchanged.

Every protected write sends the session cookie and `X-CSRF-Token`. The cookie is host-only, HttpOnly, `SameSite=Lax`, and uses `Secure` when `BIBMGR_COOKIE_SECURE=true` or `BIBMGR_ENV=production`. `BIBMGR_COOKIE_PATH` can restrict it to an application subpath on a shared host. Production traffic must use HTTPS and should serve the frontend and API from one origin.

## Operator audit

`BIBMGR_AUTH_ALLOWED_EMAILS` is an additive exception list for people who do not have a laboratory-domain address. Values are comma- or newline-separated complete addresses such as `collaborator@example.org`. A bare domain, suffix, or wildcard does not match anyone, so each external person must be named explicitly.

Each new reference stores `created_by_user_id` and `updated_by_user_id`. An update changes only `updated_by_user_id`. The same transaction advances a persistent history head and appends a numbered `reference_audit_events` revision for every create, update, citation-context addition, delete, and restore operation.

Each non-deleted revision stores the exact persisted BibTeX, complete semantic snapshot, reference row, contributors, identifiers, URLs, and citation contexts. Compatibility keys for submitted and canonical BibTeX remain in the snapshot; new writes carry the same source in both, while legacy normalized revisions can retain different values. A delete revision stores the complete previous state and a null resulting state. Audit rows deliberately do not have a foreign key to the live reference because deletion must not erase or null the historical reference ID. PostgreSQL rejects updates and deletes against the audit table with an append-only trigger.

`POST /references/{id}/revert` restores a selected non-deleted snapshot and appends the result as a new revision; it never rewrites the selected revision or removes later revisions. The request includes the caller's observed history-head revision. A concurrent edit, delete, or restore advances the head and causes the stale request to fail with HTTP 409.

Users are disabled by setting `users.status` to `disabled` rather than deleting them, which preserves actor foreign keys and immediately invalidates their sessions.

Operators use `bibmgr-admin users`, `bibmgr-admin disable EMAIL`, `bibmgr-admin enable EMAIL`, and `bibmgr-admin revoke-sessions EMAIL` for account lifecycle management. `bibmgr-admin cleanup-auth` removes login challenges expired for more than one day and expired or revoked sessions retained for more than thirty days; production should schedule it daily.

## Development email

Start PostgreSQL and Mailpit, apply migrations, then run the application:

```bash
uv run poe dev-services-up
uv run poe db-migrate
uv run poe dev
```

The development SMTP endpoint is `127.0.0.1:1025` and the captured inbox is available at `http://127.0.0.1:8025/`. Mailpit is a development tool and must not be exposed as the production mail service.

Docker is not required. The [local development guide](local-development.md) documents how to run PostgreSQL and Mailpit directly on macOS, verify the first login code, and create a local development account.

## Production configuration

The backend reads:

| Variable | Purpose |
| --- | --- |
| `BIBMGR_ENV=production` | Enables production configuration checks and secure cookies |
| `BIBMGR_AUTH_SECRET` | Secret used to HMAC login codes and derive CSRF tokens |
| `BIBMGR_AUTH_SECRET_FILE` | File alternative to `BIBMGR_AUTH_SECRET` |
| `BIBMGR_AUTH_EMAIL_DOMAIN` | Exact allowed email domain |
| `BIBMGR_AUTH_ALLOWED_EMAILS` | Comma/newline-separated exact external addresses |
| `BIBMGR_SESSION_COOKIE` | Optional session-cookie name |
| `BIBMGR_COOKIE_PATH` | Session-cookie path, `/` by default |
| `BIBMGR_COOKIE_SECURE` | Explicit secure-cookie override |
| `BIBMGR_SMTP_HOST` | SMTP relay host |
| `BIBMGR_SMTP_PORT` | SMTP relay port |
| `BIBMGR_SMTP_USERNAME` | Optional SMTP username |
| `BIBMGR_SMTP_PASSWORD` | Optional SMTP password |
| `BIBMGR_SMTP_PASSWORD_FILE` | File alternative to the SMTP password; an empty file means no password |
| `BIBMGR_SMTP_STARTTLS` | Enable SMTP STARTTLS |
| `BIBMGR_EMAIL_FROM` | Authentication email sender |

An authentication secret supplied through `BIBMGR_AUTH_SECRET` or `BIBMGR_AUTH_SECRET_FILE` and an explicit `BIBMGR_SMTP_HOST` are mandatory when `BIBMGR_ENV=production`. Secrets must be provided through the deployment secret store rather than committed to the repository. The SMTP account should be restricted to sending the application's authentication email.
