"""Verify local vLLM inference and JSON-schema constrained output."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .clients.llm import LLMProviderError, create_local_vllm_provider
from .config import settings


class VLLMHealthResponse(BaseModel):
    status: Literal["ok"]
    capability: Literal["structured_output"]


def main() -> int:
    try:
        provider = create_local_vllm_provider()
        result = provider.generate(
            (
                "This is a health check. Return status='ok' and "
                "capability='structured_output' using the required schema."
            ),
            VLLMHealthResponse,
        )
    except LLMProviderError as exc:
        print(f"vLLM health check failed: {exc}")
        return 1
    print(
        "vLLM health check passed "
        f"model={settings.local_llm_model} "
        f"endpoint={settings.local_llm_base_url} "
        f"capability={result.capability}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
