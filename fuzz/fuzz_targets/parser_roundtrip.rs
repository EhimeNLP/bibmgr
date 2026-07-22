#![no_main]

use bibmgr_syntax::{parse, ParseOptions};
use libfuzzer_sys::fuzz_target;

fuzz_target!(|bytes: &[u8]| {
    let source = String::from_utf8_lossy(bytes);
    for options in [ParseOptions::strict(), ParseOptions::tolerant()] {
        let document = parse(&source, options);
        assert_eq!(document.to_source().as_bytes(), source.as_bytes());
        let _ = document.summary();
        let _ = document.diagnostics();
    }
});
