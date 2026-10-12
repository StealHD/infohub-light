"""Bilibili target, video URL and legacy RSS article identity."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from ...ports import TargetSpec
from ...identity import legacy_rss_item_id


_UID = re.compile(r"^[1-9][0-9]{0,18}$")
_VIDEO = re.compile(r"^(BV[0-9A-Za-z]{10}|av[1-9][0-9]*)$")


def normalize_profile_target(raw: object) -> TargetSpec:
    if isinstance(raw, bool):
        raise ValueError("Bilibili UID is invalid")
    value = str(raw or "").strip()
    uid = value
    if "://" in value:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.hostname != "space.bilibili.com"
                or parsed.port not in {None, 443} or parsed.username or parsed.password
                or parsed.query or parsed.fragment or "//" in parsed.path):
            raise ValueError("Bilibili profile target is unsafe")
        uid = parsed.path.strip("/")
    if not _UID.fullmatch(uid) or int(uid) > 9_223_372_036_854_775_807:
        raise ValueError("Bilibili target must identify one positive UID")
    return TargetSpec(canonical_url=f"https://space.bilibili.com/{uid}", native_id=uid)


def canonical_video_url(raw: object) -> str:
    parsed = urlsplit(str(raw or ""))
    if (parsed.scheme not in {"https", "http"}
            or parsed.hostname not in {"www.bilibili.com", "bilibili.com", "m.bilibili.com"}
            or parsed.username or parsed.password or parsed.port not in {None, 443, 80}):
        raise ValueError("Bilibili item is not a public video")
    parts = parsed.path.strip("/").split("/")
    if len(parts) != 2 or parts[0] != "video" or not _VIDEO.fullmatch(parts[1]):
        raise ValueError("Bilibili item is not a public video")
    return f"https://www.bilibili.com/video/{parts[1]}"


def rss_article_id(uid: str, video_url: str) -> str:
    key = f"rss:rsshub:bilibili:user_video:{uid}"
    return legacy_rss_item_id(key, video_url, managed=True)
