"""Worker composition for value-free per-Actor output mapping repair."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(slots=True)
class CanaryOutputMappingAI:
    """Uses the approved global AI configuration only when repair is needed."""

    client: Any
    store: Any
    workspace_id: str
    user_id: str
    provider: str

    async def propose_output_mapping(
        self, request: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        from .quota import QuotaService

        QuotaService(self.store).admit_ai_attempt(
            workspace_id=self.workspace_id,
            user_id=self.user_id,
            provider=self.provider,
        )
        raw = await self.client.complete(
            "Return one strict JSON object only. Map only the supplied output "
            "field paths. Never return values, targets, URLs, Actor IDs, "
            "Build IDs, credentials, code, templates, or explanations.",
            json.dumps(request, ensure_ascii=False, sort_keys=True),
            temperature=0.0,
            max_tokens=640,
        )
        try:
            result = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return result if isinstance(result, Mapping) else None

    async def aclose(self) -> None:
        close = getattr(self.client, "aclose", None)
        if callable(close):
            result = close()
            if hasattr(result, "__await__"):
                await result


def open_canary_output_mapping_ai(
    *, store: Any, data_dir: str, ops: Any, job: Mapping[str, Any]
) -> CanaryOutputMappingAI | None:
    """Return no repairer when the independently configured AI is unavailable."""

    from ..ai.client import create_ai_client
    from .apify_discovery_ai import resolve_global_discovery_ai

    settings = ops.get_discovery_settings()
    if not bool(settings.get("enabled")):
        return None
    global_ai = resolve_global_discovery_ai(
        store,
        data_dir=data_dir,
        workspace_id=str(job["workspace_id"]),
        secret_ref_id=(
            str(settings["secret_ref_id"])
            if settings.get("secret_ref_id")
            else None
        ),
    )
    if not global_ai.ready or global_ai.config is None:
        return None
    config = global_ai.config.model_copy(
        update={"enabled": True, "temperature": 0.0, "max_tokens": 640}
    )
    return CanaryOutputMappingAI(
        client=create_ai_client(config, single_attempt=True, timeout_seconds=90),
        store=store,
        workspace_id=str(job["workspace_id"]),
        user_id=str(job["user_id"]),
        provider=str(global_ai.provider),
    )


async def close_canary_output_mapping_ai(repairer: Any) -> None:
    if repairer is not None:
        await repairer.aclose()


__all__ = [
    "CanaryOutputMappingAI",
    "close_canary_output_mapping_ai",
    "open_canary_output_mapping_ai",
]
