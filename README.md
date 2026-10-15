<p style="text-align: center"><img src="docs/assets/bibmgr-logo.svg" alt="BibMgR Logo" width=100%></p>

**BibMgR** is a BibTeX reference manager for maintaining a shared bibliography. The web application lets users collect, search, validate, edit, and export references, with email authentication and revision history. A CLI and Slack app provide additional ways to validate and format BibTeX using the same Rust core.

## Features

- **Shared reference library:** register BibTeX by pasting text or uploading a file, then search and edit stored references.
- **Validation and safe fixes:** inspect diagnostics and preview corrections while preserving the original BibTeX source.
- **Configurable export:** format references for different publication conventions using built-in or custom profiles.
- **Duplicate review:** compare normalized titles, identifiers, and supporting fields, with configurable warnings, confirmation, or rejection.
- **Revision history:** review changes and restore earlier versions, including deleted references.

Registration preserves the submitted source. Fixes and export are explicit operations, so storing a reference does not silently reformat it. Validation policies, export profiles, and duplicate handling can be configured independently.

## Run locally

To build and run the web application from source, install:

- `uv` for the Python environment and development tasks.
- Rust 1.88 or later for the shared core and Python extension.
- Node.js 22.12 or later within the 22.x release line, with npm 10 or later, for the frontend.

PostgreSQL 18 stores the library, and Mailpit captures login emails during development. The example below starts both through Docker Compose; [Local development](docs/local-development.md) also covers macOS without Docker and external services. Python 3.11–3.13 is supported, with 3.12 selected by default for development.

```bash
git clone https://github.com/EhimeNLP/bibmgr.git
cd bibmgr

uv sync
uv run poe setup
uv run poe dev-services-up
uv run poe db-migrate
uv run poe dev
```

The first build downloads the search dictionary and requires network access. See [Development tools](docs/local-development.md#development-tools) for caching it across builds.

Open the web app at `http://127.0.0.1:5173/`. For the first login, enter an address such as `dev@example.test`, retrieve its verification code from Mailpit at `http://127.0.0.1:8025/`, and enter the code in the app. The account is created on verification. Use the add button to register BibTeX, then select a reference to inspect or edit it and choose an export profile when exporting.

The backend API documentation is available at `http://127.0.0.1:8000/docs`. Connection settings, authentication options, separate server commands, and service shutdown are covered in [Local development](docs/local-development.md).

## Other interfaces

### CLI

The CLI supports file-based validation, safe fixes, export, and duplicate comparison within a document:

```bash
bibmgr lint references.bib
bibmgr fix references.bib --safe --dry-run
bibmgr export references.bib --output references.exported.bib
```

See [Command-line interface](docs/cli.md) for installation, profiles, JSON output, and exit codes.

### Slack app

Send a BibTeX entry in a channel mention or direct message, choose an export profile, and receive the formatted entry with any remaining warnings. The app runs in Socket Mode, separately from the web application.

See [Slack app](docs/slack.md) for app creation, tokens, language settings, and deployment.

## Development

The Rust core is shared by the CLI and Python bindings. FastAPI provides the web API, PostgreSQL stores the library and audit history, and Vue provides the interface. See [Architecture](docs/architecture.md) for component boundaries and the processing model.

From a configured development environment, run the test suite or the integrated checks:

```bash
uv run poe test
uv run poe check
```

List all tasks with `uv run poe --help`. The [Rust API](docs/api.md), [Python API](docs/python-api.md), and [GUI integration](docs/gui-integration.md) guides describe how to use the core in other applications.

## Deployment

The production Compose configuration supports either HTTPS managed by Caddy or an external reverse proxy. It runs the web application, backend, and PostgreSQL together; the Slack app is deployed separately. Source and wheel-based deployment options are also available.

See [Production operations](docs/operations.md) for deployment, health checks, account management, and backups, and [Authentication](docs/authentication.md) for login and session configuration.

## Further documentation

| Topic | Guide |
| --- | --- |
| Validation policies, export profiles, and duplicate handling | [Configuration](docs/configuration.md) |
| Storage, search, and revision history | [Database](docs/database.md) |
| Extending validation rules | [Adding rules](docs/adding-rules.md) |
| Venue names and aliases | [Venue registry](docs/venues.md) |
| Preparing bibliography data from papers | [Initialization pipelines](pipeline/README.md) |

## License

The BibMgR application and libraries are distributed under the [MIT License](LICENSE).
