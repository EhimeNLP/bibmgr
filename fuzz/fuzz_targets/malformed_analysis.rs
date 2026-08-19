#![no_main]

use bibmgr_core::{analyze, AnalysisOptions};
use libfuzzer_sys::fuzz_target;

fuzz_target!(|bytes: &[u8]| {
    let source = String::from_utf8_lossy(bytes);
    let result = analyze(&source, &AnalysisOptions::default());

    assert_eq!(
        result.source_revision,
        bibmgr_model::SourceRevision::of(&source)
    );
    assert_eq!(result.schema_version, bibmgr_model::SCHEMA_VERSION);
    let _ = serde_json::to_vec(&result);
});
