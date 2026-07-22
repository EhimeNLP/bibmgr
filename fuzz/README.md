# Fuzz targets

This directory is a standalone cargo-fuzz workspace so it does not become a normal release package.

```console
cargo install cargo-fuzz
cargo fuzz build
cargo fuzz run parser_roundtrip
cargo fuzz run malformed_analysis
cargo fuzz run text_edits
```

- `parser_roundtrip` runs strict and tolerant parsing and requires exact source recovery for every valid UTF-8 string produced from fuzzer bytes.
- `malformed_analysis` exercises the complete tolerant core pipeline and its DTO serialization.
- `text_edits` sends valid and invalid ranges/revisions through the checked edit engine and verifies successful edits are UTF-8 and have the reported revision.

Crashing inputs belong under `fuzz/artifacts/` during investigation; minimized, permanent regressions should be converted into ordinary crate fixtures.
