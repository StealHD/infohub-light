"""Disk-backed cache for content analysis results."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..models import ContentItem


ANALYSIS_PROMPT_VERSION = "content-analysis-v8-content-format"


def analysis_prompt_version(topic_library: list[str] | tuple[str, ...] | None = None) -> str:
    normalized = ["__builtin_defaults__"] if topic_library is None else sorted({str(topic).strip().casefold() for topic in topic_library if str(topic).strip()})
    digest = hashlib.sha256(json.dumps(normalized, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]
    return f"{ANALYSIS_PROMPT_VERSION}:{digest}"


def apply_analysis_result(item: ContentItem, result: dict[str, Any]) -> None:
    """Apply the safe, inference-only cache projection to one item."""
    item.ai_score = result.get("score")
    item.ai_reason = None
    item.ai_summary = result.get("summary") or result.get("summary_zh") or item.title
    item.ai_summary_zh = result.get("summary_zh") or result.get("summary")
    item.ai_channel = result.get("channel") or result.get("category") or ""
    item.ai_category = item.ai_channel
    item.ai_is_featured = bool(result.get("is_featured"))
    item.ai_action_suggestion = result.get("action_suggestion") or ""
    topics = result.get("topics") or result.get("tags") or []
    item.ai_topics = [str(tag) for tag in topics] if isinstance(topics, list) else []
    item.ai_tags = list(item.ai_topics)
    item.ai_signal_strength = result.get("signal_strength") or ""
    item.ai_signal_type = result.get("signal_type") or ""
    entities = result.get("entities") or []
    item.ai_entities = [str(entity) for entity in entities] if isinstance(entities, list) else []
    item.metadata["analysis_status"] = "ai"
    content_format = str(result.get("content_format") or "").strip().lower()
    if content_format in {
        "article", "video", "image", "gallery", "audio",
        "social_post", "discussion", "release", "other",
    }:
        item.metadata["ai_content_format"] = content_format
    else:
        item.metadata.pop("ai_content_format", None)
    inferred_topics = result.get("inferred_topics") or []
    item.metadata["inferred_topics"] = (
        [str(tag) for tag in inferred_topics]
        if isinstance(inferred_topics, list)
        else []
    )


def safe_analysis_result(item: ContentItem) -> dict[str, Any]:
    """Return cached inference fields without source content or legacy reason."""
    return {
        "score": item.ai_score,
        "channel": item.ai_channel or item.ai_category or "",
        "topics": list(item.ai_topics or item.ai_tags or []),
        "inferred_topics": list(item.metadata.get("inferred_topics") or []),
        "tags": list(item.ai_topics or item.ai_tags or []),
        "category": item.ai_channel or item.ai_category or "",
        "signal_strength": item.ai_signal_strength or "",
        "signal_type": item.ai_signal_type or "",
        "entities": list(item.ai_entities or []),
        "is_featured": bool(item.ai_is_featured),
        "summary": item.ai_summary or "",
        "summary_zh": item.ai_summary_zh or "",
        "content_format": str(item.metadata.get("ai_content_format") or ""),
    }


class AnalysisCache:
    """Append-friendly JSONL cache keyed by item identity and content hash."""

    def __init__(self, path: Path):
        self.path = path
        self._entries: dict[str, dict[str, Any]] | None = None

    def _load(self) -> dict[str, dict[str, Any]]:
        if self._entries is not None:
            return self._entries

        entries: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = str(row.get("key") or "")
                if key:
                    entries[key] = row
        self._entries = entries
        return entries

    @staticmethod
    def content_hash(item: ContentItem) -> str:
        payload = {
            "id": item.id,
            "url": str(item.url),
            "title": item.title,
            "content": item.content or "",
            "author": item.author or "",
            "published_at": item.published_at.isoformat(),
            "source_name": item.metadata.get("source_display_name") or "",
            "catalog_source_type": item.metadata.get("catalog_source_type") or "",
            "platform": item.metadata.get("apify_platform") or item.source_type.value,
            "channel": item.metadata.get("channel") or item.metadata.get("category") or "",
            "topics": item.metadata.get("topics") or item.metadata.get("tags") or [],
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def key(
        self,
        item: ContentItem,
        *,
        model: str,
        prompt_version: str = ANALYSIS_PROMPT_VERSION,
    ) -> str:
        raw = f"{model}\n{prompt_version}\n{self.content_hash(item)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def apply(
        self,
        item: ContentItem,
        *,
        model: str,
        prompt_version: str = ANALYSIS_PROMPT_VERSION,
    ) -> bool:
        row = self._load().get(self.key(item, model=model, prompt_version=prompt_version))
        if not row:
            return False
        result = row.get("result")
        if not isinstance(result, dict):
            return False
        apply_analysis_result(item, result)
        item.metadata["analysis_cache_hit"] = True
        return True

    def store(
        self,
        item: ContentItem,
        *,
        model: str,
        prompt_version: str = ANALYSIS_PROMPT_VERSION,
    ) -> None:
        if item.ai_score is None:
            return
        row = {
            "key": self.key(item, model=model, prompt_version=prompt_version),
            "item_id": item.id,
            "content_hash": self.content_hash(item),
            "model": model,
            "prompt_version": prompt_version,
            "result": safe_analysis_result(item),
        }
        entries = self._load()
        entries[row["key"]] = row
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
