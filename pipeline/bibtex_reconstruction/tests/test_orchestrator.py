from __future__ import annotations

import threading
import time

from bibtex_reconstruction.application.orchestrator import (
    ReconstructionOrchestrator,
)
from bibtex_reconstruction.application.semantic_reconstructor import (
    SemanticReconstructionUnavailable,
)
from bibtex_reconstruction.clients.base import APIClientError
from bibtex_reconstruction.clients.citation_site import OfficialCitation
from bibtex_reconstruction.config import settings
from bibtex_reconstruction.domain import (
    InputData,
    LLMReconstruction,
    ReferenceData,
    RustValidationResult,
    ValidationDiagnostic,
    VerifiedCitationInfo,
)
from bibtex_reconstruction.domain.enums import (
    CandidateStatus,
    ReconstructionOutcome,
    ReconstructionPath,
)


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


class FakeCitationClient:
    def __init__(self, citation: OfficialCitation | None = None) -> None:
        self.citation = citation
        self.calls: list[str] = []

    def fetch_bibtex(self, doi: str) -> OfficialCitation | None:
        self.calls.append(doi)
        return self.citation


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


class FailingSearchClient:
    api_name = "Unavailable API"

    def search(self, input_data):
        raise APIClientError(
            api_name=self.api_name,
            operation="metadata_search",
            error_type="HTTPError",
            status_code=503,
        )


class SearchConcurrencyTracker:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active = 0
        self.maximum_active = 0


class CountingSearchClient:
    def __init__(self, api_name: str, tracker: SearchConcurrencyTracker):
        self.api_name = api_name
        self.tracker = tracker

    def search(self, input_data):
        with self.tracker.lock:
            self.tracker.active += 1
            self.tracker.maximum_active = max(
                self.tracker.maximum_active,
                self.tracker.active,
            )
        time.sleep(0.01)
        with self.tracker.lock:
            self.tracker.active -= 1
        return None, None


def orchestrator(**kwargs) -> ReconstructionOrchestrator:
    return ReconstructionOrchestrator(
        external_clients=kwargs.pop("external_clients", []),
        citation_client=kwargs.pop(
            "citation_client",
            FakeCitationClient(),
        ),
        **kwargs,
    )


def test_exact_input_doi_bypasses_search_and_llm():
    doi_client = FakeDoiClient(VALID_BIBTEX)
    citation_client = FakeCitationClient()
    validator = FakeValidator([True])
    service = orchestrator(
        doi_client=doi_client,
        citation_client=citation_client,
        validator=validator,
        reconstructor=FailingIfCalledReconstructor(),
    )

    result = service.reconstruct_reference(input_data(doi="10.1000/example"))

    assert result.outcome == ReconstructionOutcome.READY
    assert result.reconstruction_path == ReconstructionPath.DOI_CONTENT_NEGOTIATION
    assert result.reconstructed_bibtex == VALID_BIBTEX
    assert doi_client.calls == ["10.1000/example"]
    assert citation_client.calls == ["10.1000/example"]
    assert len(result.attempts) == 1


def test_complete_official_citation_has_priority_over_complete_doi_bibtex():
    official_bibtex = VALID_BIBTEX.replace(
        "@article{example,",
        "@article{official,",
    )
    citation_client = FakeCitationClient(
        OfficialCitation(
            bibtex=official_bibtex,
            source_url="https://publisher.example/paper.bib",
        )
    )
    service = orchestrator(
        doi_client=FakeDoiClient(VALID_BIBTEX),
        citation_client=citation_client,
        validator=FakeValidator([True, True]),
        reconstructor=FailingIfCalledReconstructor(),
    )

    result = service.reconstruct_reference(
        input_data(doi="10.1000/example")
    )

    assert result.reconstruction_path == ReconstructionPath.OFFICIAL_CITATION
    assert result.reconstructed_bibtex == official_bibtex
    assert [attempt.path for attempt in result.attempts] == [
        ReconstructionPath.DOI_CONTENT_NEGOTIATION,
        ReconstructionPath.OFFICIAL_CITATION,
    ]


