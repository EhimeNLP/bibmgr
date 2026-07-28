from __future__ import annotations

from core.config import settings
from core.constants import ReconstructionOutcome, ReconstructionPath
from models import (
    InputData,
    LLMReconstruction,
    ReferenceData,
    RustValidationResult,
    ValidationDiagnostic,
    VerifiedCitationInfo,
)
from services.orchestrator import ReconstructionOrchestrator
from services.semantic_reconstructor import SemanticReconstructionUnavailable


VALID_BIBTEX = """@article{example,
  title = {A Reliable Paper},
  author = {Ada Example},
  journal = {Journal of Tests},
  year = {2024},
  doi = {10.1000/example}
}"""


def input_data(
    *,
    doi: str | None = None,
    year: str = "2024",
) -> InputData:
    return InputData(
        parsed_data=ReferenceData(
            id="ref-1",
            title="A Reliable Paper",
            authors=["Ada Example"],
            year=year,
            doi=doi,
            raw_text=(
                "Ada Example. A Reliable Paper. 2024. "
                + (f"https://doi.org/{doi}" if doi else "")
            ),
        )
    )


class FakeDoiClient:
    def __init__(self, bibtex: str | None) -> None:
        self.bibtex = bibtex
        self.calls: list[str] = []

    def fetch_bibtex(self, doi: str) -> str | None:
        self.calls.append(doi)
        return self.bibtex


class FakeValidator:
    def __init__(self, accepted_sequence: list[bool]) -> None:
        self.accepted_sequence = iter(accepted_sequence)
        self.calls: list[str] = []

    def validate(self, source: str) -> RustValidationResult:
        self.calls.append(source)
        accepted = next(self.accepted_sequence)
        return RustValidationResult(
            accepted=accepted,
            source=source,
            diagnostics=[] if accepted else [
                ValidationDiagnostic(
                    code="LAB-ENTRY-001",
                    severity="error",
                    blocking=True,
                    message="missing required field",
                )
            ],
        )


class NormalizingFakeValidator:
    def __init__(self) -> None:
        self.calls = 0

    def validate(self, source: str) -> RustValidationResult:
        self.calls += 1
        return RustValidationResult(
            accepted=self.calls > 1,
            source="@article{rust-normalized}" if self.calls == 1 else source,
            diagnostics=[] if self.calls > 1 else [
                ValidationDiagnostic(
                    code="LAB-ENTRY-001",
                    severity="error",
                    blocking=True,
                    message="missing required field",
                )
            ],
        )


class FailingIfCalledReconstructor:
    def reconstruct(self, *args, **kwargs):
        raise AssertionError("LLM must not be called")


class FakeReconstructor:
    def __init__(self, bibtex: str = VALID_BIBTEX) -> None:
        self.bibtex = bibtex
        self.calls = []

    def reconstruct(self, evidence, **kwargs) -> LLMReconstruction:
        self.calls.append((evidence, kwargs))
        return LLMReconstruction(
            bibtex=self.bibtex,
            confidence=0.95,
            evidence_sources=["Crossref API"],
            summary="Reconstructed from matching metadata.",
        )


class UnavailableReconstructor:
    def reconstruct(self, *args, **kwargs):
        raise SemanticReconstructionUnavailable("LLM is unavailable")


class FakeSearchClient:
    api_name = "Crossref API"

    def __init__(self, doi: str = "10.1000/example") -> None:
        self.doi = doi

    def search(self, input_data):
        return (
            VerifiedCitationInfo(
                title="A Reliable Paper",
                authors=["Ada Example"],
                year=2024,
                venue="Journal of Tests",
                doi=self.doi,
            ),
            None,
        )


def orchestrator(**kwargs) -> ReconstructionOrchestrator:
    return ReconstructionOrchestrator(
        external_clients=kwargs.pop("external_clients", []),
        **kwargs,
    )


def test_exact_input_doi_bypasses_search_and_llm():
    doi_client = FakeDoiClient(VALID_BIBTEX)
    validator = FakeValidator([True])
    service = orchestrator(
        doi_client=doi_client,
        validator=validator,
        reconstructor=FailingIfCalledReconstructor(),
    )

    result = service.reconstruct_reference(input_data(doi="10.1000/example"))

    assert result.outcome == ReconstructionOutcome.READY
    assert result.reconstruction_path == ReconstructionPath.DOI_CONTENT_NEGOTIATION
    assert result.reconstructed_bibtex == VALID_BIBTEX
    assert doi_client.calls == ["10.1000/example"]
    assert len(result.attempts) == 1


