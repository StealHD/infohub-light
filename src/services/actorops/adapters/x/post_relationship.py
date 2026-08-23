"""Deterministic X post-relationship evidence for profile timelines."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


_REPLY_FLAG_PATHS = (
    ("isReply",),
    ("is_reply",),
    ("tweet", "isReply"),
    ("tweet", "is_reply"),
)
_REPLY_PARENT_PATHS = (
    ("inReplyToStatusId",),
    ("inReplyToStatusIdStr",),
    ("in_reply_to_status_id",),
    ("in_reply_to_status_id_str",),
    ("inReplyToTweetId",),
    ("in_reply_to_tweet_id",),
    ("replyToTweetId",),
    ("reply_to_tweet_id",),
    ("replyToId",),
    ("reply_to_id",),
    ("inReplyTo",),
    ("replyTo",),
    ("legacy", "in_reply_to_status_id_str"),
    ("tweet", "legacy", "in_reply_to_status_id_str"),
)
_RELATION_TYPE_PATHS = (
    ("relationshipType",),
    ("postType",),
    ("tweetType",),
    ("recordType",),
    ("type",),
)
_REPLY_TYPES = frozenset({"reply", "tweet_reply", "tweet-reply"})


def exclude_x_reply_rows(
    rows: Sequence[Mapping[str, object]],
) -> tuple[tuple[Mapping[str, object], ...], int]:
    """Return non-reply rows and the number removed using explicit evidence."""

    kept: list[Mapping[str, object]] = []
    excluded = 0
    for row in rows:
        if is_x_reply(row):
            excluded += 1
        else:
            kept.append(row)
    return tuple(kept), excluded


def is_x_reply(row: Mapping[str, object]) -> bool:
    """Classify only explicit reply evidence; text and reply counts are ignored."""

    if any(_is_true(_read_path(row, path)) for path in _REPLY_FLAG_PATHS):
        return True
    if any(_has_relation(_read_path(row, path)) for path in _REPLY_PARENT_PATHS):
        return True
    return any(
        str(_read_path(row, path) or "").strip().casefold() in _REPLY_TYPES
        for path in _RELATION_TYPE_PATHS
    )


def _read_path(row: Mapping[str, object], path: tuple[str, ...]) -> object:
    value: object = row
    for key in path:
        if not isinstance(value, Mapping) or key not in value:
            return None
        value = value[key]
    return value


def _is_true(value: object) -> bool:
    if value is True or value == 1:
        return True
    return isinstance(value, str) and value.strip().casefold() in {
        "1",
        "true",
        "yes",
    }


def _has_relation(value: object) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping) or isinstance(value, Sequence):
        return bool(value)
    return value != 0


__all__ = ["exclude_x_reply_rows", "is_x_reply"]
