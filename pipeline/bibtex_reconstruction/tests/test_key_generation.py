from __future__ import annotations

import re

from bibtex_reconstruction.application.key_generation import (
    CitationKeyGenerator,
    ConceptRequest,
    ConfiguredConceptRanker,
    concept_candidates,
)
from bibtex_reconstruction.domain import (
    ConceptRankingItem,
    ConceptRankingResponse,
    ProcessedReference,
    ReferenceData,
    RustValidationResult,
)
from bibtex_reconstruction.domain.enums import (
    ReconstructionOutcome,
    ReconstructionPath,
)


class RuleOrderRanker:
    def rank(self, requests):
        return {
            request.ref_id: list(range(len(request.candidates)))
            for request in requests
        }, {
            request.ref_id: "rule_based"
            for request in requests
        }


class FakeConceptProvider:
    provider_label = "local_vllm"

    def generate(self, prompt, response_model):
        assert "Never add a candidate" in prompt
        return ConceptRankingResponse(
            rankings=[
                ConceptRankingItem(
                    ref_id="b1",
                    candidate_indices=[2, 99, 2, 0],
                )
            ]
        )


class BatchedConceptProvider:
    provider_label = "local_vllm"

    def __init__(self):
        self.call_count = 0

    def generate(self, prompt, response_model):
        self.call_count += 1
        ref_ids = re.findall(r'"ref_id": "([^"]+)"', prompt)
        return ConceptRankingResponse(
            rankings=[
                ConceptRankingItem(
                    ref_id=ref_id,
                    candidate_indices=[0],
                )
                for ref_id in ref_ids
            ]
        )


class AcceptedNormalizingValidator:
    def validate(self, source):
        return RustValidationResult(
            accepted=True,
            source="@misc{UnexpectedRewrite}",
        )


def ready_result(
    ref_id: str,
    source: str,
    *,
    path: ReconstructionPath = ReconstructionPath.OFFICIAL_CITATION,
) -> ProcessedReference:
    return ProcessedReference(
        ref_id=ref_id,
        outcome=ReconstructionOutcome.READY,
        original_data=ReferenceData(
            id=ref_id,
            title="input",
            raw_text="input",
        ),
        reconstruction_path=path,
        reconstructed_bibtex=source,
    )


def test_concept_candidates_are_title_derived_and_deterministic():
    assert concept_candidates(
        "BERT: Pre-training of Deep Bidirectional Transformers"
    )[:3] == ("bert", "pre-training", "deep")


def test_generator_rewrites_only_the_citation_key():
    source = (
        "@inproceedings{OriginalKey,\n"
        "  title = {{BERT}: Pre-training of Transformers},\n"
        "  author = {Devlin, Jacob},\n"
        "  booktitle = {Proceedings of NAACL},\n"
        "  year = {2019},\n"
        "}"
    )
    result = ready_result("b1", source)

    CitationKeyGenerator(ranker=RuleOrderRanker()).apply([result])

    assert result.reconstructed_bibtex == source.replace(
        "OriginalKey",
        "devlin-2019-naacl-bert",
        1,
    )
    assert result.citation_key is not None
    assert result.citation_key.original_citation_key == "OriginalKey"
    assert result.citation_key.concept == "bert"


def test_generator_does_not_adopt_validator_source_rewrites():
    source = (
        "@article{OriginalKey,\n"
        "  title = {Reliable Evidence},\n"
        "  author = {Doe, Jane},\n"
        "  journal = {Journal of Tests},\n"
        "  year = {2024},\n"
        "}"
    )
    result = ready_result("b1", source)

    CitationKeyGenerator(
        ranker=RuleOrderRanker(),
        validator=AcceptedNormalizingValidator(),
    ).apply([result])

    assert result.reconstructed_bibtex == source.replace(
        "OriginalKey",
        "doe-2024-t-reliable",
        1,
    )
    assert result.validation.source == result.reconstructed_bibtex


def test_local_db_key_and_source_are_preserved():
    source = "@misc{StoredKey, title = {Stored Paper}}"
    result = ready_result(
        "b1",
        source,
        path=ReconstructionPath.LOCAL_DB,
    )

    CitationKeyGenerator(ranker=RuleOrderRanker()).apply([result])

    assert result.reconstructed_bibtex == source
    assert result.citation_key is not None
    assert result.citation_key.key_preserved is True
    assert result.citation_key.generated_citation_key == "StoredKey"


def test_model_can_only_rank_existing_concept_indices():
    ranker = ConfiguredConceptRanker([FakeConceptProvider()])

    rankings, methods = ranker.rank(
        [
            ConceptRequest(
                ref_id="b1",
                title="Alpha Beta Gamma",
                candidates=("alpha", "beta", "gamma"),
            )
        ]
    )

    assert rankings == {"b1": [2, 0]}
    assert methods == {"b1": "local_vllm"}


def test_concept_ranking_batches_large_reference_collections():
    provider = BatchedConceptProvider()
    ranker = ConfiguredConceptRanker([provider], batch_size=16)
    requests = [
        ConceptRequest(
            ref_id=f"b{index}",
            title=f"Concept {index}",
            candidates=("concept",),
        )
        for index in range(33)
    ]

    rankings, methods = ranker.rank(requests)

    assert provider.call_count == 3
    assert len(rankings) == 33
    assert set(methods.values()) == {"local_vllm"}


def test_collision_uses_the_next_concept_before_a_hash_suffix():
    first = ready_result(
        "b1",
        (
            "@inproceedings{First,\n"
            "  title = {BERT: Transformers for Language},\n"
            "  author = {Devlin, Jacob},\n"
            "  booktitle = {Proceedings of NAACL},\n"
            "  year = {2019},\n"
            "}"
        ),
    )
    second = ready_result(
        "b2",
        (
            "@inproceedings{Second,\n"
            "  title = {BERT: Pretraining Transformers},\n"
            "  author = {Devlin, Jacob},\n"
            "  booktitle = {Proceedings of NAACL},\n"
            "  year = {2019},\n"
            "}"
        ),
    )

    CitationKeyGenerator(ranker=RuleOrderRanker()).apply([first, second])

    generated = {
        first.citation_key.generated_citation_key,
        second.citation_key.generated_citation_key,
    }
    assert "devlin-2019-naacl-bert" in generated
    assert any(
        key in generated
        for key in {
            "devlin-2019-naacl-pretraining",
            "devlin-2019-naacl-transformers",
        }
    )
    assert any(
        result.citation_key.collision_keys
        for result in (first, second)
    )
