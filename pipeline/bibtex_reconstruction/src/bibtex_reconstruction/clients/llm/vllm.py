"""Local vLLM adapter with deterministic JSON-schema-constrained output."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import requests

from .base import LLMProviderError
from .openai_compatible import OpenAICompatibleProvider


class VLLMProvider(OpenAICompatibleProvider):
    """Use a local or HTTPS vLLM server for structured inference."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout: int = 120,
        temperature: float = 0.0,
        max_output_tokens: int = 2048,
        seed: int = 0,
        http_client: Any = requests,
    ) -> None:
        self._validate_endpoint(base_url)
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout=timeout,
            use_json_schema=True,
            strict_json_schema=True,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            seed=seed,
            extra_body={
                "chat_template_kwargs": {
                    "enable_thinking": False,
                }
            },
            http_client=http_client,
            provider_label="local_vllm",
        )

    @staticmethod
    def _validate_endpoint(base_url: str) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"}:
            raise LLMProviderError(
                "vLLM base URL must use HTTP or HTTPS"
            )
        if parsed.scheme == "http" and parsed.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise LLMProviderError(
                "plain HTTP is only allowed for a loopback vLLM endpoint"
            )
