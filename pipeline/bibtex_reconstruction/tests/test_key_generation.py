from __future__ import annotations

import re

from bibtex_reconstruction.application.key_generation import (
    CitationKeyGenerator,
    ConceptRequest,
    ConfiguredConceptGenerator,
    GeneratedConcept,
    concept_candidates,
    representative_concept,
)
from bibtex_reconstruction.domain import (
    ConceptGenerationItem,
    ConceptGenerationResponse,
    LLMInvocationAudit,
    ProcessedReference,
    ReferenceData,
    RustValidationResult,
)
from bibtex_reconstruction.domain.enums import (
    LLMTask,
    ReconstructionOutcome,
    ReconstructionPath,
)


class RuleGenerator:
    def generate(self, requests):
        return {}


class FakeProvider:
    provider_label = "local_vllm"
    model = "Qwen/Test"

    def generate(self, prompt, response_model):
        assert "SELECTION ORDER" in prompt
        assert "KNOWLEDGE USE" in prompt
        assert "pretrained knowledge" in prompt
        return ConceptGenerationResponse(
            concepts=[
                ConceptGenerationItem(
                    ref_id="b1",
                    concept="transformer",
                    source_terms=["transformers"],
                )
            ]
        )


class BatchedProvider:
    provider_label = "local_vllm"
    model = "Qwen/Test"

    def __init__(self):
        self.calls = 0

    def generate(self, prompt, response_model):
        self.calls += 1
        return ConceptGenerationResponse(
            concepts=[
                ConceptGenerationItem(
                    ref_id=ref_id,
                    concept="concept",
                    source_terms=["concept"],
                )
                for ref_id in re.findall(r'"ref_id": "([^"]+)"', prompt)
            ]
        )


class ExplicitGenerator:
    def generate(self, requests):
        audit = LLMInvocationAudit(
            task=LLMTask.KEY_CONCEPT_GENERATION,
            provider="local_vllm",
            model="Qwen/Test",
            prompt_sha256="0" * 64,
            response={"concept": "language"},
        )
        return {
            request.ref_id: GeneratedConcept(
                concept="language",
                source_terms=("language",),
                audit=audit,
            )
            for request in requests
        }


class AcceptedValidator:
    def validate(self, source):
        return RustValidationResult(accepted=True, source="ignored")


def ready(ref_id: str, source: str, *, local: bool = False):
    return ProcessedReference(
        ref_id=ref_id,
        outcome=ReconstructionOutcome.READY,
        original_data=ReferenceData(
            id=ref_id,
            title="input",
            raw_text="raw citation",
        ),
        reconstruction_path=(
            ReconstructionPath.LOCAL_DB
            if local
            else ReconstructionPath.OFFICIAL_CITATION
        ),
        reconstructed_bibtex=source,
    )


def source(key: str, title: str) -> str:
    return (
        f"@inproceedings{{{key},\n"
        f"  title = {{{title}}},\n"
        "  author = {Devlin, Jacob},\n"
        "  booktitle = {Proceedings of NAACL},\n"
        "  year = {2019},\n"
        "}"
    )


def source_without_venue(key: str, title: str) -> str:
    return (
        f"@misc{{{key},\n"
        f"  title = {{{title}}},\n"
        "  author = {Devlin, Jacob},\n"
        "  year = {2019},\n"
        "}"
    )


def test_rule_candidates_are_deterministic():
    candidates = concept_candidates(
        "BERT: Pre-training of Deep Bidirectional Transformers"
    )

    assert candidates[:3] == ("bert", "pretraining", "deep")
    assert all("-" not in candidate for candidate in candidates)


def test_representative_title_name_is_selected_by_rules():
    assert representative_concept(
        "BERT: Pre-training of Deep Bidirectional Transformers"
    ) == "bert"
    assert representative_concept(
        "RoBERTa: A Robustly Optimized BERT Pretraining Approach"
    ) == "roberta"
    assert representative_concept(
        "Scaling Language Modeling with Qwen3"
    ) == "qwen3"
    assert representative_concept(
        "An Evaluation of Language Modeling"
    ) is None
    assert representative_concept(
        "Towards: Reliable Evaluation of Language Models"
    ) is None


def test_llm_generates_one_grounded_concept_word():
    generator = ConfiguredConceptGenerator([FakeProvider()])
    result = generator.generate(
        [
            ConceptRequest(
                ref_id="b1",
                title="Deep Bidirectional Transformers",
                raw_text="citation",
                candidates=("deep", "bidirectional", "transformers"),
            )
        ]
    )

    assert result["b1"].concept == "transformer"
    assert result["b1"].audit.task == LLMTask.KEY_CONCEPT_GENERATION
    assert len(result["b1"].audit.prompt_sha256) == 64


def test_llm_multiword_concept_is_rejected():
    class MultiwordProvider(FakeProvider):
        def generate(self, prompt, response_model):
            return ConceptGenerationResponse(
                concepts=[
                    ConceptGenerationItem.model_construct(
                        ref_id="b1",
                        concept="bidirectional-transformer-model",
                        source_terms=["bidirectional", "transformers"],
                    )
                ]
            )

    generator = ConfiguredConceptGenerator([MultiwordProvider()])
    result = generator.generate(
        [
            ConceptRequest(
                ref_id="b1",
                title="Deep Bidirectional Transformers",
                raw_text="citation",
                candidates=("deep", "bidirectional", "transformers"),
            )
        ]
    )

    assert result == {}


