"""Adapter for OpenAI and OpenAI-compatible Chat Completions APIs."""

from __future__ import annotations

from typing import Any

import requests
from pydantic import BaseModel

from .base import LLMProviderError, ResponseModel


class OpenAICompatibleProvider:
    """Generate structured output through a Chat Completions compatible API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout: int = 120,
        use_json_schema: bool = False,
        strict_json_schema: bool = False,
        temperature: float = 0.0,
        max_output_tokens: int = 2048,
        seed: int | None = None,
        extra_body: dict[str, object] | None = None,
        http_client: Any = requests,
        provider_label: str = "api_llm",
    ) -> None:
        if not model:
            raise LLMProviderError(
                "BIBTEX_RECONSTRUCTION_LLM_MODEL is not configured"
            )
        if not base_url:
            raise LLMProviderError(
                "BIBTEX_RECONSTRUCTION_LLM_BASE_URL is required for "
                "provider 'openai_compatible'"
            )

        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.use_json_schema = use_json_schema
        self.strict_json_schema = strict_json_schema
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.seed = seed
        self.extra_body = dict(extra_body or {})
        self.http_client = http_client
        self.provider_label = provider_label

    def generate(
        self,
        prompt: str,
        response_model: type[ResponseModel],
    ) -> ResponseModel:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": self._response_format(response_model),
            "temperature": self.temperature,
            "max_tokens": self.max_output_tokens,
        }
        if self.seed is not None:
            payload["seed"] = self.seed
        payload.update(self.extra_body)

        try:
            response = self.http_client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
            if not isinstance(content, str) or not content.strip():
                raise ValueError("response content is empty")
            return response_model.model_validate_json(content)
        except Exception as exc:
            raise LLMProviderError(
                "OpenAI-compatible provider failed: "
                f"{type(exc).__name__}"
            ) from exc

    def _response_format(
        self,
        response_model: type[BaseModel],
    ) -> dict[str, object]:
        if not self.use_json_schema:
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "bibtex_reconstruction",
                "strict": self.strict_json_schema,
                "schema": response_model.model_json_schema(),
            },
        }
