# Command-line interface

The installed executable is `bibmgr`. Every command delegates analysis, validation, editing, and export to `bibmgr-core`.

## Installation

To use BibTeX validation from the command line, install the CLI directly from GitHub without cloning the repository:

```bash
cargo install --git https://github.com/EhimeNLP/bibmgr.git --locked bibmgr-cli
bibmgr --version
```

Alternatively, Linux and macOS users can install a prebuilt binary without requiring Rust:

```bash
curl -LsSf https://github.com/EhimeNLP/bibmgr/releases/latest/download/bibmgr-installer.sh | sh
```

The installer verifies the release archive with SHA-256 and writes the `bibmgr` executable to `~/.local/bin` by default. If that directory is not already on `PATH`, add it in your shell configuration:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Set `BIBMGR_INSTALL_DIR` to select another destination, or `BIBMGR_VERSION` to install a specific release. A version may be written with or without the leading `v`.

```bash
curl -LsSf https://github.com/EhimeNLP/bibmgr/releases/latest/download/bibmgr-installer.sh |
  BIBMGR_INSTALL_DIR="$HOME/bin" BIBMGR_VERSION=v0.1.7 sh
```

Windows x86_64 users can download `bibmgr-x86_64-pc-windows-msvc.zip` from the [latest release](https://github.com/EhimeNLP/bibmgr/releases/latest), extract `bibmgr.exe`, and place it on `PATH`.

If you clone the repository for development or inspection, you can install from the local path:

```bash
git clone https://github.com/EhimeNLP/bibmgr.git
cd bibmgr
cargo install --locked --path crates/bibmgr-cli
```

To build a release binary without installing it, use the Poe task:

```bash
uv run --frozen poe build-cli
./target/release/bibmgr --version
```

## Commands

```console
bibmgr lint FILE
bibmgr lint FILE --format json
bibmgr fix FILE
bibmgr fix FILE --safe
bibmgr fix FILE --fix-id BIB-SYNTAX-004:0 --source-revision sha256:...
bibmgr fix FILE --safe --fix-id BIB-SYNTAX-004:0 --source-revision sha256:...
bibmgr fix FILE --dry-run
bibmgr export FILE
bibmgr export FILE --venue-name abbreviated
bibmgr export FILE --profile classical-bst
bibmgr export FILE --format json
bibmgr inspect FILE --ast
bibmgr inspect FILE --cst
```

`-` denotes standard input where supported. A mutating `fix` writes only after the complete operation succeeds; `--dry-run` writes a diff and never changes the file. With no `--fix-id`, `fix` applies all safe fixes. It uses deterministic non-conflicting batches and reanalyzes after each batch, so initially overlapping safe fixes are replanned against the new source revision.

`--fix-id ID` is repeatable and selects exactly those fixes. It requires the `--source-revision` returned by the analysis that produced those IDs; stale revisions are rejected before planning. An explicit selection may include confirmation-required or unsafe fixes; the caller is responsible for obtaining any required confirmation. Combining explicit IDs with `--safe` rejects every selected fix that is not classified as safe.

`lint --format json` and `export --format json` each write exactly one schema-v1 DTO to stdout. Progress, terminal decoration, and errors go to stderr so stdout remains machine-readable. Ranges are UTF-8 byte offsets. JSON fields and ordering match PyO3 DTOs.

`inspect --cst` and `inspect --ast` each emit a versioned JSON envelope. Both include `schema_version` and `source_revision`; their payload is named `document` and `bibliography`, respectively.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Operation succeeded and there are no blocking diagnostics |
| 1 | Analysis completed and at least one diagnostic is blocking |
| 2 | Invalid CLI usage, unreadable input, unwritable output, or invalid configuration |
| 3 | Internal invariant failure or unexpected adapter error |

Warnings alone do not determine the exit status; the resolved policy's `blocking` decision does. JSON output is still emitted on code 1.

## Profiles and configuration

The default profile is `modern` for lint, fix, and export. It excludes optional profile-convention rules. Use `--profile ID` to select another embedded profile. The standalone CLI accepts embedded profiles only; deployment-specific profiles are added and applied through the web application or supplied directly through the Python API as described in [Configuration](configuration.md). `--venue-name full|abbreviated` selects venue rendering independently of the profile and defaults to `full`; it affects conference, journal, and other venue-derived fields. An invalid profile or venue-name value is an exit-code-2 configuration error.

## Automation examples

```console
# Human-readable check
bibmgr lint bibliography.bib

# Stable CI payload
bibmgr lint bibliography.bib --format json > lint.json

# Preview byte-preserving safe edits
bibmgr fix bibliography.bib --safe --dry-run

# Generate a separate artifact for a classical BibTeX style
bibmgr export bibliography.bib --profile classical-bst > submission.bib

# Capture the generated source and export metadata as one stable DTO
bibmgr export bibliography.bib --format json > export.json
```

Export writes a newly optimized document for the selected output profile; it is not an in-place lint fix. With `--output`, the generated BibTeX is written to that file, while `--format json` still writes the result DTO to stdout when requested.

## Duplicate candidates

```sh
bibmgr duplicates references.bib
bibmgr duplicates references.bib --policy duplicate-policy.json
```

This read-only command compares entries inside one input document and emits `{"schema_version":"1","findings":[...]}` using the same Rust engine as Web registration. It does not connect to a database. `--policy` accepts the duplicate action JSON described in [Configuration](configuration.md#duplicate-comparison-and-registration-actions). With the default policy, title and citation-key matches are warnings; exact DOI or arXiv matches reject. Exit status is 1 for `confirm` or `reject` findings, 0 for warnings/no matches, and 2 for invalid syntax/configuration or exceeded limits.
