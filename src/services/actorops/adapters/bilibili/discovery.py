"""Schema-proven Bilibili profile-video input and output mappings."""

from __future__ import annotations

import json
from collections.abc import Mapping

from ...ports import DiscoveryMapping
from .._discovery import deterministic_input_plan


def input_options(revision):
    properties = revision.input_schema.get("properties", {})
    constants = {}
    for field in ("searchType", "mode", "action", "operation"):
        schema = properties.get(field, {})
        choices = schema.get("enum", []) if isinstance(schema, Mapping) else []
        mode = next((value for value in (
            "user_videos", "user-videos", "creator_videos", "userVideos", "creatorVideos", "uploads", "list_user_videos",
        ) if value in choices), None)
        if mode is not None:
            constants[field] = mode
    return {
        "input_keys": ("mid", "uid", "userId", "user_id", "creatorId", "userIds", "creatorIds",
                       "userUrls", "creatorUrls", "profileUrls", "startUrls", "profileUrl", "userUrl", "profile_url"),
        "identity_ref": "target.native_id",
        "list_native_id_input_keys": ("userIds", "creatorIds"),
        "list_url_input_keys": ("userUrls", "creatorUrls", "profileUrls", "startUrls"),
        "url_input_keys": ("profileUrl", "userUrl", "profile_url"),
        "max_items_input_keys": ("maxResultsPerInput", "maxItems", "max_items", "maxResults", "limit", "maxVideos", "maxVideosPerCreator"),
        "input_constants": constants,
    }


_FIELDS = {
    "native_id": (("bvid", "videoId", "aid", "content_id", "id"), "to_string"),
    "url": (("url", "videoUrl", "video_url", "share_url", "link"), "normalize_url"),
    "published_at": (("pubdate", "publishedAt", "publishDate", "publishTimestamp", "publish_time", "created", "published_at", "createTime"), "parse_datetime"),
    "title": (("title", "videoTitle"), "strip_html"),
    "text": (("desc", "description", "content"), "strip_html"),
    "source_native_id": (("owner.mid", "creatorId", "authorMid", "creator_mid", "authorId", "uploaderId", "author_user_id", "userId", "mid", "uid"), "to_string"),
    "author": (("owner.name", "creatorName", "authorName", "uploaderName", "author_name", "author"), "to_string"),
    "author_avatar_url": (("owner.face", "creatorAvatar", "authorAvatar", "uploaderAvatar", "author_avatar_url", "avatar", "face"), "normalize_url"),
    "thumbnail_url": (("pic", "cover", "thumbnailUrl", "cover_image_url", "thumbnail"), "normalize_url"),
    "like_count": (("stat.like", "like_count", "likes", "likeCount"), "to_integer"),
    "comment_count": (("stat.reply", "reply_count", "replyCount", "comment_count", "comments", "commentCount"), "to_integer"),
    "share_count": (("stat.share", "share_count", "shares", "shareCount"), "to_integer"),
    "view_count": (("stat.view", "view_count", "views", "viewCount"), "to_integer"),
}


def _pointer(schema, name):
    node = schema
    parts = name.split(".")
    for part in parts:
        properties = node.get("properties", {}) if isinstance(node, Mapping) else {}
        node = properties.get(part)
        if node is None:
            return None
    if isinstance(node, Mapping):
        kinds = node.get("type")
        if isinstance(kinds, str):
            kinds = [kinds]
        if isinstance(kinds, list) and any(kind in ("object", "array") for kind in kinds):
            return None
    return "/" + "/".join(parts)


def map_manifest(revision):
    plan, error = deterministic_input_plan(revision, **input_options(revision))
    if not plan:
        return DiscoveryMapping(None, error)
    outputs = {}
    for field, (aliases, transform) in _FIELDS.items():
        pointers = [p for name in aliases if (p := _pointer(revision.output_schema, name))][:6]
        if pointers:
            transforms = (["pick_first"] if len(pointers) > 1 else []) + [transform]
            outputs[field] = {"pointers": pointers, "transforms": transforms}
    if not {"native_id", "url", "published_at", "source_native_id"} <= outputs.keys() or not (
        "title" in outputs or "text" in outputs
    ):
        return DiscoveryMapping(None, "actorops_discovery_mapping_unresolved")
    return DiscoveryMapping(json.dumps({
        "version": 1, "actor_id": revision.actor_id, "build_number": revision.build_number,
        "input": json.loads(plan)["input"], "output": outputs,
        "semantics": {
            "identity": {"output_field": "source_native_id", "target_ref": "target.native_id", "match": "exact"},
            "url_host_allowlist": ["bilibili.com"],
        },
    }, ensure_ascii=False, sort_keys=True))


def refine_mapping(revision, mapping):
    if mapping is None or not mapping.manifest_json:
        return mapping
    try:
        value = json.loads(mapping.manifest_json)
    except (TypeError, ValueError):
        return mapping
    if not isinstance(value, Mapping) or value.get("structures") or value.get("row_extraction"):
        return mapping
    canonical = map_manifest(revision)
    return canonical if canonical.manifest_json else mapping
