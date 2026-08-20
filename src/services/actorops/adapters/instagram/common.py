"""Instagram profile identity validation."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from ...ports import TargetSpec


_USERNAME = re.compile(r"^[A-Za-z0-9._]{1,30}$")
_RESERVED = frozenset(
    {"about", "accounts", "developer", "direct", "directory", "explore", "p", "reel", "reels", "stories", "web"}
)


def normalize_profile_target(raw: object) -> TargetSpec:
    value = str(raw or "").strip()
    if not value:
        raise ValueError("Instagram profile target is required")
    parsed = urlsplit(value)
    if parsed.scheme:
        if (
            parsed.scheme.casefold() != "https"
            or str(parsed.hostname or "").casefold()
            not in {"instagram.com", "www.instagram.com"}
            or parsed.port not in {None, 443}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Instagram profile target is unsafe")
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 1:
            raise ValueError("Instagram target must identify one account")
        username = parts[0]
    else:
        if "://" in value:
            raise ValueError("Instagram profile target is unsafe")
        username = value.lstrip("@").strip("/")
    if (
        not _USERNAME.fullmatch(username)
        or ".." in username
        or username.startswith(".")
        or username.endswith(".")
        or username.casefold() in _RESERVED
    ):
        raise ValueError("Instagram username is invalid")
    return TargetSpec(
        canonical_url=f"https://www.instagram.com/{username}/",
        native_id=None,
        handle=username,
    )
