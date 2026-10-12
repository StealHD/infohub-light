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


def legacy_rss_item_id(feed_identity: str, entry_identity: str, *, managed: bool) -> str:
    """Preserve the RSS adapter's feed and GUID hash formula across transport changes."""
    feed_id = (
        hashlib.sha256(feed_identity.encode("utf-8")).hexdigest()[:16]
        if managed else feed_identity.split("//", 1)[-1].replace("/", "_")
    )
    entry_id = hashlib.sha256(entry_identity.encode("utf-8")).hexdigest()[:16]
    return f"rss:{feed_id}:{entry_id}"


__all__ = ["stable_actor_item_id", "legacy_rss_item_id"]
