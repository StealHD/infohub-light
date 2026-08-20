"""X profile identity validation."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from ...ports import TargetSpec


_HANDLE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_RESERVED = frozenset(
    {"compose", "explore", "home", "i", "messages", "notifications", "search", "settings"}
)


def normalize_profile_target(raw: object) -> TargetSpec:
    value = str(raw or "").strip()
    if not value:
        raise ValueError("X profile target is required")
    parsed = urlsplit(value)
    if parsed.scheme:
        if (
            parsed.scheme.casefold() != "https"
            or str(parsed.hostname or "").casefold()
            not in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}
            or parsed.port not in {None, 443}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("X profile target is unsafe")
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 1:
            raise ValueError("X profile target must identify one account")
        handle = parts[0]
    else:
        if "://" in value:
            raise ValueError("X profile target is unsafe")
        handle = value.lstrip("@").strip("/")
    if not _HANDLE.fullmatch(handle) or handle.casefold() in _RESERVED:
        raise ValueError("X profile handle is invalid")
    return TargetSpec(
        canonical_url=f"https://x.com/{handle}",
        native_id=None,
        handle=handle,
    )
