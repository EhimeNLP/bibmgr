"""Provider-independent interface for structured LLM tasks."""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel


ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class LLMProviderError(RuntimeError):
    """Raised when a configured LLM provider cannot return a reconstruction."""


class LLMProvider(Protocol):
    """Generate one structured response from a prepared prompt."""

    def generate(
        self,
        prompt: str,
        response_model: type[ResponseModel],
    ) -> ResponseModel:
        """Return a provider-independent structured result."""
