# bibmgr backend integration example

This package is intentionally a transport adapter. It calls `bibmgr_native` for analysis, fixes, registration validation, and export and contains no BibTeX parser, regular-expression rule, or policy decision.

From the repository root, prepare the locked Python, native-module, and frontend dependencies without activating a virtual environment:

```bash
uv run poe setup
```

Run the reload-enabled backend development server with the repository task:

```bash
uv run poe dev-backend
```

The service listens on `127.0.0.1:8000` and exposes:

- `POST /bibtex/analyze`
- `POST /bibtex/fixes/apply`
- `POST /bibtex/registration/validate`
- `POST /bibtex/export`

Explicit fix requests include the `source_revision` returned by analysis. The native layer rejects a stale revision before resolving any fix ID against the current source.

Authentication, database persistence, and transactions are deployment-specific and intentionally omitted. A real registration handler must call `validate_for_registration` again on the server inside its transaction; it must not trust a previous browser result.
