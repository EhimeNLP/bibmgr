# WebAssembly API

`bibmgr-wasm` exposes BibMgR's analysis, safe fixes, registration validation, and export through a JSON API for JavaScript applications. It can be used in browser editors, Chrome extensions, and other tools that process BibTeX locally.

## Build

Install the `wasm32-unknown-unknown` Rust target, wasm-pack 0.13.1, and Node.js 22, then run:

```sh
python3 scripts/build_wasm.py
```

The package in `dist/wasm` contains the WebAssembly module, JavaScript bindings, TypeScript declarations, and package metadata.

## Usage

Initialize the module, then pass a JSON-encoded request to `invoke`. The returned string is a JSON response with either `{ok: true, result}` or `{ok: false, error: {code, message}}`.

```js
import init, { invoke } from './wasm/bibmgr.js';

await init();

const response = JSON.parse(invoke(JSON.stringify({
  operation: 'validate_registration',
  source: '@misc{example, title={Example}}',
  profile: 'archive',
  apply_safe_fixes: true,
})));

if (!response.ok) {
  throw new Error(response.error.message);
}

const { accepted, source, diagnostics } = response.result;
```

## Operations

| Operation | Request fields | Result |
| --- | --- | --- |
| `catalog` | none | Engine and schema versions, available export profiles |
| `analyze` | `source`, `profile` | Syntax, bibliography, diagnostics, and available fixes |
| `fix` | `source`, `profile` | Safely fixed source, diff, updated analysis, and applied fix IDs |
| `validate_registration` | `source`, `profile`, optional `apply_safe_fixes` (default `false`) | Registration decision, source, diagnostics, and bibliography |
| `export` | `source`, `profile`, `venue_name_style` (`full` or `abbreviated`) | Exported source, record count, applied fix IDs, and diagnostics |

For `analyze`, `fix`, and `validate_registration`, `profile` selects the validation or registration policy. For `export`, it selects an output profile from `catalog`.

## Validation and export

A successful API response (`ok: true`) means the request was processed. For registration validation, check `result.accepted` to determine whether the source satisfies the selected policy. Diagnostics include each rule's message, severity, blocking status, and source locations. Registration validation evaluates the supplied document; checking for duplicates in an existing library requires the library service.

For example, a Chrome extension can validate selected BibTeX with `apply_safe_fixes: true`, highlight blocking diagnostics when `accepted` is `false`, and export the returned source when validation passes. An export-profile selector can use the profiles returned by `catalog`. Export results include diagnostics for the generated source, which the application can inspect before offering a copy action.

## Source locations and limits

Diagnostic locations use UTF-8 byte ranges. Convert them to UTF-16 offsets when using JavaScript string indices or DOM selections. After applying fixes, display diagnostics against the returned source and its revision so that highlights refer to the correct text.

Input is limited to 2 MiB of UTF-8 text. Automatic fixes apply only changes classified as safe; changes requiring confirmation remain available for review through analysis results.
