import json

import bibmgr_native

from core.constants import ReconstructionOutcome
from core.native_validation import NativeBibtexValidator
from main import reconstruct_file
from models import ProcessedReference
from services.orchestrator import ReconstructionOrchestrator


class FakeOrchestrator:
    def reconstruct_reference(self, input_data):
        reference = input_data.parsed_data
        if reference.id == "b0":
            return ProcessedReference(
                ref_id=reference.id,
                outcome=ReconstructionOutcome.READY,
                original_data=reference,
                reconstructed_bibtex="@article{ready,\n  title = {Ready}\n}",
            )
        return ProcessedReference(
            ref_id=reference.id,
            outcome=ReconstructionOutcome.MANUAL_REVIEW,
            original_data=reference,
            review_reason="insufficient evidence",
        )


class FakeDoiClient:
    def fetch_bibtex(self, doi):
        assert doi == "10.1000/example"
        return (
            "@article{Example_2024, title={An Example}, "
            "author={Doe, Jane}, journal={Journal of Examples}, "
            "year={2024}, month=July, DOI={10.1000/example} }"
        )


class FailingIfCalledReconstructor:
    def reconstruct(self, *args, **kwargs):
        raise AssertionError("LLM must not be called on the DOI fast path")


def test_cli_writes_only_validated_entries_and_separate_review_report(tmp_path):
    input_path = tmp_path / "metadata.json"
    output_path = tmp_path / "reconstructed.bib"
    review_path = tmp_path / "review.json"
    input_path.write_text(json.dumps({
        "title": "Source document",
        "authors": ["Root Author"],
        "year": 2025,
        "doi": None,
        "abstract": "Source abstract",
        "reference_count": 2,
        "references": [
            {
                "id": "b0",
                "title": "Ready",
                "authors": ["First Author"],
                "year": "2024",
                "doi": None,
                "venue": None,
                "raw_text": "First Author. 2024. Ready.",
            },
            {
                "id": "b1",
                "title": "Unresolved",
                "authors": [],
                "year": None,
                "doi": None,
                "venue": None,
                "raw_text": "Unresolved citation",
            },
        ],
    }), encoding="utf-8")

    entries, report = reconstruct_file(
        input_path,
        output_path,
        review_path,
        orchestrator=FakeOrchestrator(),
    )

    assert len(entries) == 1
    assert report.manual_review_count == 1
    assert output_path.read_text(encoding="utf-8") == (
        "@article{ready,\n  title = {Ready}\n}\n"
    )
    report_json = json.loads(review_path.read_text(encoding="utf-8"))
    assert report_json["document"]["title"] == "Source document"
    assert report_json["total_reference_count"] == 2
    assert report_json["reconstructed_count"] == 1
    assert report_json["manual_review_count"] == 1
    assert [item["ref_id"] for item in report_json["processed_references"]] == [
        "b0",
        "b1",
    ]


def test_cli_produces_a_rust_validated_bibliography_without_network(tmp_path):
    input_path = tmp_path / "metadata.json"
    output_path = tmp_path / "reconstructed.bib"
    review_path = tmp_path / "review.json"
    input_path.write_text(json.dumps({
        "title": "Source document",
        "authors": [],
        "year": None,
        "doi": None,
        "abstract": None,
        "reference_count": 1,
        "references": [{
            "id": "b0",
            "title": "An Example",
            "authors": ["Jane Doe"],
            "year": "2024",
            "doi": "10.1000/example",
            "venue": "Journal of Examples",
            "raw_text": (
                "Jane Doe. 2024. An Example. "
                "https://doi.org/10.1000/example"
            ),
        }],
    }), encoding="utf-8")
    orchestrator = ReconstructionOrchestrator(
        external_clients=[],
        doi_client=FakeDoiClient(),
        validator=NativeBibtexValidator(),
        reconstructor=FailingIfCalledReconstructor(),
    )

    entries, report = reconstruct_file(
        input_path,
        output_path,
        review_path,
        orchestrator=orchestrator,
    )

    output = output_path.read_text(encoding="utf-8")
    decision = bibmgr_native.validate_for_registration(
        output,
        policy="laboratory",
    )
    assert len(entries) == 1
    assert report.manual_review_count == 0
    assert decision.accepted is True
    assert len(decision.records) == 1
    report_json = json.loads(review_path.read_text(encoding="utf-8"))
    assert report_json["reconstructed_count"] == 1
    assert report_json["manual_review_count"] == 0
    assert report_json["processed_references"][0]["ref_id"] == "b0"
