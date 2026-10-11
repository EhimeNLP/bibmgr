//! Reproducible synthetic retrieval workload; run with --release.

use std::time::Instant;

use bibmgr_search::{SearchDocument, SearchIndex, SearchRequest};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let count: usize = std::env::args()
        .nth(1)
        .map_or(Ok(10_000), |arg| arg.parse())?;
    let titles = [
        "Neural machine translation with attention",
        "自然言語処理のためのBERT",
        "Efficient document retrieval with transformers",
        "Graph clustering for scientific literature",
        "Robust speech recognition",
    ];
    let documents = (0..count)
        .map(|i| SearchDocument {
            id: format!("{i:032x}"),
            title: format!("{}: experiment {i}", titles[i % titles.len()]),
            authors: vec!["Jörg Müller".into(), "山田 太郎".into()],
            venues: vec!["ACL".into()],
            identifiers: vec![format!("paper{i}"), format!("10.1234/paper{i}")],
            year: Some(2024),
            body: format!("Results and evaluation of {}.", titles[i % titles.len()]),
            ..SearchDocument::default()
        })
        .collect();
    let started = Instant::now();
    let index = SearchIndex::new()?;
    index.apply(documents, &[])?;
    println!(
        "documents={count} build_ms={}",
        started.elapsed().as_millis()
    );
    for query in [
        "neural translation",
        "neurla translation",
        "山田 言語処理",
        "Muller retrieval",
        "10.1234/paper42",
    ] {
        let request = SearchRequest {
            query: query.into(),
            limit: 25,
            sort: "relevance".into(),
            ..SearchRequest::default()
        };
        let page = index.search(&request)?;
        let mut elapsed = Vec::new();
        for _ in 0..40 {
            let started = Instant::now();
            std::hint::black_box(index.search(&request)?);
            elapsed.push(started.elapsed().as_micros());
        }
        elapsed.sort_unstable();
        println!(
            "query={query:?} matches={} p50_us={} p95_us={}",
            page.total, elapsed[20], elapsed[37]
        );
    }
    Ok(())
}
