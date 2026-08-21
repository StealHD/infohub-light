"""Safe fallback when optional discovery ranking cannot produce JSON."""

from __future__ import annotations

from typing import Any


def unavailable_proposals(error: Exception) -> tuple[dict[str, tuple[Any, ...]], str]:
    """Keep deterministic candidates while recording the bounded AI failure."""

    code = str(getattr(error, "code", "discovery_ai_unavailable"))[:128]
    return {"proposals": ()}, code


def ai_unavailable_rejection(error_code: str) -> dict[str, str]:
    """Return a value-free rejection suitable for the persisted summary."""

    return {"actor_id": "ai-response", "reason": error_code}


__all__ = ["ai_unavailable_rejection", "unavailable_proposals"]
