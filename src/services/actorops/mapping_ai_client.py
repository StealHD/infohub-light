"""Actor field-mapping-only AI transport policy."""

from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI

from ...ai.client import AIClient, OpenAIClient, create_ai_client
from ...models import AIConfig, AIProvider


class ActorMappingDeepSeekClient(OpenAIClient):
    """Disable reasoning only for schema-to-Manifest JSON mapping calls."""

    def __init__(
        self,
        config: AIConfig,
        *,
        api_key: str | None = None,
        max_retries: int | None = None,
        timeout_seconds: float | None = None,
        allow_compatibility_fallback: bool = False,
    ) -> None:
        if api_key is None:
            super().__init__(
                config, max_retries=max_retries,
                timeout_seconds=timeout_seconds,
                allow_compatibility_fallback=allow_compatibility_fallback,
            )
            return
        self.config = config
        kwargs: dict[str, Any] = {
            "api_key": api_key,
            "base_url": config.base_url or self._DEFAULT_BASE_URLS["deepseek"],
        }
        if max_retries is not None:
            kwargs["max_retries"] = max_retries
        if timeout_seconds is not None:
            kwargs["timeout"] = timeout_seconds
        self.client = AsyncOpenAI(**kwargs)
        self.model = config.model
        self.temperature = config.temperature
        self.max_tokens = config.max_tokens
        self.provider = config.provider.value
        self._allow_compatibility_fallback = allow_compatibility_fallback
        self._supports_temperature = True
        self.last_completion_metrics = None

    async def _do_request(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        include_temperature: bool,
    ) -> Any:
        request_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "extra_body": {"thinking": {"type": "disabled"}},
        }
        if include_temperature:
            request_kwargs["temperature"] = temperature
        return await self.client.chat.completions.create(**request_kwargs)


def create_actor_mapping_ai_client(
    config: AIConfig,
    *,
    api_key: str | None = None,
    timeout_seconds: float = 90,
) -> AIClient:
    """Build an isolated single-attempt client for Actor field mapping."""

    if config.provider == AIProvider.DEEPSEEK:
        return ActorMappingDeepSeekClient(
            config,
            api_key=api_key,
            max_retries=0,
            timeout_seconds=timeout_seconds,
            allow_compatibility_fallback=False,
        )
    if api_key is not None:
        raise ValueError("direct Actor mapping secret is unsupported for provider")
    return create_ai_client(
        config,
        single_attempt=True,
        timeout_seconds=timeout_seconds,
    )


__all__ = ["ActorMappingDeepSeekClient", "create_actor_mapping_ai_client"]
