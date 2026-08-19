use bibmgr_core::{analyze, AnalysisOptions};
use bibmgr_edit::{apply_fix_plan, FixPlan};
use bibmgr_model::{SourceRevision, TextEdit, TextRange};
use criterion::{black_box, criterion_group, criterion_main, BenchmarkId, Criterion, Throughput};

fn bibliography(entries: usize) -> String {
    let mut source = String::with_capacity(entries * 240);
    for index in 0..entries {
        source.push_str(&format!(
            "@article{{author{index}-title{index},\n  author = {{Author, Alice and Writer, Bob}},\n  title = {{A deterministic benchmark entry {index}}},\n  journal = {{Computational Linguistics}},\n  year = {{2026}},\n  doi = {{10.1000/example.{index}}},\n}}\n\n"
        ));
    }
    source
}

fn bench_analysis(c: &mut Criterion) {
    let options = AnalysisOptions::default();
    let mut group = c.benchmark_group("complete_analysis");
    for entry_count in [1_usize, 100, 1_000] {
        let source = bibliography(entry_count);
        group.throughput(Throughput::Bytes(source.len() as u64));
        group.bench_with_input(
            BenchmarkId::from_parameter(entry_count),
            &source,
            |benchmark, source| {
                benchmark.iter(|| analyze(black_box(source), black_box(&options)));
            },
        );
    }
    group.finish();
}

fn bench_source_preserving_edit(c: &mut Criterion) {
    let source = bibliography(1_000);
    let plan = FixPlan {
        source_revision: SourceRevision::of(&source),
        fixes: Vec::new(),
        edits: vec![TextEdit {
            range: TextRange::new(0, 0),
            replacement: "% benchmark edit\n".to_owned(),
        }],
    };
    c.bench_function("source_preserving_edit/1000_entries", |benchmark| {
        benchmark.iter(|| apply_fix_plan(black_box(&source), black_box(&plan)).unwrap());
    });
}

criterion_group!(benches, bench_analysis, bench_source_preserving_edit);
criterion_main!(benches);
