"""Deterministic per-item summary fallback and output length policy."""

from __future__ import annotations

import html
import re

from ..models import ContentItem


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_SENTENCE_ENDINGS = frozenset("。！？.!?")


def clean_summary_text(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = _HTML_TAG_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def truncate_summary(value: object, limit: int) -> str:
    text = clean_summary_text(value)
    limit = max(1, int(limit))
    if len(text) <= limit:
        return text
    prefix = text[:limit]
    boundary = max((index for index, char in enumerate(prefix) if char in _SENTENCE_ENDINGS), default=-1)
    if boundary + 1 >= max(1, limit // 2):
        return prefix[: boundary + 1].rstrip()
    if limit == 1:
        return "…"
    return prefix[: limit - 1].rstrip() + "…"


def preserve_source_summary(item: ContentItem) -> None:
    if item.metadata.get("source_summary"):
        return
    candidate = item.ai_summary_zh or item.ai_summary
    if candidate:
        item.metadata["source_summary"] = clean_summary_text(candidate)


def normalize_item_summary(item: ContentItem, limit: int) -> str:
    candidates = (
        item.ai_summary_zh,
        item.metadata.get("source_summary"),
        item.ai_summary,
        item.content,
        item.title,
    )
    selected = next((clean_summary_text(candidate) for candidate in candidates if clean_summary_text(candidate)), "")
    summary = truncate_summary(selected, limit)
    item.ai_summary_zh = summary
    item.ai_summary = summary
    return summary
