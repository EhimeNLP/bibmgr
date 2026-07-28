# Frontend

## Overview

The Vue 3 + TypeScript client provides public reference search, BibTeX validation/fixes, reference detail, and profile-based export. Database writes and operator history require an authenticated email-code session with CSRF protection.

The interface currently supports:

- paginated free-text and structured search by year, author, venue, identifier, entry type, creator, updated range, and sort order;
- one profile-controlled preview that exports with the laboratory profile by default;
- citation-context display;
- manual and `.bib` batch registration that stores accepted source without profile-driven rewriting while showing an independent profile-selectable output preview;
- revision-checked edit and delete actions;
- paginated append-only history and confirmation-based restore;
- login through the laboratory domain or an exact operator-approved external address;
- explicit sign-out confirmation and automatic login recovery after session expiry;
- keyboard focus containment in modal dialogs and Playwright/axe accessibility coverage.

## Runtime data flow

The browser calls `/api`, which Vite proxies to `http://localhost:8000` during development and Caddy proxies to the backend in production. Initial loading and searches call `GET /references/page` and retain `total`, `limit`, and `offset` for pagination. Read-only operations do not send authentication credentials.

Protected requests send the HttpOnly session cookie with `credentials: "include"` and the session-bound `X-CSRF-Token`. A protected HTTP 401 clears remembered authentication and opens the login dialog. Update sends the observed `source_revision`; delete sends the observed revision as quoted `If-Match`; restore sends the observed history-head revision.

## Important modules

- `src/App.vue`: search/page/session state and responsive master-detail navigation.
- `src/components/SearchBar.vue`: free-text and structured filters.
- `src/components/ReferenceDetail.vue`: metadata, citation contexts, and one profile-controlled BibTeX preview.
- `src/components/RegistrationPanel.vue`: manual and `.bib` file registration.
- `src/components/ReferenceActions.vue`: Apple-style More menu, edit sheet, and destructive confirmation.
- `src/components/HistoryPanel.vue`: active/deleted histories and append-only restore.
- `src/components/AuthMenu.vue`: email-code login and sign-out confirmation.
- `src/api/`: typed transport and response normalization.
- `src/types/`: authentication, history, BibTeX, and reference DTOs.

## Development

Install locked dependencies and start the frontend from the repository root:

```bash
uv run poe setup-frontend
uv run poe dev-frontend
```

The complete local stack also needs PostgreSQL, Mailpit, migrations, and the backend as described in [`../docs/local-development.md`](../docs/local-development.md).

## Verification

Run lint, TypeScript checks, unit/component tests, and a production build:

```bash
uv run poe check-frontend
uv run poe test-frontend
uv run poe build-frontend
```

The Playwright E2E suite uses PostgreSQL, Mailpit, a migrated database, and Chromium. It verifies the real email-code login flow, registration, search, edit, delete, history restore, and critical/serious axe findings:

```bash
cd frontend
npx playwright install chromium
npm run test:e2e
```

## API configuration

`VITE_API_BASE_URL` changes the API base URL at build time. It defaults to `/api`, which is the recommended same-origin configuration for session cookies and CSRF.

The registration contract is documented in [`fe-registration.md`](fe-registration.md).