def test_complete_doi_bibtex_wins_when_official_citation_is_incomplete():
    incomplete_official = """@article{official,
  title = {},
  author = {Ada Example},
  journal = {Journal of Tests},
  year = {2024}
}"""
    service = orchestrator(
        doi_client=FakeDoiClient(VALID_BIBTEX),
        citation_client=FakeCitationClient(
            OfficialCitation(
                bibtex=incomplete_official,
                source_url="https://publisher.example/incomplete.bib",
            )
        ),
        validator=FakeValidator([True, True]),
        reconstructor=FailingIfCalledReconstructor(),
    )

    result = service.reconstruct_reference(
        input_data(doi="10.1000/example")
    )

    assert result.reconstruction_path == (
        ReconstructionPath.DOI_CONTENT_NEGOTIATION
    )
    assert result.reconstructed_bibtex == VALID_BIBTEX
    assert result.attempts[1].quality_issues == ["title"]


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


def test_incomplete_doi_uses_official_site_citation_before_metadata_or_llm():
    incomplete = """@inproceedings{example,
  title = {},
  author = {Ada Example},
  booktitle = {Proceedings of Tests},
  year = {2024}
}"""
    official = VALID_BIBTEX.replace("@article", "@inproceedings").replace(
        "journal = {Journal of Tests}",
        "booktitle = {Proceedings of Tests}",
    )
    citation_client = FakeCitationClient(
        OfficialCitation(
            bibtex=official,
            source_url="https://publisher.example/paper.bib",
        )
    )
    service = orchestrator(
        doi_client=FakeDoiClient(incomplete),
        citation_client=citation_client,
        validator=FakeValidator([True, True]),
        reconstructor=FailingIfCalledReconstructor(),
    )

    result = service.reconstruct_reference(
        input_data(doi="10.1000/example")
    )

    assert result.outcome == ReconstructionOutcome.READY
    assert result.reconstruction_path == ReconstructionPath.OFFICIAL_CITATION
    assert [attempt.path for attempt in result.attempts] == [
        ReconstructionPath.DOI_CONTENT_NEGOTIATION,
        ReconstructionPath.OFFICIAL_CITATION,
    ]
    assert result.attempts[0].quality_issues == ["title"]
    assert (
        result.attempts[1].source_url
        == "https://publisher.example/paper.bib"
    )


def test_incomplete_doi_is_enriched_from_matching_verified_metadata():
    incomplete = """@inproceedings{example,
  title = {},
  author = {Ada Example},
  booktitle = {Proceedings of Tests}
}"""
    service = orchestrator(
        external_clients=[FakeSearchClient()],
        doi_client=FakeDoiClient(incomplete),
        validator=FakeValidator([True, True]),
        reconstructor=FailingIfCalledReconstructor(),
    )

    result = service.reconstruct_reference(
        input_data(doi="10.1000/example")
    )

    assert result.outcome == ReconstructionOutcome.READY
    assert result.reconstruction_path == ReconstructionPath.METADATA_ENRICHMENT
    assert result.attempts[0].quality_issues == ["title", "year"]
    assert result.attempts[1].filled_fields == ["title", "year", "doi"]
    assert "title = {A Reliable Paper}" in result.reconstructed_bibtex
    assert "year = {2024}" in result.reconstructed_bibtex
    assert "author = {Ada Example}" in result.reconstructed_bibtex


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


def test_api_failure_is_reported_separately_from_not_found():
    service = orchestrator(
        external_clients=[FailingSearchClient()],
        doi_client=FakeDoiClient(None),
        validator=FakeValidator([True]),
        reconstructor=FakeReconstructor(),
    )

    result = service.reconstruct_reference(input_data())

    assert result.candidates[0].status == CandidateStatus.API_ERROR
    assert result.candidates[0].error == (
        "error_type=HTTPError operation=metadata_search http_status=503"
    )


def test_api_search_worker_count_is_bounded():
    tracker = SearchConcurrencyTracker()
    clients = [
        CountingSearchClient(f"API {index}", tracker)
        for index in range(4)
    ]
    service = orchestrator(
        external_clients=clients,
        search_workers=2,
    )

    candidates = service._search_candidates(input_data())

    assert len(candidates) == 4
    assert tracker.maximum_active == 2


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
    assert previous["quality_issues"] == (
        "title",
        "author_or_editor",
        "year",
        "journal",
    )


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
