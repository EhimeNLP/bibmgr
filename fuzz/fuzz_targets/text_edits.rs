#![no_main]

use bibmgr_edit::{apply_fix_plan, FixPlan};
use bibmgr_model::{SourceRevision, TextEdit, TextRange};
use libfuzzer_sys::fuzz_target;

fuzz_target!(|bytes: &[u8]| {
    let split = bytes.len().min(8);
    let control = &bytes[..split];
    let source = String::from_utf8_lossy(&bytes[split..]).into_owned();

    let number = |offset: usize| -> u32 {
        let first = control.get(offset).copied().unwrap_or_default();
        let second = control.get(offset + 1).copied().unwrap_or_default();
        u16::from_le_bytes([first, second]).into()
    };
    let start = number(0);
    let end = number(2);
    let replacement = String::from_utf8_lossy(control.get(4..).unwrap_or_default()).into_owned();
    let revision = if control.get(7).copied().unwrap_or_default() & 1 == 0 {
        SourceRevision::of(&source)
    } else {
        SourceRevision::of("stale")
    };
    let plan = FixPlan {
        source_revision: revision,
        fixes: Vec::new(),
        edits: vec![TextEdit {
            range: TextRange { start, end },
            replacement,
        }],
    };

    if let Ok(applied) = apply_fix_plan(&source, &plan) {
        assert_eq!(applied.source_revision, SourceRevision::of(&applied.source));
        assert!(std::str::from_utf8(applied.source.as_bytes()).is_ok());
    }
});
