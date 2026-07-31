# Production operations

## Deployment topology

`compose.production.yaml` contains the shared Rust-backed FastAPI service, Vue/Caddy web service, PostgreSQL 18 service, and one-shot Alembic migration job. It intentionally publishes no host ports. Select exactly one deployment override:

- `compose.production.direct.yaml` publishes ports 80 and 443 and lets Caddy obtain and renew certificates for `BIBMGR_SITE_ADDRESS`.
- `compose.production.proxy.yaml` publishes one HTTP origin port for an external TLS-terminating reverse proxy. `BIBMGR_BASE_PATH` scopes the frontend, API, and authentication cookie to the externally assigned path.

Copy `.env.production.example` to `.env.production` and set the values for the selected mode, allowed email domain, and SMTP service. In proxy mode, bind the origin to loopback when the proxy runs on the same host, or to the specific private interface reachable by a remote proxy. Create `deploy/secrets/database_password`, `deploy/secrets/database_url`, `deploy/secrets/auth_secret`, and `deploy/secrets/smtp_password` as described in `deploy/secrets/README.md`. The database URL must use the Compose hostname `postgres`, and an external-domain user must be listed by complete address in `BIBMGR_AUTH_ALLOWED_EMAILS`.

```bash
cp .env.production.example .env.production
mkdir -p -m 700 deploy/secrets
openssl rand -hex 32 > deploy/secrets/database_password
openssl rand -hex 32 > deploy/secrets/auth_secret
touch deploy/secrets/smtp_password
chmod 600 \
  deploy/secrets/database_password \
  deploy/secrets/auth_secret \
  deploy/secrets/smtp_password
```

Write a matching URL to `deploy/secrets/database_url`. Put the SMTP account password in `deploy/secrets/smtp_password`, or leave the file empty only when using an unauthenticated private relay with `BIBMGR_SMTP_SECURITY=plain`. Validate and start one mode with its dedicated Poe tasks:

```bash
# Public Caddy with automatic HTTPS
uv run poe prod-direct-config
uv run poe prod-direct-up

# HTTP origin behind an external reverse proxy
uv run poe prod-proxy-config
uv run poe prod-proxy-up
```

For subsequent raw Compose commands, select the same override consistently:

```bash
export BIBMGR_DEPLOYMENT_MODE=proxy
docker compose --env-file .env.production \
  -f compose.production.yaml \
  -f "compose.production.${BIBMGR_DEPLOYMENT_MODE}.yaml" ps
```

Changing `BIBMGR_BASE_PATH` requires rebuilding the web image because the path is embedded into the frontend assets. The external proxy must preserve that prefix when forwarding requests. The backend refuses production startup without an authentication secret, allowed email domain, sender address, SMTP host, and SMTP security mode. The production cookie is Secure and HttpOnly, so login must be tested through the public HTTPS URL rather than the internal HTTP origin.

For example, a reverse proxy on the same host can forward a public subpath to a loopback-only origin:

```dotenv
BIBMGR_BASE_PATH=/bibmgr
BIBMGR_WEB_BIND_ADDRESS=127.0.0.1
BIBMGR_WEB_PORT=8080
```

With a public URL such as `https://bibmgr.example.com/bibmgr/`, the proxy forwards that path to `http://127.0.0.1:8080/bibmgr/`. When the proxy runs on another host, replace the loopback address with a private interface and restrict that origin port to the proxy host at the network boundary.

## Health, logs, and metrics

`GET /api/healthz` checks process liveness and `GET /api/readyz` checks database connectivity in direct mode. Prefix these paths with `BIBMGR_BASE_PATH` in proxy mode, for example `/bibmgr/api/readyz`. Container health uses the backend's unprefixed readiness endpoint. `GET /api/metrics` exposes Prometheus text counters and request-duration sums/counts with method, normalized route, and status labels.

Every response carries `X-Request-ID`; a valid incoming ID is preserved and an invalid or missing value is replaced. Request logs are structured JSON and contain the ID, method, normalized route, status, and duration. They deliberately omit query values, bodies, email addresses, login codes, and BibTeX.

At minimum, alert on persistent readiness failure, repeated HTTP 5xx responses, backup timer failure, and an unexpectedly old latest backup. The Caddy and backend container logs are available through:

```bash
docker compose --env-file .env.production \
  -f compose.production.yaml \
  -f "compose.production.${BIBMGR_DEPLOYMENT_MODE}.yaml" \
  logs --follow web backend
```

## Accounts and authentication retention

