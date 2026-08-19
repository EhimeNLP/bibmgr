# Benchmarks

Criterion records complete-pipeline and source-edit baselines without adding benchmark dependencies to production crates.

```console
cargo bench --manifest-path benches/Cargo.toml
```

HTML and machine-readable measurements are written below `benches/target/criterion`. CI uploads that directory as a build artifact so a candidate run can be compared with the same runner class and toolchain. Results from different operating systems or runner classes should not be compared as a hard regression threshold.
