"""Deterministic, source-neutral Feed presentation projection."""

from __future__ import annotations

import html
import re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlparse

from ..models import ContentItem, SourceType


PRESENTATION_VERSION = 1
SOURCE_EXCERPT_MAX_CHARS = 600
ACTION_SUGGESTION_MAX_CHARS = 80

_CONTENT_KINDS = {
    "facebook": "post_body",
    "github": "event_description",
    "hackernews": "discussion",
    "instagram": "caption",
    "reddit": "discussion",
    "rss": "feed_summary",
    "telegram": "message",
    "twitter": "post_body",
}
_GENERATED_TITLE_SOURCES = {"facebook", "github", "instagram", "telegram", "twitter"}
_AUTHOR_KINDS = {"person", "account", "channel", "organization", "unknown"}
_ANALYSIS_STATUSES = {"ai", "fallback", "personal_only", "disabled"}
CONTENT_FORMATS = {
    "article",
    "video",
    "image",
    "gallery",
    "audio",
    "social_post",
    "discussion",
    "release",
    "other",
}
FORMAT_ORIGINS = {"upstream", "deterministic", "ai", "fallback"}
_SOCIAL_SOURCE_TYPES = {
    "apify_social",
    "facebook",
    "instagram",
    "telegram",
    "twitter",
    "x",
}
_VIDEO_HOSTS = {
    "b23.tv",
    "bilibili.com",
    "m.bilibili.com",
    "youtu.be",
    "youtube.com",
    "www.bilibili.com",
    "www.youtube.com",
}

_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1>",
    flags=re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _isoformat(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _bounded_text(value: Any, limit: int) -> tuple[str, bool]:
    text = _WHITESPACE_RE.sub(" ", str(value or "")).strip()
    if len(text) <= limit:
        return text, False
    return text[: max(0, limit - 1)].rstrip() + "…", True


def _clean_source_excerpt(value: Any) -> str:
    text = str(value or "")
    if "--- Top Comments ---" in text:
        text = text.split("--- Top Comments ---", 1)[0]
    text = _SCRIPT_STYLE_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)
    return html.unescape(text)


