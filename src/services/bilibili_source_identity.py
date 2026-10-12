"""Pure compatibility identity for controlled and legacy Bilibili RSS rows."""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import urlsplit

from ..rsshub import normalize_rsshub_route


_LEGACY_PATH = re.compile(r"^/(?:[^/?#]+/)*bilibili/user/video/([0-9]{1,20})(?:/1)?/?$")


def bilibili_source_uid(config: object) -> str | None:
    if not isinstance(config, Mapping):
        return None
    if config.get("provider") == "rsshub":
        try:
            route = normalize_rsshub_route(
                site=config.get("site"), route_key=config.get("route_key"),
                params=config.get("params"),
            )
            return route["params"]["uid"] if (route["site"], route["route_key"]) == ("bilibili", "user_video") else None
        except ValueError:
            return None
    try:
        parsed = urlsplit(str(config.get("url") or ""))
        match = _LEGACY_PATH.fullmatch(parsed.path)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.fragment
                or match is None):
            return None
        route = normalize_rsshub_route(
            site="bilibili", route_key="user_video", params={"uid": match.group(1)},
        )
        return route["params"]["uid"]
    except ValueError:
        return None


def is_bilibili_source(source_type: str, config: object) -> bool:
    return source_type == "rss" and bilibili_source_uid(config) is not None


def bilibili_public_target(config: object) -> str:
    uid = bilibili_source_uid(config)
    if uid is None:
        raise ValueError("actorops_v2_target_invalid")
    return f"https://space.bilibili.com/{uid}"