def test_ungrounded_llm_concept_falls_back_to_rules():
    generator = ConfiguredConceptGenerator([FakeProvider()])
    result = generator.generate(
        [
            ConceptRequest(
                ref_id="b1",
                title="Alpha Beta",
                raw_text="citation",
                candidates=("alpha", "beta"),
            )
        ]
    )
    assert result == {}


def test_concept_generation_is_batched():
    provider = BatchedProvider()
    generator = ConfiguredConceptGenerator([provider], batch_size=16)
    result = generator.generate(
        [
            ConceptRequest(
                ref_id=f"b{index}",
                title="Concept",
                raw_text="citation",
                candidates=("concept",),
            )
            for index in range(33)
        ]
    )
    assert provider.calls == 3
    assert len(result) == 33


def test_key_uses_rule_based_surname_year_venue_and_llm_concept():
    item = ready("b1", source("Original", "Language Model Evaluation"))
    CitationKeyGenerator(
        concept_generator=ExplicitGenerator(),
        validator=AcceptedValidator(),
    ).apply([item])

    assert "devlin-2019-naacl-language" in item.reconstructed_bibtex
    assert item.citation_key.concept == "language"
    assert item.citation_key.concept_source_terms == ["language"]
    assert item.citation_key.llm_invocation.provider == "local_vllm"


def test_high_confidence_rule_concept_skips_llm():
    class RecordingGenerator:
        def __init__(self):
            self.requests = None

        def generate(self, requests):
            self.requests = list(requests)
            return {}

    generator = RecordingGenerator()
    item = ready(
        "b1",
        source(
            "Original",
            "BERT: Pre-training of Deep Bidirectional Transformers",
        ),
    )
    CitationKeyGenerator(
        concept_generator=generator,
        validator=AcceptedValidator(),
    ).apply([item])

    assert generator.requests == []
    assert "devlin-2019-naacl-bert" in item.reconstructed_bibtex
    assert item.citation_key.concept == "bert"
    assert item.citation_key.concept_method == "rule_based"
    assert item.citation_key.llm_invocation is None


def test_missing_venue_uses_unknown_without_aborting_key_generation():
    item = ready(
        "b1",
        source_without_venue(
            "Original",
            "BERT: Pre-training of Deep Bidirectional Transformers",
        ),
    )
    CitationKeyGenerator(
        concept_generator=RuleGenerator(),
        validator=AcceptedValidator(),
    ).apply([item])

    assert item.outcome == ReconstructionOutcome.READY
    assert "devlin-2019-unknown-bert" in item.reconstructed_bibtex
    assert item.citation_key.venue == "unknown"


def test_invalid_key_record_isolated_from_other_references():
    invalid = ready("b1", "@misc{Broken, title = {Broken}}")
    valid = ready(
        "b2",
        source(
            "Original",
            "BERT: Pre-training of Deep Bidirectional Transformers",
        ),
    )
    CitationKeyGenerator(
        concept_generator=RuleGenerator(),
        validator=AcceptedValidator(),
    ).apply([invalid, valid])

    assert invalid.outcome == ReconstructionOutcome.MANUAL_REVIEW
    assert invalid.reconstructed_bibtex is None
    assert "author or editor is required" in invalid.review_reason
    assert valid.outcome == ReconstructionOutcome.READY
    assert "devlin-2019-naacl-bert" in valid.reconstructed_bibtex


def test_injected_multiword_concept_falls_back_to_one_rule_word():
    class MultiwordGenerator:
        def generate(self, requests):
            audit = LLMInvocationAudit(
                task=LLMTask.KEY_CONCEPT_GENERATION,
                provider="test",
                model="test",
                prompt_sha256="0" * 64,
                response={"concept": "language-model-evaluation"},
            )
            return {
                request.ref_id: GeneratedConcept(
                    concept="language-model-evaluation",
                    source_terms=("language", "model", "evaluation"),
                    audit=audit,
                )
                for request in requests
            }

    item = ready("b1", source("Original", "Language Model Evaluation"))
    CitationKeyGenerator(
        concept_generator=MultiwordGenerator(),
        validator=AcceptedValidator(),
    ).apply([item])

    assert "devlin-2019-naacl-language" in item.reconstructed_bibtex
    assert item.citation_key.concept == "language"
    assert "-" not in item.citation_key.concept
    assert item.citation_key.concept_method == "rule_based"


def test_collision_uses_next_rule_concept_before_hash():
    first = ready("b1", source("First", "BERT Transformers Language"))
    second = ready("b2", source("Second", "BERT Pretraining Language"))
    CitationKeyGenerator(
        concept_generator=RuleGenerator(),
        validator=AcceptedValidator(),
    ).apply([first, second])

    keys = {
        first.citation_key.generated_citation_key,
        second.citation_key.generated_citation_key,
    }
    assert "devlin-2019-naacl-bert" in keys
    assert any(key.endswith("-transformers") or key.endswith("-pretraining") for key in keys)


def test_local_db_key_is_preserved():
    item = ready(
        "b1",
        "@misc{StoredKey, title = {Stored Paper}}",
        local=True,
    )
    CitationKeyGenerator(
        concept_generator=RuleGenerator(),
        validator=AcceptedValidator(),
    ).apply([item])

    assert item.citation_key.generated_citation_key == "StoredKey"
    assert item.citation_key.key_preserved is True
