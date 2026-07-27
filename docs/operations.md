# Production operations

## Deployment topology

`compose.production.yaml` builds the Rust-backed FastAPI service and the Vue/Caddy web service, runs PostgreSQL 18, applies Alembic migrations as a one-shot dependency, and exposes only Caddy on ports 80 and 443. Caddy serves the single-page application, proxies `/api/` to the backend, obtains TLS certificates for a public hostname, and applies baseline security headers.

Copy `.env.production.example` to `.env.production` and set the public hostname and SMTP relay. Create `deploy/secrets/database_password`, `deploy/secrets/database_url`, `deploy/secrets/auth_secret`, and `deploy/secrets/smtp_password` as described in `deploy/secrets/README.md`. The database URL must use the Compose hostname `postgres`, and an external-domain user must be listed by complete address in `BIBMGR_AUTH_ALLOWED_EMAILS`.

```bash
cp .env.production.example .env.production
mkdir -p -m 700 deploy/secrets
openssl rand -hex 32 > deploy/secrets/database_password
openssl rand -hex 32 > deploy/secrets/auth_secret
chmod 600 deploy/secrets/database_password deploy/secrets/auth_secret
```

Write a matching URL to `deploy/secrets/database_url`, create the SMTP password file, then validate and start the project:

```bash
docker compose --env-file .env.production \
  -f compose.production.yaml config
docker compose --env-file .env.production \
  -f compose.production.yaml up --detach --build --wait
```

The backend refuses production startup without an authentication secret and an explicit SMTP host. The production cookie is Secure and HttpOnly, so login must be tested through the HTTPS site rather than the backend port.

## Health, logs, and metrics

`GET /api/healthz` checks process liveness and `GET /api/readyz` checks database connectivity. Container health uses readiness. `GET /api/metrics` exposes Prometheus text counters and request-duration sums/counts with method, normalized route, and status labels.

Every response carries `X-Request-ID`; a valid incoming ID is preserved and an invalid or missing value is replaced. Request logs are structured JSON and contain the ID, method, normalized route, status, and duration. They deliberately omit query values, bodies, email addresses, login codes, and BibTeX.

At minimum, alert on persistent readiness failure, repeated HTTP 5xx responses, backup timer failure, and an unexpectedly old latest backup. The Caddy and backend container logs are available through:

```bash
docker compose --env-file .env.production \
  -f compose.production.yaml logs --follow web backend
```

## Accounts and authentication retention

Account rows are retained for audit identity. Disable a departed user instead of deleting the row; disabling also revokes every active session.

```bash
docker compose --env-file .env.production \
  -f compose.production.yaml run --rm --no-deps \
  backend bibmgr-admin users
docker compose --env-file .env.production \
  -f compose.production.yaml run --rm --no-deps \
  backend bibmgr-admin disable member@ai.cs.ehime-u.ac.jp
docker compose --env-file .env.production \
  -f compose.production.yaml run --rm --no-deps \
  backend bibmgr-admin enable member@ai.cs.ehime-u.ac.jp
docker compose --env-file .env.production \
  -f compose.production.yaml run --rm --no-deps \
  backend bibmgr-admin revoke-sessions member@ai.cs.ehime-u.ac.jp
```

Run `bibmgr-admin cleanup-auth --dry-run` to inspect retention, then run it without `--dry-run` to remove challenges expired for over one day and expired/revoked sessions retained for over thirty days. The supplied `bibmgr-auth-cleanup.timer` schedules this daily.

## Backup

The backend image includes the PostgreSQL 18 client so its dump format matches the server major version. The backup command writes a custom-format dump to a named Compose volume, uses a temporary file followed by atomic rename, and sets mode `0600`.

```bash
docker compose --env-file .env.production \
  -f compose.production.yaml run --rm --no-deps \
  backend bibmgr-ops backup --output-dir /var/lib/bibmgr/backups
```

Copy a dump to encrypted off-host storage. Container-local or single-host copies do not protect against host loss. The supplied `bibmgr-backup.timer` runs daily at approximately 03:15, but the operator must also configure off-host transfer and retention appropriate to laboratory policy.

Inspect the named volume or copy a selected dump out with a temporary container:

```bash
docker compose --env-file .env.production \
  -f compose.production.yaml run --rm --no-deps \
  backend ls -l /var/lib/bibmgr/backups
docker compose --env-file .env.production \
  -f compose.production.yaml run --rm --no-deps \
  -v /absolute/export/directory:/export \
  backend cp /var/lib/bibmgr/backups/SELECTED.dump /export/
```

## Restore and recovery drill

A restore deletes/recreates objects represented in the dump. Take a fresh backup first, stop the backend to close application connections, mount one reviewed dump read-only, and require the exact target database name:

```bash
docker compose --env-file .env.production \
  -f compose.production.yaml stop backend
docker compose --env-file .env.production \
  -f compose.production.yaml run --rm --no-deps \
  -v /absolute/path/backup.dump:/restore/backup.dump:ro \
  backend bibmgr-ops restore \
  --input /restore/backup.dump \
  --confirm-database bibmgr
docker compose --env-file .env.production \
  -f compose.production.yaml up --detach --wait backend web
```

Verify `/api/readyz`, public search, one authenticated write, and a history restore after recovery. Perform this drill against an isolated staging database regularly; a backup is not operationally proven until restore has succeeded.

## systemd

The files under `deploy/systemd/` assume the checkout and `.env.production` live at `/opt/bibmgr`. Install the service and timers, reload systemd, and enable them:

```bash
sudo cp deploy/systemd/bibmgr* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bibmgr.service
sudo systemctl enable --now bibmgr-auth-cleanup.timer bibmgr-backup.timer
```

Adjust `WorkingDirectory`, backup schedule, off-host transfer, and monitoring for the deployment host before enabling the units.