Account rows are retained for audit identity. Disable a departed user instead of deleting the row; disabling also revokes every active session.

```bash
docker compose --env-file .env.production \
  -f compose.production.yaml \
  -f "compose.production.${BIBMGR_DEPLOYMENT_MODE}.yaml" \
  run --rm --no-deps \
  backend bibmgr-admin users
docker compose --env-file .env.production \
  -f compose.production.yaml \
  -f "compose.production.${BIBMGR_DEPLOYMENT_MODE}.yaml" \
  run --rm --no-deps \
  backend bibmgr-admin disable member@example.com
docker compose --env-file .env.production \
  -f compose.production.yaml \
  -f "compose.production.${BIBMGR_DEPLOYMENT_MODE}.yaml" \
  run --rm --no-deps \
  backend bibmgr-admin enable member@example.com
docker compose --env-file .env.production \
  -f compose.production.yaml \
  -f "compose.production.${BIBMGR_DEPLOYMENT_MODE}.yaml" \
  run --rm --no-deps \
  backend bibmgr-admin revoke-sessions member@example.com
```

Run `bibmgr-admin cleanup-auth --dry-run` to inspect retention, then run it without `--dry-run` to remove challenges expired for over one day and expired/revoked sessions retained for over thirty days. The supplied `bibmgr-auth-cleanup.timer` schedules this daily.

## Backup

The backend image includes the PostgreSQL 18 client so its dump format matches the server major version. The backup command writes a custom-format dump to a named Compose volume, uses a temporary file followed by atomic rename, and sets mode `0600`.

```bash
docker compose --env-file .env.production \
  -f compose.production.yaml \
  -f "compose.production.${BIBMGR_DEPLOYMENT_MODE}.yaml" \
  run --rm --no-deps \
  backend bibmgr-ops backup --output-dir /var/lib/bibmgr/backups
```

Copy a dump to encrypted off-host storage. Container-local or single-host copies do not protect against host loss. The supplied `bibmgr-backup.timer` runs daily at approximately 03:15, but the operator must also configure off-host transfer and retention appropriate to local policy.

Inspect the named volume or copy a selected dump out with a temporary container:

```bash
docker compose --env-file .env.production \
  -f compose.production.yaml \
  -f "compose.production.${BIBMGR_DEPLOYMENT_MODE}.yaml" \
  run --rm --no-deps \
  backend ls -l /var/lib/bibmgr/backups
docker compose --env-file .env.production \
  -f compose.production.yaml \
  -f "compose.production.${BIBMGR_DEPLOYMENT_MODE}.yaml" \
  run --rm --no-deps \
  -v /absolute/export/directory:/export \
  backend cp /var/lib/bibmgr/backups/SELECTED.dump /export/
```

## Restore and recovery drill

A restore deletes/recreates objects represented in the dump. Take a fresh backup first, stop the backend to close application connections, mount one reviewed dump read-only, and require the exact target database name:

```bash
docker compose --env-file .env.production \
  -f compose.production.yaml \
  -f "compose.production.${BIBMGR_DEPLOYMENT_MODE}.yaml" \
  stop backend
docker compose --env-file .env.production \
  -f compose.production.yaml \
  -f "compose.production.${BIBMGR_DEPLOYMENT_MODE}.yaml" \
  run --rm --no-deps \
  -v /absolute/path/backup.dump:/restore/backup.dump:ro \
  backend bibmgr-ops restore \
  --input /restore/backup.dump \
  --confirm-database bibmgr
docker compose --env-file .env.production \
  -f compose.production.yaml \
  -f "compose.production.${BIBMGR_DEPLOYMENT_MODE}.yaml" \
  up --detach --wait backend web
```

Verify the public readiness URL, authenticated search, one authenticated write, and a history restore after recovery. Perform this drill against an isolated staging database regularly; a backup is not operationally proven until restore has succeeded.

## systemd

The files under `deploy/systemd/` assume the checkout and `.env.production` live at `/opt/bibmgr`. They default to direct mode. For proxy mode, create `/etc/default/bibmgr` before starting the units:

```bash
BIBMGR_DEPLOYMENT_MODE=proxy
```

Install the service and timers, reload systemd, and enable them:

```bash
sudo cp deploy/systemd/bibmgr* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bibmgr.service
sudo systemctl enable --now bibmgr-auth-cleanup.timer bibmgr-backup.timer
```

Adjust `WorkingDirectory`, backup schedule, off-host transfer, and monitoring for the deployment host before enabling the units.
