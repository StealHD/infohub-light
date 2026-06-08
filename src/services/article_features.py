"""Low-cost feature extraction for article relationship analysis."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from ..models import ContentItem
from ..storage.article_store import content_hash


ENTITY_ALIASES: dict[str, tuple[str, ...]] = {
    "OpenAI": ("openai", "chatgpt", "gpt-4", "gpt-5", "codex"),
    "Anthropic": ("anthropic", "claude"),
    "Google DeepMind": ("deepmind", "google ai", "gemini"),
    "Meta AI": ("meta ai", "llama"),
    "Microsoft": ("microsoft", "azure", "github copilot"),
    "NVIDIA": ("nvidia", "cuda", "nemotron"),
    "MCP": ("mcp", "model context protocol"),
    "RAG": ("rag", "retrieval augmented"),
    "Codex": ("codex",),
    "Claude Code": ("claude code",),
    "Cursor": ("cursor",),
    "Devin": ("devin",),
    "Hugging Face": ("hugging face", "huggingface"),
    "LangChain": ("langchain",),
    "LlamaIndex": ("llamaindex", "llama index"),
}

STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "into",
    "about",
    "using",
    "update",
    "release",
    "new",
    "发布",
    "更新",
    "一个",
    "可以",
    "通过",
}

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{2,}|[\u4e00-\u9fff]{2,}")
CAPITALIZED_RE = re.compile(r"\b[A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*){0,3}\b")


def _unique(values: list[str], *, limit: int = 24) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _article_value(article: ContentItem | dict[str, Any], name: str, default: Any = "") -> Any:
    if isinstance(article, dict):
        return article.get(name, default)
    return getattr(article, name, default)


def _article_tags(article: ContentItem | dict[str, Any]) -> list[str]:
    if isinstance(article, dict):
        values = [*(article.get("tags") or [])]
        category = article.get("category")
    else:
        metadata_tags = article.metadata.get("tags") if isinstance(article.metadata, dict) else []
        values = [*(metadata_tags or []), *article.ai_tags]
        category = article.ai_category
    if category:
        values.append(str(category))
    return _unique([str(value) for value in values], limit=12)


def _article_text(article: ContentItem | dict[str, Any]) -> str:
    parts: list[str] = []
    for name in ("title", "summary_zh", "cleaned_text", "content"):
        value = _article_value(article, name, "")
        if value:
            parts.append(str(value))
    if not parts and not isinstance(article, dict):
        parts.extend(
            str(value)
            for value in (article.ai_summary_zh, article.ai_summary, article.content)
            if value
        )
    return "\n".join(parts)


def _published_at(article: ContentItem | dict[str, Any]) -> str:
    value = _article_value(article, "published_at", "")
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def extract_entities(text: str) -> list[str]:
    lower = text.lower()
    entities: list[str] = []
    for canonical, aliases in ENTITY_ALIASES.items():
        if any(alias in lower for alias in aliases):
            entities.append(canonical)
    entities.extend(
        match.group(0)
        for match in CAPITALIZED_RE.finditer(text)
        if match.group(0).lower() not in STOPWORDS
    )
    return _unique(entities, limit=20)


def extract_keywords(text: str) -> list[str]:
    keywords: list[str] = []
    for match in TOKEN_RE.finditer(text.lower()):
        token = match.group(0).strip("-_")
        if token and token not in STOPWORDS:
            keywords.append(token)
    return _unique(keywords, limit=30)


def extract_article_features(article: ContentItem | dict[str, Any]) -> dict[str, Any]:
    """Extract deterministic topics/entities/keywords without an AI call."""
    tags = _article_tags(article)
    text = _article_text(article)
    feature_text = "\n".join([*tags, text])
    return {
        "topics": tags,
        "entities": extract_entities(feature_text),
        "keywords": extract_keywords(feature_text),
        "event_time": _published_at(article)[:10],
        "viewpoint": "",
        "feature_text_hash": content_hash(feature_text),
    }
