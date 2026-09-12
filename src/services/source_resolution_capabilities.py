"""Pure capability projection for registry-declared source resolvers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_YOUTUBE_RESOLUTION = {
    "supported": True,
    "strategy": "agent_web",
    "official_hosts": ["www.youtube.com"],
    "locator_kinds": [
        "handle",
        "channel_url",
        "channel_id",
        "channel_feed",
    ],
    "max_candidates": 5,
}


def source_resolution_capability(source_type: str) -> dict[str, Any]:
    """Return an isolated capability value for a canonical registry type."""

    capability = (
        _YOUTUBE_RESOLUTION if source_type == "youtube" else {"supported": False}
    )
    return deepcopy(capability)
