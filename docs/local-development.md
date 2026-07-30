# Local development

## Development tools

Install the following tools before running the application from source:

- `uv`: provisions the Python environment, installs locked dependencies, and runs Poe tasks; the application supports Python 3.11–3.13, while `.python-version` selects 3.12 only as the default contributor version
- Rust 1.86 or later (`rustc` and `cargo`): builds the Rust workspace and `bibmgr_native`
- Node.js 22.12 or later in the Node.js 22 release line, with npm 10 or later: manages Vue frontend dependencies, the development server, tests, and builds

If all of the following commands succeed, you can proceed with the application setup:

```bash
uv --version
rustc --version
cargo --version
node --version
npm --version
```

Installing the Rust toolchain through `rustup` is recommended. Because `npm` is bundled with Node.js, it normally does not require a separate installation.

In addition to the BibMgR application, local development requires two services:

- PostgreSQL: stores users, sessions, references, and audit history
- Mailpit: captures login codes sent during development

Docker is one way to run these services, but it is not an application requirement. Without Docker, install the same services directly on the local machine.

## Using Docker

Start PostgreSQL and Mailpit, then apply the database migrations:

```bash
uv run poe dev-services-up
uv run poe db-migrate
uv run poe dev
```

## macOS without Docker

Install PostgreSQL 18 and Mailpit with Homebrew:

```bash
brew install postgresql@18 mailpit
brew services start postgresql@18
brew services start mailpit
```

Because `postgresql@18` is keg-only, add its binary directory to `PATH` in the shell that runs the commands:

```bash
export PATH="/opt/homebrew/opt/postgresql@18/bin:$PATH"
```

Create the development role and database:

```bash
createuser --login --pwprompt bibmgr
createdb --owner=bibmgr bibmgr
```

When prompted for a password, enter `bibmgr` to match the default connection settings. If you use a different password, configure the connection in the shell that starts the application:

```bash
export BIBMGR_DATABASE_URL="postgresql+psycopg://bibmgr:your-password@127.0.0.1:5432/bibmgr"
```

Apply the migrations and start the backend and frontend:

```bash
uv run poe db-migrate
uv run poe dev
```

## Verification

After startup, use the following URLs:

- Frontend: `http://127.0.0.1:5173/`
- Backend: `http://127.0.0.1:8000/`
- Backend readiness: `http://127.0.0.1:8000/readyz`
- Mailpit inbox: `http://127.0.0.1:8025/`

For the first login, enter a development address on the permitted domain, such as `dev@ai.cs.ehime-u.ac.jp`. The address does not need to exist because Mailpit captures the message locally instead of delivering it externally. Find the eight-digit code in the Mailpit inbox and enter it; the account is created when the address is verified for the first time. After login, use the add button to register BibTeX.

Using the application requires login. Read-only operations, including search, reference details, BibTeX analysis, fix calculation, and export, also require a valid session. Registering, editing, deleting, and restoring references additionally use the CSRF token managed by the frontend.

To test a development address outside the laboratory domain, list the complete address explicitly. The following setting permits only `visitor@example.org`, not other addresses on the same domain:

```bash
export BIBMGR_AUTH_ALLOWED_EMAILS="visitor@example.org"
uv run poe dev
```

## Stopping services

If the services were started with Docker Compose:

```bash
docker compose down
```

If the services were started through Homebrew:

```bash
brew services stop mailpit
brew services stop postgresql@18
```

Stopping the services preserves the PostgreSQL data. To return the development database to an empty current schema, run the following command against the local database and type the displayed database name to confirm:

```bash
uv run poe db-reset
```

## Using external services

Instead of installing PostgreSQL and Mailpit locally, you can configure an existing PostgreSQL server and SMTP relay:

```bash
export BIBMGR_DATABASE_URL="postgresql+psycopg://user:password@db.example/bibmgr"
export BIBMGR_SMTP_HOST="smtp.example"
export BIBMGR_SMTP_PORT="587"
export BIBMGR_SMTP_USERNAME="smtp-user"
export BIBMGR_SMTP_PASSWORD="smtp-password"
export BIBMGR_SMTP_STARTTLS="true"

uv run poe db-migrate
uv run poe dev
```

When using a real SMTP relay, login codes are delivered to the entered email address. Do not store credentials in the repository.

## Local backups

With the PostgreSQL 18 `pg_dump` client available on `PATH`, the following task creates a custom-format backup under `backups/` with permissions `0600`:

```bash
uv run poe db-backup
```

Because restoration replaces the current database contents, specify both the input file and the target database name:

```bash
uv run bibmgr-ops restore \
  --input backups/bibmgr-YYYYMMDDTHHMMSSZ.dump \
  --confirm-database bibmgr
```
