import json

from core.constants import ReconstructionOutcome
from main import reconstruct_file
from models import ProcessedReference


class FakeOrchestrator:
    def reconstruct_reference(self, input_data):
        reference = input_data.parsed_data
        if reference.id == "entry-0001":
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


def test_cli_writes_only_validated_entries_and_separate_review_report(tmp_path):
    input_path = tmp_path / "damaged.bib"
    output_path = tmp_path / "reconstructed.bib"
    review_path = tmp_path / "review.json"
    input_path.write_text(
        "@article{first}\n\n@article{second}",
        encoding="utf-8",
    )

    entries, reviews = reconstruct_file(
        input_path,
        output_path,
        review_path,
        orchestrator=FakeOrchestrator(),
    )

    assert len(entries) == 1
    assert len(reviews) == 1
    assert output_path.read_text(encoding="utf-8") == (
        "@article{ready,\n  title = {Ready}\n}\n"
    )
    report = json.loads(review_path.read_text(encoding="utf-8"))
    assert report["reconstructed_count"] == 1
    assert report["manual_review_count"] == 1
    assert report["manual_review"][0]["ref_id"] == "entry-0002"
