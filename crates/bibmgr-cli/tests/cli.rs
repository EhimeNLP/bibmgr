use bibmgr_core::SourceRevision;
use serde_json::Value;
use std::fs;
use std::process::Command;
use tempfile::NamedTempFile;

fn bibmgr() -> Command {
    Command::new(env!("CARGO_BIN_EXE_bibmgr"))
}

#[test]
fn safe_bulk_fix_converges_across_overlapping_plans_without_writing_in_dry_run() {
    let file = NamedTempFile::new().unwrap();
    let source = "@article{k, year={2024}, TITLE=\"T\", author={Doe, Jane}, journal={J},}\n";
    fs::write(file.path(), source).unwrap();

    let output = bibmgr()
        .args([
            "fix",
            file.path().to_str().unwrap(),
            "--safe",
            "--dry-run",
            "--format",
            "json",
        ])
        .output()
        .unwrap();

    assert_eq!(output.status.code(), Some(0));
    let payload: Value = serde_json::from_slice(&output.stdout).unwrap();
    let fixed = payload["source"].as_str().unwrap();
    assert!(fixed.contains("title = {T}"));
    assert!(fixed.find("title =").unwrap() < fixed.find("author =").unwrap());
    assert_eq!(fs::read_to_string(file.path()).unwrap(), source);
}

#[test]
fn safe_flag_rejects_an_explicit_unsafe_fix() {
    let file = NamedTempFile::new().unwrap();
    let source = "@misc{k, title={A}, title={B},}\n";
    fs::write(file.path(), source).unwrap();
    let revision = SourceRevision::of(source);

    let output = bibmgr()
        .args([
            "fix",
            file.path().to_str().unwrap(),
            "--safe",
            "--fix-id",
            "BIB-SYNTAX-001:0",
            "--source-revision",
            revision.as_str(),
            "--dry-run",
        ])
        .output()
        .unwrap();

    assert_eq!(output.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&output.stderr).contains("is unsafe"));
}

#[test]
fn explicit_fix_rejects_a_stale_source_revision() {
    let file = NamedTempFile::new().unwrap();
    fs::write(file.path(), "@misc{k, TITLE={T},}\n").unwrap();

    let output = bibmgr()
        .args([
            "fix",
            file.path().to_str().unwrap(),
            "--fix-id",
            "BIB-SYNTAX-002:0",
            "--source-revision",
            SourceRevision::of("older source").as_str(),
            "--dry-run",
        ])
        .output()
        .unwrap();

    assert_eq!(output.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&output.stderr).contains("revision is stale"));
}

#[test]
fn inspect_is_versioned_and_goes_through_the_core_facade() {
    let file = NamedTempFile::new().unwrap();
    fs::write(file.path(), "@misc{k, title={T},}\n").unwrap();

    let output = bibmgr()
        .args(["inspect", file.path().to_str().unwrap(), "--ast"])
        .output()
        .unwrap();

    assert_eq!(output.status.code(), Some(0));
    let payload: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(payload["schema_version"], "1");
    assert_eq!(
        payload["bibliography"]["records"][0]["citation_key"]["value"],
        "k"
    );
}

#[test]
fn export_json_emits_the_versioned_result_for_the_selected_profile() {
    let file = NamedTempFile::new().unwrap();
    fs::write(
        file.path(),
        "@misc{smith-2024, title = {A Study}, author = {Smith, Jane}, year = {2024}, eprint = {2401.00001}, archivePrefix = {arXiv}, url = {https://arxiv.org/abs/2401.00001},}\n",
    )
    .unwrap();

    let output = bibmgr()
        .args([
            "export",
            file.path().to_str().unwrap(),
            "--profile",
            "laboratory",
            "--format",
            "json",
        ])
        .output()
        .unwrap();

    assert_eq!(output.status.code(), Some(0));
    let payload: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(payload["schema_version"], "1");
    assert_eq!(payload["profile"], "laboratory");
    let source = payload["source"].as_str().unwrap();
    assert!(source.contains("eprint"));
    assert!(source.contains("archivePrefix = {arXiv}"));
    assert!(source.contains("url = {https://arxiv.org/abs/2401.00001}"));
}
