"""YouTube channel identity validation."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlsplit

from ...ports import TargetSpec


_CHANNEL_ID = re.compile(r"^UC[A-Za-z0-9_-]{22}$")


def normalize_channel_target(raw: object) -> TargetSpec:
    value = str(raw or "").strip()
    parsed = urlsplit(value)
    if (
        parsed.scheme.casefold() != "https"
        or str(parsed.hostname or "").casefold() not in {"youtube.com", "www.youtube.com"}
        or parsed.port not in {None, 443}
        or parsed.fragment
    ):
        raise ValueError("YouTube channel target is unsafe")
    parts = [part for part in parsed.path.split("/") if part]
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    if parsed.path == "/feeds/videos.xml":
        if len(pairs) != 1 or pairs[0][0] != "channel_id" or not _CHANNEL_ID.fullmatch(pairs[0][1]):
            raise ValueError("YouTube feed channel_id is invalid")
        channel_id = pairs[0][1]
        return TargetSpec(
            canonical_url=f"https://www.youtube.com/channel/{channel_id}",
            native_id=channel_id,
            native_url=value,
        )
    if len(parts) == 2 and parts[0] == "channel" and not pairs and _CHANNEL_ID.fullmatch(parts[1]):
        return TargetSpec(
            canonical_url=f"https://www.youtube.com/channel/{parts[1]}",
            native_id=parts[1],
            native_url=value,
        )
    if len(parts) == 1 and parts[0].startswith("@") and len(parts[0]) > 1 and not pairs:
        handle = parts[0][1:]
        return TargetSpec(
            canonical_url=f"https://www.youtube.com/@{handle}",
            handle=handle,
            native_url=value,
        )
    raise ValueError("YouTube target must identify one channel")
