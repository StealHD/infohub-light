"""Optional premium-article full text fetching and cleaning."""

from __future__ import annotations

import asyncio
import html
import re
from typing import Any

import httpx

from ..storage.article_store import ArticleStore


BLOCK_RE = re.compile(
    r"<\s*(script|style|nav|footer|header|aside)\b[^>]*>.*?<\s*/\s*\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def clean_html_to_text(markup: str, *, max_chars: int = 12000) -> str:
    """Strip noisy HTML chrome and return compact plain text."""
    without_blocks = BLOCK_RE.sub(" ", markup or "")
    with_breaks = re.sub(
        r"<\s*/\s*(p|div|section|article|h[1-6]|li|br)\s*>",
        " ",
        without_blocks,
        flags=re.IGNORECASE,
    )
    text = TAG_RE.sub(" ", with_breaks)
    text = html.unescape(text)
    text = SPACE_RE.sub(" ", text).strip()
    if max_chars <= 0:
        return text
    return text[:max_chars]


class FullTextFetcher:
    """Bounded async fetcher for high-score article bodies."""

    def __init__(
        self,
        store: ArticleStore,
        *,
        score_threshold: float = 8.5,
        max_articles: int = 10,
        max_chars: int = 12000,
        concurrency: int = 2,
        timeout_seconds: float = 12.0,
    ) -> None:
        self.store = store
        self.score_threshold = score_threshold
        self.max_articles = max_articles
        self.max_chars = max_chars
        self.concurrency = max(1, concurrency)
        self.timeout_seconds = timeout_seconds

    async def fetch_missing(self) -> int:
        """Fetch and store missing premium article text."""
        if self.max_articles <= 0:
            return 0
        candidates = self.store.load_premium_candidates(
            min_score=self.score_threshold,
            limit=self.max_articles,
        )
        if not candidates:
            return 0

        semaphore = asyncio.Semaphore(self.concurrency)
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "Horizon-Inteliscope/1.0"},
        ) as client:
            results = await asyncio.gather(
                *[
                    self._fetch_one(client, semaphore, candidate)
                    for candidate in candidates
                ],
                return_exceptions=True,
            )

        fetched = 0
        for result in results:
            if result is True:
                fetched += 1
        return fetched

    async def _fetch_one(
        self,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        article: dict[str, Any],
    ) -> bool:
        async with semaphore:
            article_id = str(article["id"])
            normalized_url = str(article.get("normalized_url") or "")
            try:
                response = await client.get(str(article["url"]))
                response.raise_for_status()
                cleaned = clean_html_to_text(
                    response.text,
                    max_chars=self.max_chars,
                )
                if not cleaned:
                    raise ValueError("empty cleaned article body")
                self.store.upsert_premium_article(
                    article_id=article_id,
                    normalized_url=normalized_url,
                    cleaned_text=cleaned,
                    fetch_status="ok",
                )
                return True
            except Exception as exc:  # noqa: BLE001 - failure is intentionally non-fatal
                self.store.upsert_premium_article(
                    article_id=article_id,
                    normalized_url=normalized_url,
                    cleaned_text="",
                    fetch_status="failed",
                    fetch_error=str(exc)[:500],
                )
                return False
