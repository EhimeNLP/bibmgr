from __future__ import annotations

import bibmgr_native

from bibmgr_slack.input import extract_bibtex


def test_native_workflow_fixes_lint_and_keeps_unresolved_policy_findings() -> None:
    source = "@article{k,\n  TITLE={T},\n  journal={J},\n  year={2024}\n}\n"

    result = bibmgr_native.export_source_workflow(
        source,
        profile="laboratory",
    )

    assert result.input_applied_fix_ids
    assert "title =" in result.source
    assert any(
        diagnostic.code == "LAB-ENTRY-003"
        for diagnostic in result.input_diagnostics + result.output_diagnostics
    )


def test_native_workflow_restores_slack_auto_formatted_url() -> None:
    source = extract_bibtex(
        "```\n"
        "@misc{k, title={T}, year={2022}, eprint={2207.03960}, "
        "archivePrefix={arXiv}, "
        "url={<https://arxiv.org/abs/2207.03960>},}\n"
        "```"
    )

    result = bibmgr_native.export_source_workflow(source, profile="acl")
    diagnostics = result.input_diagnostics + result.output_diagnostics

    assert all(diagnostic.code != "BIB-SEMANTIC-106" for diagnostic in diagnostics)
    assert "url = {https://arxiv.org/abs/2207.03960}" in result.source
