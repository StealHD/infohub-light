"""Bounded mapping-only path discovery for presentation evidence."""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Mapping


_MAX_OBJECTS = 256
_MAX_KEYS = 4_096
_MAX_DEPTH = 8
PRESENTATION_AVATAR_FALLBACK_POINTER = "/__actorops_target/avatar_url"
_NORMALIZE_KEY = re.compile(r"[^a-z0-9]+")
_PRIORITY_CONTAINERS = frozenset(
    {"user", "owner", "author", "profile", "account", "channel"}
)
_ALIASES = {
    "x": (
        "userprofileimageurlhttps", "userprofileimageurl",
        "profileimageurlhttps", "profileimageurl", "profilepictureurl",
        "authoravatarurl", "avatarurl", "profilepicture", "avatar",
    ),
    "instagram": (
        "profilepicurlhd", "profilepicurl", "profilepictureurl",
        "authorprofilepicurl", "ownerprofilepicurl", "authoravatarurl",
        "profilepicture", "avatarurl", "avatar",
    ),
    "youtube": (
        "channelthumbnailurl", "authorthumbnailurl", "channelavatarurl",
        "channelthumbnail", "authorthumbnail", "thumbnailurl",
        "profilepicture", "avatarurl", "avatar",
    ),
}


def normalized_key(value: str) -> str:
    return _NORMALIZE_KEY.sub("", value.casefold())


def avatar_alias_rank(platform: str) -> dict[str, int]:
    aliases = _ALIASES.get(str(platform).casefold(), ())
    return {value: index for index, value in enumerate(aliases)}


def avatar_alias_keys(platform: str) -> frozenset[str]:
    return frozenset(avatar_alias_rank(platform))


def json_pointer(parts: tuple[str, ...]) -> str:
    return "/" + "/".join(
        value.replace("~", "~0").replace("/", "~1") for value in parts
    )


def avatar_candidates(
    row: Mapping[str, object], aliases: Mapping[str, int]
) -> list[tuple[int, int, str]]:
    """Traverse only mappings so scalar noise cannot exhaust path discovery."""

    queue = deque([(row, (), 0)])
    seen: set[int] = set()
    candidates: list[tuple[int, int, str]] = []
    object_count = key_count = 0
    while queue and object_count < _MAX_OBJECTS:
        node, path, depth = queue.popleft()
        marker = id(node)
        if marker in seen:
            continue
        seen.add(marker)
        object_count += 1
        priority: list[tuple[Mapping[str, object], tuple[str, ...], int]] = []
        others: list[tuple[Mapping[str, object], tuple[str, ...], int]] = []
        for raw_key, value in node.items():
            key_count += 1
            if key_count > _MAX_KEYS:
                return candidates
            if not isinstance(raw_key, str):
                continue
            child_path = (*path, raw_key)
            key = normalized_key(raw_key)
            rank = aliases.get(key)
            if rank is not None and isinstance(value, str):
                candidates.append((rank, len(child_path), json_pointer(child_path)))
            if depth < _MAX_DEPTH and isinstance(value, Mapping):
                child = (value, child_path, depth + 1)
                (priority if key in _PRIORITY_CONTAINERS else others).append(child)
        queue.extendleft(reversed(priority))
        queue.extend(others)
    return candidates


__all__ = [
    "avatar_alias_keys",
    "avatar_alias_rank",
    "avatar_candidates",
    "json_pointer",
    "normalized_key",
    "PRESENTATION_AVATAR_FALLBACK_POINTER",
]