def test_high_confidence_search_doi_bypasses_llm():
    doi_client = FakeDoiClient(VALID_BIBTEX)
    service = orchestrator(
        external_clients=[FakeSearchClient()],
        doi_client=doi_client,
        validator=FakeValidator([True]),
        reconstructor=FailingIfCalledReconstructor(),
    )

    result = service.reconstruct_reference(input_data())

    assert result.outcome == ReconstructionOutcome.READY
    assert result.evidence.trusted_doi == "10.1000/example"
    assert result.candidates[0].source_api == "Crossref API"


def test_citation_year_suffix_does_not_reject_matching_api_year():
    service = orchestrator(
        external_clients=[FakeSearchClient()],
        doi_client=FakeDoiClient(VALID_BIBTEX),
        validator=FakeValidator([True]),
        reconstructor=FailingIfCalledReconstructor(),
    )

    result = service.reconstruct_reference(input_data(year="2024a"))

    assert result.outcome == ReconstructionOutcome.READY
    assert result.evidence.trusted_doi == "10.1000/example"


def test_search_doi_with_conflicting_authors_is_not_trusted():
    search_client = FakeSearchClient()
    original_search = search_client.search

    def conflicting_search(input_data):
        metadata, bibtex = original_search(input_data)
        metadata.authors = ["Grace Different"]
        return metadata, bibtex

    search_client.search = conflicting_search
    reconstructor = FakeReconstructor()
    service = orchestrator(
        external_clients=[search_client],
        doi_client=FakeDoiClient(VALID_BIBTEX),
        validator=FakeValidator([True]),
        reconstructor=reconstructor,
    )

    result = service.reconstruct_reference(input_data())

    assert result.reconstruction_path == ReconstructionPath.LLM
    assert result.evidence.trusted_doi is None
    assert len(reconstructor.calls) == 1


def test_rejected_doi_candidate_is_repaired_with_rust_feedback():
    validator = FakeValidator([False, True])
    reconstructor = FakeReconstructor()
    service = orchestrator(
        doi_client=FakeDoiClient("@article{broken}"),
        validator=validator,
        reconstructor=reconstructor,
    )

    result = service.reconstruct_reference(input_data(doi="10.1000/example"))

    assert result.outcome == ReconstructionOutcome.READY
    assert result.reconstruction_path == ReconstructionPath.LLM
    assert len(result.attempts) == 2
    previous = reconstructor.calls[0][1]
    assert previous["previous_candidate"] == "@article{broken}"
    assert previous["validation"].diagnostics[0].code == "LAB-ENTRY-001"


def test_llm_feedback_uses_the_source_that_rust_diagnosed():
    reconstructor = FakeReconstructor()
    service = orchestrator(
        doi_client=FakeDoiClient("@article{raw-doi-candidate}"),
        validator=NormalizingFakeValidator(),
        reconstructor=reconstructor,
    )

    result = service.reconstruct_reference(input_data(doi="10.1000/example"))

    assert result.outcome == ReconstructionOutcome.READY
    assert (
        reconstructor.calls[0][1]["previous_candidate"]
        == "@article{rust-normalized}"
    )


def test_validation_retry_limit_routes_reference_to_review(monkeypatch):
    monkeypatch.setattr(settings, "max_llm_attempts", 2)
    service = orchestrator(
        doi_client=FakeDoiClient(None),
        validator=FakeValidator([False, False]),
        reconstructor=FakeReconstructor(),
    )

    result = service.reconstruct_reference(input_data())

    assert result.outcome == ReconstructionOutcome.MANUAL_REVIEW
    assert len(result.attempts) == 2
    assert "2 LLM attempts" in result.review_reason


def test_unavailable_llm_routes_reference_to_review():
    service = orchestrator(
        doi_client=FakeDoiClient(None),
        validator=FakeValidator([]),
        reconstructor=UnavailableReconstructor(),
    )

    result = service.reconstruct_reference(input_data())

    assert result.outcome == ReconstructionOutcome.MANUAL_REVIEW
    assert result.review_reason == "LLM is unavailable"
