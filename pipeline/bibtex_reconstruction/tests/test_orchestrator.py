from __future__ import annotations

import threading
import time

from bibtex_reconstruction.application.orchestrator import (
    ReconstructionOrchestrator,
)
from bibtex_reconstruction.clients.base import APIClientError
from bibtex_reconstruction.clients.citation_site import OfficialCitation
from bibtex_reconstruction.config import settings
from bibtex_reconstruction.domain import (
    InputData,
    QueryImprovementAudit,
    ReferenceData,
    RustValidationResult,
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

ARXIV_ADAM_BIBTEX = """@misc{kingma2017adam,
  title={Adam: A Method for Stochastic Optimization},
  author={Diederik P. Kingma and Jimmy Ba},
  year={2017},
  eprint={1412.6980},
  archivePrefix={arXiv}
}"""


def input_data(*, doi: str | None = None) -> InputData:
    return InputData(
        parsed_data=ReferenceData(
            id="ref-1",
            title="A Reliable Paper",
            authors=["Ada Example"],
            year="2024",
            doi=doi,
            raw_text=f"Ada Example. A Reliable Paper. 2024. {doi or ''}",
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
    def __init__(self, bibtex: str | None = None) -> None:
        self.bibtex = bibtex
        self.calls: list[str] = []

    def fetch_bibtex(self, doi: str):
        self.calls.append(doi)
        if self.bibtex is None:
            return None
        return OfficialCitation(
            self.bibtex,
            "https://publisher.example/cite.bib",
        )


class AcceptingValidator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def validate(self, source: str) -> RustValidationResult:
        self.calls.append(source)
        return RustValidationResult(accepted=True, source="not-adopted")


class RejectingSourceValidator:
    def __init__(self, rejected_text: str) -> None:
        self.rejected_text = rejected_text
        self.calls: list[str] = []

    def validate(self, source: str) -> RustValidationResult:
        self.calls.append(source)
        return RustValidationResult(
            accepted=self.rejected_text not in source,
            source=source,
        )


class NoQueryImprover:
    def improve(self, reference):
        return QueryImprovementAudit()


class FakeQueryImprover:
    def improve(self, reference):
        return QueryImprovementAudit(queries=["Reliable Paper Ada"])


class IdentifierQueryImprover:
    def improve(self, reference):
        return QueryImprovementAudit(
            queries=[
                "Kingma Ba ICLR 2015 Adam stochastic optimization",
                "arXiv:1412.6980 Adam Kingma",
            ]
        )


class SearchClient:
    authoritative_bibtex = False

    def __init__(
        self,
        api_name: str,
        *,
        doi: str | None = "10.1000/example",
        bibtex: str | None = None,
        title: str = "A Reliable Paper",
        authors: list[str] | None = None,
        year: int = 2024,
    ) -> None:
        self.api_name = api_name
        self.doi = doi
        self.bibtex = bibtex
        self.title = title
        self.authors = (
            authors if authors is not None else ["Ada Example"]
        )
        self.year = year
        self.queries: list[str | None] = []

    def search(self, data):
        self.queries.append(data.parsed_data.title)
        return (
            VerifiedCitationInfo(
                title=self.title,
                authors=self.authors,
                year=self.year,
                venue="Journal of Tests",
                doi=self.doi,
                raw_payload={"provider": self.api_name},
            ),
            self.bibtex,
        )


class AuthoritativeClient(SearchClient):
    authoritative_bibtex = True


class TypedMetadataClient(SearchClient):
    def __init__(
        self,
        api_name: str,
        *,
        publication_types: list[str],
        venue: str,
        **kwargs,
    ) -> None:
        super().__init__(api_name, **kwargs)
        self.publication_types = publication_types
        self.venue = venue

    def search(self, data):
        self.queries.append(data.parsed_data.title)
        return (
            VerifiedCitationInfo(
                title=self.title,
                authors=self.authors,
                publication_types=self.publication_types,
                year=self.year,
                venue=self.venue,
                doi=self.doi,
                raw_payload={"provider": self.api_name},
            ),
            self.bibtex,
        )


class FailingClient:
    api_name = "Unavailable API"

    def search(self, data):
        raise APIClientError(
            api_name=self.api_name,
            operation="metadata_search",
            error_type="HTTPError",
            status_code=503,
        )


class LocalClient:
    api_name = "BibMgR Local DB"

    def search(self, data):
        return (
            VerifiedCitationInfo(
                title="A Reliable Paper",
                authors=["Ada Example"],
                year=2024,
                doi="10.1000/example",
            ),
            VALID_BIBTEX,
        )


class IncompleteLocalClient:
    api_name = "BibMgR Local DB"

    def search(self, data):
        return (
            VerifiedCitationInfo(title="Stored"),
            "@misc{StoredKey, title = {Stored}}",
        )


def service(**kwargs):
    return ReconstructionOrchestrator(
        external_clients=kwargs.pop("external_clients", []),
        doi_client=kwargs.pop("doi_client", FakeDoiClient(None)),
        citation_client=kwargs.pop(
            "citation_client",
            FakeCitationClient(),
        ),
        validator=kwargs.pop("validator", AcceptingValidator()),
        query_improver=kwargs.pop(
            "query_improver",
            NoQueryImprover(),
        ),
        **kwargs,
    )


def test_exact_doi_collects_both_representations_and_prefers_official():
    official = VALID_BIBTEX.replace("example,", "official,", 1)
    validator = AcceptingValidator()
    result = service(
        doi_client=FakeDoiClient(VALID_BIBTEX),
        citation_client=FakeCitationClient(official),
        validator=validator,
    ).reconstruct_reference(input_data(doi="10.1000/example"))

    assert result.outcome == ReconstructionOutcome.READY
    assert result.reconstruction_path == ReconstructionPath.OFFICIAL_CITATION
    assert result.reconstructed_bibtex == official
    assert len(result.doi_groups) == 1
    assert result.doi_groups[0].official_citation.bibtex == official
    assert (
        result.doi_groups[0].content_negotiation.bibtex == VALID_BIBTEX
    )
    assert validator.calls == [official]


def test_official_base_is_supplemented_without_reformatting():
    official = """@article{official,
  title = {},
  author = {Ada Example},
  journal = {Journal of Tests},
}"""
    negotiated = VALID_BIBTEX
    result = service(
        doi_client=FakeDoiClient(negotiated),
        citation_client=FakeCitationClient(official),
    ).reconstruct_reference(input_data(doi="10.1000/example"))

    assert result.outcome == ReconstructionOutcome.READY
    assert result.reconstruction_path == ReconstructionPath.METADATA_ENRICHMENT
    assert result.reconstructed_bibtex.startswith("@article{official,")
    assert "title = {A Reliable Paper}" in result.reconstructed_bibtex
    assert "year = {2024}" in result.reconstructed_bibtex
    assert result.selection.source_kind.value == "official_citation"
    assert {
        item.field for item in result.selection.supplements
    } == {"title", "year", "doi"}


def test_invalid_provider_key_is_repaired_without_changing_fields():
    official = VALID_BIBTEX.replace(
        "example,",
        "10.1000/example,",
        1,
    )
    validator = RejectingSourceValidator("{10.1000/example,")
    result = service(
        citation_client=FakeCitationClient(official),
        validator=validator,
    ).reconstruct_reference(input_data(doi="10.1000/example"))

    assert result.outcome == ReconstructionOutcome.READY
    assert len(result.attempts) == 2
    assert result.doi_groups[0].official_citation.bibtex == official
    assert result.reconstructed_bibtex == official.replace(
        "{10.1000/example,",
        "{10.1000-example,",
        1,
    )


def test_rust_rejection_falls_back_within_the_same_doi():
    official = VALID_BIBTEX.replace("example,", "official,", 1)
    negotiated = VALID_BIBTEX.replace("example,", "negotiated,", 1)
    validator = RejectingSourceValidator("{official,")
    result = service(
        citation_client=FakeCitationClient(official),
        doi_client=FakeDoiClient(negotiated),
        validator=validator,
    ).reconstruct_reference(input_data(doi="10.1000/example"))

    assert result.outcome == ReconstructionOutcome.READY
    assert result.reconstruction_path == ReconstructionPath.DOI_CONTENT_NEGOTIATION
    assert result.reconstructed_bibtex == negotiated
    assert [attempt.candidate_bibtex for attempt in result.attempts] == [
        official,
        negotiated,
    ]


def test_api_candidates_remain_independent_and_follow_source_priority():
    acl_anthology = SearchClient("ACL Anthology")
    crossref = SearchClient("Crossref API")
    semantic_scholar = SearchClient("Semantic Scholar API")
    cinii = SearchClient("CiNii API")
    jstage = SearchClient("J-STAGE API")
    arxiv = SearchClient("arXiv API")
    result = service(
        external_clients=[
            arxiv,
            jstage,
            cinii,
            semantic_scholar,
            crossref,
            acl_anthology,
        ],
        doi_client=FakeDoiClient(VALID_BIBTEX),
    ).reconstruct_reference(input_data())

    assert [item.source_api for item in result.candidates] == [
        "ACL Anthology",
        "Crossref API",
        "Semantic Scholar API",
        "CiNii API",
        "J-STAGE API",
        "arXiv API",
    ]
    assert len({item.candidate_id for item in result.candidates}) == 6
    assert result.doi_groups[0].candidate_ids == [
        item.candidate_id for item in result.candidates
    ]


def test_only_one_same_doi_api_is_used_as_supplement():
    incomplete = """@article{base,
  title = {A Reliable Paper},
  author = {Ada Example},
}"""
    jstage = SearchClient("J-STAGE API")
    crossref = SearchClient("Crossref API")
    result = service(
        external_clients=[crossref, jstage],
        doi_client=FakeDoiClient(incomplete),
    ).reconstruct_reference(input_data(doi="10.1000/example"))

    assert result.outcome == ReconstructionOutcome.READY
    assert {
        item.source_api for item in result.selection.supplements
    } == {"Crossref API"}


def test_conflicting_same_doi_supplement_requires_manual_review():
    incomplete = """@article{base,
  title = {A Reliable Paper},
  author = {Ada Example},
}"""
    conflict = SearchClient(
        "Crossref API",
        title="A Completely Different Paper",
    )
    result = service(
        external_clients=[conflict],
        doi_client=FakeDoiClient(incomplete),
    ).reconstruct_reference(input_data(doi="10.1000/example"))

    assert result.outcome == ReconstructionOutcome.MANUAL_REVIEW
    assert result.selection.conflicts[0].field == "title"
    assert result.reconstructed_bibtex is None


def test_llm_is_used_only_to_retry_search_queries(monkeypatch):
    monkeypatch.setattr(settings, "query_improvement_enabled", True)
    client = SearchClient(
        "Crossref API",
        doi=None,
        title="unrelated",
    )
    result = service(
        external_clients=[client],
        query_improver=FakeQueryImprover(),
    ).reconstruct_reference(input_data())

    assert client.queries == ["A Reliable Paper", "Reliable Paper Ada"]
    assert result.query_improvements[0].queries == ["Reliable Paper Ada"]
    assert result.reconstructed_bibtex is None


def test_query_improvement_runs_for_each_configured_round(monkeypatch):
    monkeypatch.setattr(settings, "query_improvement_enabled", True)
    monkeypatch.setattr(settings, "query_improvement_max_rounds", 3)

    class MultiRoundQueryImprover:
        def __init__(self):
            self.titles = []

        def improve(self, reference):
            self.titles.append(reference.title)
            return QueryImprovementAudit(
                queries=[f"Round {len(self.titles)} Query"]
            )

    class ThirdRoundMatchClient(SearchClient):
        def search(self, data):
            query = data.parsed_data.title
            self.queries.append(query)
            if query != "Round 3 Query":
                return (
                    VerifiedCitationInfo(
                        title="Unrelated Work",
                        authors=["Other Author"],
                        year=1999,
                    ),
                    None,
                )
            return (
                VerifiedCitationInfo(
                    title=self.title,
                    authors=self.authors,
                    year=self.year,
                    venue="Journal of Tests",
                    doi=self.doi,
                ),
                self.bibtex,
            )

    improver = MultiRoundQueryImprover()
    client = ThirdRoundMatchClient("Crossref API")
    result = service(
        external_clients=[client],
        doi_client=FakeDoiClient(VALID_BIBTEX),
        query_improver=improver,
    ).reconstruct_reference(input_data())

    assert improver.titles == [
        "A Reliable Paper",
        "Round 1 Query",
        "Round 2 Query",
    ]
    assert client.queries == [
        "A Reliable Paper",
        "Round 1 Query",
        "Round 2 Query",
        "Round 3 Query",
    ]
    assert [
        audit.query_round for audit in result.query_improvements
    ] == [1, 2, 3]
    assert [
        audit.queries for audit in result.query_improvements
    ] == [
        ["Round 1 Query"],
        ["Round 2 Query"],
        ["Round 3 Query"],
    ]
    assert {
        candidate.query_round for candidate in result.candidates
    } == {0, 1, 2, 3}
    assert result.outcome == ReconstructionOutcome.READY


def test_improved_query_result_is_scored_against_original_citation(
    monkeypatch,
):
    monkeypatch.setattr(settings, "query_improvement_enabled", True)

    class QuerySensitiveClient(SearchClient):
        def search(self, data):
            self.queries.append(data.parsed_data.title)
            if len(self.queries) == 1:
                return (
                    VerifiedCitationInfo(
                        title="Unrelated Work",
                        authors=["Other Author"],
                        year=1999,
                    ),
                    None,
                )
            return (
                VerifiedCitationInfo(
                    title=self.title,
                    authors=self.authors,
                    year=self.year,
                    venue="Journal of Tests",
                    doi=self.doi,
                    raw_payload={"provider": self.api_name},
                ),
                self.bibtex,
            )

    client = QuerySensitiveClient("Crossref API")
    result = service(
        external_clients=[client],
        doi_client=FakeDoiClient(VALID_BIBTEX),
        query_improver=FakeQueryImprover(),
    ).reconstruct_reference(input_data())

    assert client.queries == ["A Reliable Paper", "Reliable Paper Ada"]
    assert result.outcome == ReconstructionOutcome.READY
    improved = next(
        candidate
        for candidate in result.candidates
        if candidate.query_round == 1
    )
    assert improved.confidence_score == 1.0


def test_explicit_arxiv_query_is_prioritized_and_stops_fuzzy_retries(
    monkeypatch,
):
    monkeypatch.setattr(settings, "query_improvement_enabled", True)

    class IdentifierArxivClient:
        api_name = "arXiv API"
        authoritative_bibtex = True

        def __init__(self):
            self.queries = []

        def search(self, data):
            query = data.parsed_data.title
            self.queries.append(query)
            if not query.startswith("arXiv:"):
                return None, None
            return (
                VerifiedCitationInfo(
                    title="Adam: A Method for Stochastic Optimization",
                    authors=["Diederik P. Kingma", "Jimmy Ba"],
                    publication_types=["Preprint"],
                    year=2017,
                    venue="arXiv",
                ),
                ARXIV_ADAM_BIBTEX,
            )

    client = IdentifierArxivClient()
    adam = InputData(
        parsed_data=ReferenceData(
            id="b11",
            title="Adam: A Method for Stochastic Optimization",
            authors=["Diederik P. Kingma", "Jimmy Lei Ba"],
            year="2015",
            raw_text="Kingma and Ba. Adam. ICLR 2015.",
        )
    )
    result = service(
        external_clients=[client],
        query_improver=IdentifierQueryImprover(),
    ).reconstruct_reference(adam)

    assert result.outcome == ReconstructionOutcome.READY
    assert client.queries == [
        "Adam: A Method for Stochastic Optimization",
        "arXiv:1412.6980 Adam Kingma",
    ]


def test_untrusted_match_still_triggers_query_improvement(monkeypatch):
    monkeypatch.setattr(settings, "query_improvement_enabled", True)
    client = SearchClient("Crossref API", authors=[])

    result = service(
        external_clients=[client],
        query_improver=FakeQueryImprover(),
    ).reconstruct_reference(input_data())

    assert client.queries == ["A Reliable Paper", "Reliable Paper Ada"]
    assert result.outcome == ReconstructionOutcome.MANUAL_REVIEW


def test_direct_authoritative_export_is_fallback_not_generated_bibtex():
    client = AuthoritativeClient(
        "CiNii API",
        doi=None,
        bibtex=VALID_BIBTEX,
    )
    result = service(
        external_clients=[client],
    ).reconstruct_reference(input_data())

    assert result.outcome == ReconstructionOutcome.READY
    assert result.reconstruction_path == ReconstructionPath.EXTERNAL_API
    assert result.selection.candidate_id == result.candidates[0].candidate_id


def test_direct_export_requires_stricter_identity_than_doi_lookup():
    direct = AuthoritativeClient(
        "CiNii API",
        doi=None,
        bibtex=VALID_BIBTEX,
        title="A Reliable Paper Extended",
    )
    direct_result = service(
        external_clients=[direct],
    ).reconstruct_reference(input_data())

    doi_candidate = SearchClient(
        "Crossref API",
        title="A Reliable Paper Extended",
    )
    doi_result = service(
        external_clients=[doi_candidate],
        doi_client=FakeDoiClient(VALID_BIBTEX),
    ).reconstruct_reference(input_data())

    assert direct_result.candidates[0].confidence_score < 0.90
    assert direct_result.outcome == ReconstructionOutcome.MANUAL_REVIEW
    assert doi_result.outcome == ReconstructionOutcome.READY


def test_typed_metadata_synthesizes_formal_adam_citation():
    adam = InputData(
        parsed_data=ReferenceData(
            id="b11",
            title="Adam: A Method for Stochastic Optimization",
            authors=["Diederik P. Kingma", "Jimmy Lei Ba"],
            year="2015",
            venue=(
                "In Proceedings of the 3rd International Conference on "
                "Learning Representations"
            ),
            raw_text=(
                "Diederik P. Kingma and Jimmy Lei Ba. 2015. Adam: A Method "
                "for Stochastic Optimization. In Proceedings of the 3rd "
                "International Conference on Learning Representations."
            ),
        )
    )
    semantic_scholar = TypedMetadataClient(
        "Semantic Scholar API",
        publication_types=["Conference"],
        venue="International Conference on Learning Representations",
        doi=None,
        title="Adam: A Method for Stochastic Optimization",
        authors=["Diederik P. Kingma", "Jimmy Ba"],
        year=2014,
    )
    arxiv = AuthoritativeClient(
        "arXiv API",
        doi=None,
        bibtex=ARXIV_ADAM_BIBTEX,
        title="Adam: A Method for Stochastic Optimization",
        authors=["Diederik P. Kingma", "Jimmy Ba"],
        year=2014,
    )

    result = service(
        external_clients=[arxiv, semantic_scholar],
    ).reconstruct_reference(adam)

    assert result.outcome == ReconstructionOutcome.READY
    assert result.reconstruction_path == ReconstructionPath.METADATA_SYNTHESIS
    assert result.reconstructed_bibtex.startswith("@inproceedings{")
    assert "year = {2015}" in result.reconstructed_bibtex
    assert (
        "booktitle = {International Conference on Learning Representations}"
        in result.reconstructed_bibtex
    )
    assert result.selection.generated_entry_type == "inproceedings"
    assert result.selection.observed_conflicts[0].values == {
        "metadata_extraction": "2015",
        "Semantic Scholar API": "2014",
    }
    year_source = next(
        item
        for item in result.selection.field_provenance
        if item.field == "year"
    )
    assert year_source.source_api == "metadata_extraction"


def test_arxiv_misc_is_last_fallback_and_ignores_year_difference():
    arxiv = AuthoritativeClient(
        "arXiv API",
        doi=None,
        bibtex=ARXIV_ADAM_BIBTEX,
        title="Adam: A Method for Stochastic Optimization",
        authors=["Diederik P. Kingma", "Jimmy Ba"],
        year=2014,
    )
    adam = InputData(
        parsed_data=ReferenceData(
            id="b11",
            title="Adam: A Method for Stochastic Optimization",
            authors=["Diederik P. Kingma", "Jimmy Lei Ba"],
            year="2015",
            raw_text="Kingma and Ba. 2015. Adam. ICLR.",
        )
    )

    result = service(external_clients=[arxiv]).reconstruct_reference(adam)

    assert result.outcome == ReconstructionOutcome.READY
    assert result.reconstruction_path == ReconstructionPath.EXTERNAL_API
    assert result.reconstructed_bibtex == ARXIV_ADAM_BIBTEX
    assert result.selection.observed_conflicts[0].values == {
        "metadata_extraction": "2015",
        "arXiv API metadata": "2014",
        "arXiv API BibTeX": "2017",
    }


def test_ambiguous_publication_type_is_not_synthesized():
    ambiguous = TypedMetadataClient(
        "Semantic Scholar API",
        publication_types=["Conference", "JournalArticle"],
        venue="Journal of Tests",
        doi=None,
    )

    result = service(external_clients=[ambiguous]).reconstruct_reference(
        input_data()
    )

    assert result.outcome == ReconstructionOutcome.MANUAL_REVIEW
    assert result.attempts == []


def test_local_db_is_the_highest_priority(monkeypatch):
    monkeypatch.setattr(settings, "localdb_enabled", True)
    validator = AcceptingValidator()
    result = service(
        local_db_client=LocalClient(),
        external_clients=[SearchClient("Crossref API")],
        validator=validator,
    ).reconstruct_reference(input_data())

    assert result.reconstruction_path == ReconstructionPath.LOCAL_DB
    assert result.selection.source_kind.value == "local_db"
    assert validator.calls == [VALID_BIBTEX]


def test_local_db_preserves_an_already_registered_source(monkeypatch):
    monkeypatch.setattr(settings, "localdb_enabled", True)
    result = service(
        local_db_client=IncompleteLocalClient(),
    ).reconstruct_reference(input_data())

    assert result.outcome == ReconstructionOutcome.READY
    assert result.reconstructed_bibtex == (
        "@misc{StoredKey, title = {Stored}}"
    )


def test_api_failure_is_distinct_from_not_found():
    result = service(
        external_clients=[FailingClient()],
    ).reconstruct_reference(input_data())

    assert result.candidates[0].status == CandidateStatus.API_ERROR
    assert result.candidates[0].error.endswith("http_status=503")


def test_search_worker_count_is_bounded():
    lock = threading.Lock()
    active = 0
    maximum = 0

    class SlowClient:
        def __init__(self, name):
            self.api_name = name

        def search(self, data):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.01)
            with lock:
                active -= 1
            return None, None

    manager = service(
        external_clients=[SlowClient(str(index)) for index in range(4)],
        search_workers=2,
    )
    candidates = manager._search_candidates(input_data(), query_round=0)

    assert len(candidates) == 4
    assert maximum == 2
