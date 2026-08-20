"""Stable ContentItem identities shared by ActorOps runtimes."""

from __future__ import annotations

import hashlib


def stable_actor_item_id(platform: str, source_key: str, native_id: str) -> str:
    """Return the legacy-compatible opaque identity for one Actor item."""

    normalized_platform = str(platform).strip().casefold()
    digest = hashlib.sha256(
        "\x1f".join((normalized_platform, str(source_key), str(native_id))).encode(
            "utf-8"
        )
    ).hexdigest()[:24]
    return f"actor:{normalized_platform}:{digest}"


__all__ = ["stable_actor_item_id"]
