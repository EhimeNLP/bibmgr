"""Provider-independent interface for semantic reconstruction LLMs."""

from __future__ import annotations

from typing import Protocol

from ...domain import LLMReconstruction


class LLMProviderError(RuntimeError):
    """Raised when a configured LLM provider cannot return a reconstruction."""


class LLMProvider(Protocol):
    """Generate one structured reconstruction from a prepared prompt."""

    def generate(self, prompt: str) -> LLMReconstruction:
        """Return a provider-independent reconstruction result."""
