use bibmgr_core::duplicates::{assess_duplicates, DuplicateAction, DuplicatePolicy};
use bibmgr_core::DuplicateKind;
use bibmgr_core::{compare_records, comparison_record, inspect_ast, ParseOptions};

fn records(source: &str) -> Vec<bibmgr_core::ComparisonRecord> {
    inspect_ast(source, ParseOptions::strict())
        .bibliography
        .records
        .iter()
        .map(comparison_record)
        .collect()
}

#[test]
fn titles_normalize_tex_unicode_and_whitespace_but_preserve_meaning() {
    let values = records("@misc{a,title={{CAFÉ} Methods}}\n@misc{b,title={cafe\u{301}   methods}}\n@misc{c,title={caf\\'{e} methods}}\n@misc{d,title={café methods 2}}\n@misc{e,title={\\unknown{café} methods}}\n@misc{f,title={$X$ methods}}");
    assert_eq!(values[0].title, values[1].title);
    assert_eq!(values[0].title, values[2].title);
    assert_ne!(values[0].title, values[3].title);
    assert_eq!(values[4].title, None);
    assert_eq!(values[5].title, None);
    assert_eq!(
        compare_records(&values[0], &values[1]).unwrap().kind,
        DuplicateKind::Title
    );
}

#[test]
fn missing_metadata_is_not_a_conflict_and_title_alone_is_not_identity() {
    let values = records("@misc{a,title={A Study}}\n@article{b,title={A Study},year={2024},journal={Testing},pages={1--9}}\n@article{c,title={A Study},year={2024},journal={Testing},pages={1–9}}\n@article{d,title={A Study},year={2025},journal={Testing},pages={1--9}}");
    let candidate = compare_records(&values[0], &values[1]).unwrap();
    assert_eq!(candidate.kind, DuplicateKind::Title);
    assert_eq!(
        candidate
            .fields
            .iter()
            .find(|f| f.field == "year")
            .unwrap()
            .agreement,
        bibmgr_semantics::duplicates::Agreement::Missing
    );
    assert_eq!(
        compare_records(&values[1], &values[2]).unwrap().kind,
        DuplicateKind::CorroboratedTitle
    );
    assert_eq!(
        compare_records(&values[1], &values[3]).unwrap().kind,
        DuplicateKind::Title
    );
}

#[test]
fn identifiers_match_independently_of_title_and_arxiv_versions_remain_distinct_evidence() {
    let values = records("@misc{a,title={Before},doi={10.1000/ABC},eprint={2302.13971v1},archivePrefix={arXiv}}\n@misc{b,title={After},doi={https://doi.org/10.1000/abc}}\n@misc{c,title={Renamed},eprint={2302.13971v2},archivePrefix={arXiv}}");
    assert_eq!(
        compare_records(&values[0], &values[1]).unwrap().kind,
        DuplicateKind::Identifier
    );
    assert_eq!(
        compare_records(&values[0], &values[2]).unwrap().kind,
        DuplicateKind::ArxivFamily
    );
}

#[test]
fn authors_support_matching_without_requiring_identical_spelling() {
    let values = records("@article{a,title={Study},author={Doe, Jane},year={2024},journal={J},volume={1}}\n@article{b,title={Study},author={J. Doe},year={2024},journal={J},volume={1}}");
    assert_eq!(values[0].authors, values[1].authors);
    assert_eq!(
        compare_records(&values[0], &values[1]).unwrap().kind,
        DuplicateKind::CorroboratedTitle
    );
}

#[test]
fn policies_do_not_mutate_records_and_batch_candidates_are_deterministic() {
    let incoming =
        records("@misc{Same,title={One}}\n@misc{same,title={Other}}\n@misc{third,title={One}}");
    let policy = DuplicatePolicy {
        title: DuplicateAction::Confirm,
        ..DuplicatePolicy::default()
    };
    let findings = assess_duplicates(&incoming, &[], &policy).unwrap();
    assert_eq!(findings.len(), 2);
    assert_eq!(findings[0].action, DuplicateAction::Warn);
    assert_eq!(findings[1].action, DuplicateAction::Confirm);
    assert_eq!(
        findings,
        assess_duplicates(&incoming, &[], &policy).unwrap()
    );
    assert!(serde_json::from_str::<DuplicatePolicy>(r#"{"unknown":"warn"}"#).is_err());
}

#[test]
fn unavailable_titles_and_identifiers_do_not_create_false_matches() {
    let values =
        records("@misc{a,title=unknown}\n@misc{b,title=unknown}\n@misc{c,title={One},title={Two}}");
    assert_eq!(values[0].title, None);
    assert_eq!(values[1].title, None);
    assert_eq!(values[2].title, None);
    assert_eq!(
        assess_duplicates(&values, &[], &DuplicatePolicy::default()).unwrap(),
        []
    );
}

#[test]
fn excessively_many_matches_fail_explicitly_and_versioned_data_is_checked() {
    let record = records("@misc{a,title={Same}}").remove(0);
    let many = vec![record.clone(); 46];
    assert!(assess_duplicates(&many, &[], &DuplicatePolicy::default()).is_err());
    let mut old = record;
    old.version = 0;
    assert!(assess_duplicates(&[old], &[], &DuplicatePolicy::default()).is_err());
}
