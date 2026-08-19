# Frontend

The Vue 3 and TypeScript frontend provides the authenticated BibMgR workspace for reference search, BibTeX editing, validation, registration, history, configuration, and profile-based export. It consumes backend DTOs without reimplementing BibTeX rules or persistence decisions in the browser.

## Responsibilities

- Provide paginated free-text and structured reference search.
- Support manual and `.bib` batch registration while preserving submitted source.
- Render validation diagnostics, safe fixes, citation contexts, and profile-controlled export previews.
- Provide revision-checked edit, delete, history, and restore workflows.
- Manage email-code sessions, CSRF-protected writes, and session-expiry recovery.
- Edit shared export profiles and venue mappings with actor-attributed history.
- Maintain responsive, keyboard-accessible dialogs and critical-path axe coverage.

## Development

Run frontend tasks from the repository root. Install locked Node.js dependencies and launch the development server:

```bash
uv run poe setup-frontend
uv run poe dev-frontend
```

The frontend listens at `http://127.0.0.1:5173/`. Vite proxies API requests to the backend at `http://127.0.0.1:8000/`.

The complete application also needs PostgreSQL, Mailpit, migrations, the native extension, and the backend. Run `uv run poe dev` to start both application servers after preparing the services, or follow the [local development guide](../docs/local-development.md) for the full setup.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `BIBMGR_BASE_PATH` | `/` | Set Vite's build-time public base path for assets and API requests. |
| `VITE_API_BASE_URL` | Derived from the application base path | Override only the API base URL. |

A base path such as `/bibmgr` emits assets and default API requests below `/bibmgr/`. Same-origin API access is recommended because authentication uses an HttpOnly session cookie and state-changing requests use a session-bound CSRF token.

## Architecture

### Runtime data flow

The browser calls the `api` path below Vite's configured base path. Initial loading and searches use `GET /references/page` and retain `total`, `limit`, and `offset` for pagination. All protected requests include the session cookie with `credentials: "include"`; writes also include `X-CSRF-Token`.

A protected HTTP 401 clears remembered authentication and opens the login dialog. Updates send the observed `source_revision`, deletes send that revision as a quoted `If-Match`, and restores send the observed history-head revision. Profile selection changes only the exported preview and never the stored BibTeX source.

### Key modules

- `src/App.vue`: session, search, pagination, selection, and responsive navigation state.
- `src/components/SearchBar.vue`: free-text and structured filters.
- `src/components/ReferenceDetail.vue`: metadata, citation contexts, and BibTeX export preview.
- `src/components/RegistrationPanel.vue`: manual and `.bib` batch registration.
- `src/components/ReferenceActions.vue`: edit workflow and destructive confirmations.
- `src/components/HistoryPanel.vue`: active/deleted history and revision restore.
- `src/components/AuthMenu.vue`: email-code login and sign-out.
- `src/components/SettingsPanel.vue`: shared profile and venue configuration with audit history.
- `src/components/AppIcon.vue`: shared Bootstrap Icons boundary.
- `src/components/UnifiedDiff.vue`: accessible line-by-line history differences.
- `src/api/`: typed transport, authentication, and response normalization.
- `src/types/`: shared frontend DTO definitions.

## Verification

Run lint, TypeScript checks, unit/component tests, and a production build from the repository root:

```bash
uv run poe check-frontend
uv run poe test-frontend
uv run poe build-frontend
```

The Playwright E2E suite uses PostgreSQL, Mailpit, a migrated database, and Chromium. It covers the real email-code login flow, registration, search, edit, delete, history restore, and critical or serious axe findings:

```bash
cd frontend
npx playwright install chromium
npm run test:e2e
```

## Further reading

- [GUI behavior and integration](../docs/gui-integration.md)
- [Authentication and CSRF](../docs/authentication.md)
- [Local development](../docs/local-development.md)
- [Backend component](../backend/README.md)