def _unique(values: Iterable[Any], *, limit: int) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _number(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return int(parsed) if parsed.is_integer() else parsed


def _first_number(metadata: dict[str, Any], *keys: str) -> int | float | None:
    for key in keys:
        if key in metadata:
            value = _number(metadata.get(key))
            if value is not None:
                return value
    return None


def _section(value: Any) -> dict[str, Any]:
    return deepcopy(value) if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    return _unique(value if isinstance(value, list) else [], limit=8)


def normalize_content_format(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in CONTENT_FORMATS else None


def _nonnegative_int(value: Any) -> int:
    parsed = _number(value)
    if parsed is None:
        return 0
    return max(0, int(parsed))


def _url_host(value: Any) -> str:
    try:
        return (urlparse(str(value or "")).hostname or "").lower()
    except ValueError:
        return ""


def resolve_content_format(
    *,
    source_type: Any,
    catalog_type: Any = "",
    platform: Any = "",
    url: Any = "",
    content_kind: Any = "",
    metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Resolve display format without creating a second inference path."""

    meta = metadata or {}
    upstream = normalize_content_format(meta.get("upstream_content_format"))
    if upstream:
        return upstream, "upstream"

    source = str(source_type or "").strip().lower()
    catalog = str(catalog_type or "").strip().lower()
    platform_name = str(platform or "").strip().lower()
    kind = str(content_kind or "").strip().lower()
    image_count = _nonnegative_int(
        meta.get("media_image_count", meta.get("total_image_count"))
    )
    video_count = _nonnegative_int(meta.get("media_video_count"))
    audio_count = _nonnegative_int(meta.get("media_audio_count"))

    if video_count:
        return "video", "deterministic"
    if audio_count:
        return "audio", "deterministic"
    if image_count > 1 and ({source, catalog, platform_name} & _SOCIAL_SOURCE_TYPES):
        return "gallery", "deterministic"
    if image_count == 1 and ({source, catalog, platform_name} & _SOCIAL_SOURCE_TYPES):
        return "image", "deterministic"
    if _url_host(url) in _VIDEO_HOSTS:
        return "video", "deterministic"
    if catalog == "github_release" or (source == "github" and kind == "release_notes"):
        return "release", "deterministic"
    if source in {"reddit", "hackernews"} or kind == "discussion":
        return "discussion", "deterministic"

    inferred = normalize_content_format(meta.get("ai_content_format"))
    if inferred:
        return inferred, "ai"

    if source == "rss" or catalog == "rss":
        return "article", "fallback"
    if {source, catalog, platform_name} & _SOCIAL_SOURCE_TYPES:
        return "social_post", "fallback"
    if source == "github" or catalog == "github_user":
        return "article", "fallback"
    return "other", "fallback"


def _presentation_media(
    *,
    title: str,
    media_urls: Any,
    total_image_count: Any,
) -> dict[str, Any] | None:
    urls = _unique(media_urls if isinstance(media_urls, list) else [], limit=6)
    total = max(_nonnegative_int(total_image_count), len(urls))
    if not urls and total == 0:
        return None
    return {
        "images": [{"url": url, "alt": title or "内容图片"} for url in urls],
        "count": len(urls),
        "total_image_count": total,
        "truncated": total > len(urls),
    }


def complete_content_presentation(item: dict[str, Any]) -> dict[str, Any]:
    """Return a complete v1 projection for legacy or partially projected items."""

    presentation = _section(item.get("presentation"))
    source_type = str(item.get("source_type") or "").strip().lower()
    item_url = str(item.get("url") or "")

    source = _section(presentation.get("source"))
    source.setdefault("id", str(item.get("source_id") or ""))
    source.setdefault("catalog_type", source_type)
    source.setdefault("platform", source_type)
    source.setdefault("name", str(item.get("source") or source_type))

    author = _section(presentation.get("author"))
    author.setdefault("name", str(item.get("author") or ""))
    if author.get("kind") not in _AUTHOR_KINDS:
        author["kind"] = "unknown"

    timing = _section(presentation.get("timing"))
    timing.setdefault("published_at", str(item.get("published_at") or ""))
    timing.setdefault("fetched_at", str(item.get("fetched_at") or ""))

    links = _section(presentation.get("links"))
    links.setdefault("canonical_url", item_url)
    links.setdefault("source_url", str(item.get("discussion_url") or item_url))

    content = _section(presentation.get("content"))
    content.setdefault("title", str(item.get("title") or ""))
    content.setdefault(
        "title_origin",
        "generated" if source_type in _GENERATED_TITLE_SOURCES else "native",
    )
    content.setdefault(
        "excerpt",
        str(item.get("excerpt") or item.get("summary_zh") or ""),
    )
    content.setdefault("content_kind", _CONTENT_KINDS.get(source_type, "metadata_only"))
    content.setdefault("excerpt_truncated", False)
    if normalize_content_format(content.get("format")) is None:
        raw_media = presentation.get("media") if isinstance(presentation.get("media"), dict) else {}
        raw_media_urls = item.get("media_urls") if isinstance(item.get("media_urls"), list) else []
        format_value, format_origin = resolve_content_format(
            source_type=source_type,
            catalog_type=source.get("catalog_type"),
            platform=source.get("platform"),
            url=links.get("canonical_url"),
            content_kind=content.get("content_kind"),
            metadata={
                "media_image_count": raw_media.get(
                    "total_image_count",
                    item.get("total_image_count", len(raw_media_urls)),
                ),
                "ai_content_format": item.get("ai_content_format"),
            },
        )
        content["format"] = format_value
        content["format_origin"] = format_origin
    elif content.get("format_origin") not in FORMAT_ORIGINS:
        content["format_origin"] = "fallback"

    configured_topics = _string_list(item.get("topics") or item.get("tags"))
    taxonomy = _section(presentation.get("taxonomy"))
    taxonomy.setdefault("channel", str(item.get("channel") or item.get("category") or source_type))
    taxonomy.setdefault("configured_topics", configured_topics)
    taxonomy.setdefault("inferred_topics", [])
    taxonomy.setdefault(
        "topics",
        _unique([*taxonomy["inferred_topics"], *taxonomy["configured_topics"]], limit=6),
    )
    taxonomy.setdefault("entities", _string_list(item.get("entities")))

    engagement = _section(presentation.get("engagement"))
    for key in ("native_score", "likes", "comments", "reposts", "shares", "upvote_ratio"):
        engagement.setdefault(key, None)

    analysis = _section(presentation.get("analysis"))
    default_status = "fallback"
    if item.get("scoring_disabled"):
        default_status = "disabled"
    elif item.get("analysis_mode") == "personal_only":
        default_status = "personal_only"
    elif item.get("summary_zh") or item.get("score") is not None:
        default_status = "ai"
    analysis.setdefault("status", default_status)
    if analysis.get("status") not in _ANALYSIS_STATUSES:
        analysis["status"] = default_status
    analysis.setdefault("score", _number(item.get("score")) or 0)
    analysis.setdefault("signal_strength", str(item.get("signal_strength") or "thin"))
    analysis.setdefault("signal_type", str(item.get("signal_type") or "other"))
    analysis.setdefault(
        "summary_zh",
        str(item.get("summary_zh") or content.get("excerpt") or content.get("title") or ""),
    )
    analysis.pop("reason", None)

    media = _section(presentation.get("media"))
    existing_images = media.get("images") if isinstance(media.get("images"), list) else []
    legacy_urls = [
        str(image.get("url") or "")
        for image in existing_images
        if isinstance(image, dict) and image.get("url")
    ]
    if not legacy_urls:
        legacy_urls = item.get("media_urls") if isinstance(item.get("media_urls"), list) else []
    projected_media = _presentation_media(
        title=str(content.get("title") or ""),
        media_urls=legacy_urls,
        total_image_count=media.get("total_image_count", item.get("total_image_count")),
    )
    if projected_media:
        projected_media["images"] = existing_images or projected_media["images"]
        projected_media["count"] = len(projected_media["images"])
        projected_media["total_image_count"] = max(
            projected_media["total_image_count"], projected_media["count"]
        )
        projected_media["truncated"] = (
            projected_media["total_image_count"] > projected_media["count"]
        )

    presentation.update(
        {
            "version": 1,
            "source": source,
            "author": author,
            "timing": timing,
            "links": links,
            "content": content,
            "taxonomy": taxonomy,
            "engagement": engagement,
            "analysis": analysis,
        }
    )
    if projected_media:
        presentation["media"] = projected_media
    return presentation


def _platform(item: ContentItem) -> str:
    platform = str(item.metadata.get("apify_platform") or "").strip().lower()
    if platform == "twitter":
        return "x"
    return platform or item.source_type.value


def _source_name(item: ContentItem) -> str:
    metadata = item.metadata
    for key in ("source_display_name", "feed_name"):
        if metadata.get(key):
            return str(metadata[key])
    if metadata.get("subreddit"):
        return f"r/{metadata['subreddit']}"
    if metadata.get("repo"):
        return str(metadata["repo"])
    if metadata.get("channel"):
        return f"@{metadata['channel']}"
    return item.author or item.source_type.value


def _author_kind(item: ContentItem) -> str:
    catalog_type = str(item.metadata.get("catalog_source_type") or "")
    if catalog_type == "telegram_channel" or item.source_type == SourceType.TELEGRAM:
        return "channel"
    if catalog_type in {"github_release", "github_user"}:
        return "account"
    if item.source_type in {SourceType.TWITTER, SourceType.INSTAGRAM, SourceType.FACEBOOK}:
        return "account"
    return "person" if item.author else "unknown"


def _content_kind(item: ContentItem) -> str:
    catalog_type = str(item.metadata.get("catalog_source_type") or "")
    if catalog_type == "github_release":
        return "release_notes"
    if catalog_type == "github_user":
        return "event_description"
    if item.source_type == SourceType.RSS:
        return "feed_summary"
    if item.source_type in {SourceType.REDDIT, SourceType.HACKERNEWS}:
        return "discussion"
    if item.source_type == SourceType.TELEGRAM:
        return "message"
    if item.source_type == SourceType.INSTAGRAM:
        return "caption"
    if item.source_type in {SourceType.TWITTER, SourceType.FACEBOOK}:
        return "post_body"
    if item.source_type == SourceType.GITHUB:
        return "release_notes" if item.metadata.get("tag") else "event_description"
    return "metadata_only"


def _title_origin(item: ContentItem) -> str:
    catalog_type = str(item.metadata.get("catalog_source_type") or "")
    if catalog_type in {"github_release", "github_user", "telegram_channel", "apify_social"}:
        return "generated"
    if item.source_type in {
        SourceType.GITHUB,
        SourceType.TELEGRAM,
        SourceType.TWITTER,
        SourceType.INSTAGRAM,
        SourceType.FACEBOOK,
    }:
        return "generated"
    return "native"


def _analysis_status(item: ContentItem) -> str:
    explicit = str(item.metadata.get("analysis_status") or "")
    if explicit in {"ai", "fallback", "personal_only", "disabled"}:
        return explicit
    if item.metadata.get("analysis_mode") == "personal_only":
        return "personal_only"
    if item.metadata.get("scoring_disabled"):
        return "disabled"
    if item.ai_summary_zh or item.ai_score is not None:
        return "ai"
    return "fallback"


def build_content_presentation(
    item: ContentItem,
    *,
    summary_max_chars: int = 200,
) -> dict[str, Any]:
    """Build the canonical presentation contract without model inference."""

    metadata = item.metadata
    excerpt, excerpt_truncated = _bounded_text(
        _clean_source_excerpt(item.content),
        SOURCE_EXCERPT_MAX_CHARS,
    )
    summary, _ = _bounded_text(item.ai_summary_zh or item.ai_summary or excerpt or item.title, summary_max_chars)
    action, _ = _bounded_text(item.ai_action_suggestion, ACTION_SUGGESTION_MAX_CHARS)
    configured_topics = _unique(
        metadata.get("configured_topics")
        or metadata.get("topics")
        or metadata.get("tags")
        or [],
        limit=6,
    )
    inferred_topics = _unique(
        metadata.get("inferred_topics") or item.ai_topics or item.ai_tags,
        limit=6,
    )
    topics = _unique([*inferred_topics, *configured_topics], limit=6)
    canonical_url = str(item.url)
    source_url = str(
        metadata.get("discussion_url")
        or metadata.get("msg_url")
        or canonical_url
    )
    catalog_type = str(metadata.get("catalog_source_type") or "").strip()
    content_kind = _content_kind(item)
    content_format, format_origin = resolve_content_format(
        source_type=item.source_type.value,
        catalog_type=catalog_type,
        platform=_platform(item),
        url=canonical_url,
        content_kind=content_kind,
        metadata=metadata,
    )
    media = _presentation_media(
        title=str(metadata.get("title_zh") or item.title),
        media_urls=metadata.get("media_urls"),
        total_image_count=metadata.get("media_image_count"),
    )

    source = {
        "id": str(metadata.get("source_id") or ""),
        "catalog_type": catalog_type or item.source_type.value,
        "platform": _platform(item),
        "name": _source_name(item),
    }
    if metadata.get("avatar_url"):
        source["avatar_url"] = str(metadata["avatar_url"])

    return {
        "version": PRESENTATION_VERSION,
        "source": source,
        "author": {"name": item.author or "", "kind": _author_kind(item)},
        "timing": {
            "published_at": _isoformat(item.published_at),
            "fetched_at": _isoformat(item.fetched_at),
        },
        "links": {
            "canonical_url": canonical_url,
            "source_url": source_url,
        },
        "content": {
            "title": str(metadata.get("title_zh") or item.title),
            "title_origin": _title_origin(item),
            "excerpt": excerpt,
            "content_kind": content_kind,
            "excerpt_truncated": excerpt_truncated,
            "format": content_format,
            "format_origin": format_origin,
        },
        "taxonomy": {
            "channel": str(item.ai_channel or metadata.get("channel") or metadata.get("category") or item.source_type.value),
            "configured_topics": configured_topics,
            "inferred_topics": inferred_topics,
            "topics": topics,
            "entities": _unique(item.ai_entities, limit=8),
        },
        "engagement": {
            "native_score": _first_number(metadata, "score"),
            "likes": _first_number(metadata, "favorite_count", "likes", "likes_count"),
            "comments": _first_number(metadata, "num_comments", "descendants", "comments", "comment_count", "reply_count"),
            "reposts": _first_number(metadata, "retweet_count", "reposts"),
            "shares": _first_number(metadata, "shares"),
            "upvote_ratio": _first_number(metadata, "upvote_ratio"),
        },
        "analysis": {
            "status": _analysis_status(item),
            "score": float(item.ai_score or 0),
            "signal_strength": item.ai_signal_strength or "thin",
            "signal_type": item.ai_signal_type or "other",
            "summary_zh": summary,
            "action_suggestion": action,
        },
        **({"media": media} if media else {}),
    }
