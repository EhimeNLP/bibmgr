# Benchmarks

Criterion measures complete-pipeline and source-edit performance.

```console
cargo bench --manifest-path benches/Cargo.toml
```

HTML and machine-readable measurements are written below `benches/target/criterion`. CI uploads that directory as a build artifact so a candidate run can be compared with the same runner class and toolchain. Results from different operating systems or runner classes should not be compared as a hard regression threshold.

The search crate also provides a synthetic Japanese/English retrieval workload:

```console
cargo run --release -p bibmgr-search --example benchmark -- 10000
```

It reports initial index construction time and warm p50/p95 retrieval times for exact, typo, Japanese, author/title, and identifier queries. The document count is configurable. Measurements cover the native search engine, excluding HTTP, database synchronization, and response serialization; they do not measure relevance on a real library.
