"""Content analysis using AI."""

import asyncio
from typing import List, Optional
from tenacity import retry, stop_after_attempt, wait_exponential
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, MofNCompleteColumn

from .client import AIClient
from .analysis_cache import ANALYSIS_PROMPT_VERSION, AnalysisCache
from .prompts import CONTENT_ANALYSIS_SYSTEM, CONTENT_ANALYSIS_USER
from .tokens import token_stage
from .utils import parse_json_response
from ..models import ContentItem
from ..tag_policy import (
    normalize_channel,
    normalize_entities,
    normalize_signal_strength,
    normalize_signal_type,
    normalize_tags,
)

DEFAULT_THROTTLE_SEC = 0.0
DEFAULT_FEATURED_THRESHOLD = 7.5


class ContentAnalyzer:
    """Analyzes content items using AI to determine importance."""

    def __init__(self, ai_client: AIClient, cache: AnalysisCache | None = None):
        self.client = ai_client
        self.cache = cache

    @staticmethod
    def _parse_json_response(response: str) -> Optional[dict]:
        """Try multiple strategies to extract a JSON object from an AI response.

        Returns the parsed dict, or None if all strategies fail.
        """
        return parse_json_response(response)

    def _get_throttle_sec(self) -> float:
        """Return the configured inter-item throttle, clamped to zero or above."""
        config = getattr(self.client, "config", None)
        throttle_sec = getattr(config, "throttle_sec", DEFAULT_THROTTLE_SEC)
        return max(throttle_sec, 0.0)

    def _get_concurrency(self) -> int:
        """Return the configured analysis concurrency, clamped to 1 or above."""
        config = getattr(self.client, "config", None)
        concurrency = getattr(config, "analysis_concurrency", 1)
        return max(concurrency, 1)

    def _analysis_model(self) -> str:
        config = getattr(self.client, "config", None)
        return str(getattr(config, "model", "unknown-model") or "unknown-model")

    def _analysis_content_chars(self) -> int:
        config = getattr(self.client, "config", None)
        return max(100, int(getattr(config, "analysis_content_chars", 1000)))

    def _analysis_comments_chars(self) -> int:
        config = getattr(self.client, "config", None)
        return max(0, int(getattr(config, "analysis_comments_chars", 1500)))

    async def analyze_batch(self, items: List[ContentItem]) -> List[ContentItem]:
        throttle_sec = self._get_throttle_sec()
        concurrency = self._get_concurrency()
        semaphore = asyncio.Semaphore(concurrency)

        async def _process(item: ContentItem, index: int, progress_task) -> ContentItem:
            async with semaphore:
                try:
                    if not (
                        self.cache
                        and self.cache.apply(
                            item,
                            model=self._analysis_model(),
                            prompt_version=ANALYSIS_PROMPT_VERSION,
                        )
                    ):
                        await self._analyze_item(item)
                        if self.cache:
                            self.cache.store(
                                item,
                                model=self._analysis_model(),
                                prompt_version=ANALYSIS_PROMPT_VERSION,
                            )
                except Exception as e:
                    print(f"Error analyzing item {item.id}: {e}")
                    item.ai_score = 0.0
                    item.ai_reason = "Analysis failed"
                    item.ai_summary = item.title
                if throttle_sec > 0 and index < len(items) - 1:
                    await asyncio.sleep(throttle_sec)
            progress.advance(progress_task)
            return item

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            transient=True,
        ) as progress:
            task = progress.add_task("Analyzing", total=len(items))
            coros = [
                _process(item, i, task) for i, item in enumerate(items)
            ]
            analyzed_items = await asyncio.gather(*coros)

        return analyzed_items

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=2, max=10)
    )
    async def _analyze_item(self, item: ContentItem) -> None:
        """Analyze a single content item.

        Args:
            item: Content item to analyze (modified in-place)
        """
        # Prepare content section
        content_section = ""
        content_limit = self._analysis_content_chars()
        comments_limit = self._analysis_comments_chars()
        if item.content:
            # Split off comments if present
            content_text = item.content
            if "--- Top Comments ---" in content_text:
                main, comments_part = content_text.split("--- Top Comments ---", 1)
                content_section = f"Content: {main.strip()[:content_limit]}"
            else:
                content_section = f"Content: {content_text[:content_limit]}"

        # Prepare discussion section (comments, engagement)
        discussion_parts = []
        if item.content and "--- Top Comments ---" in item.content:
            comments_part = item.content.split("--- Top Comments ---", 1)[1]
            if comments_limit:
                discussion_parts.append(f"Community Comments:\n{comments_part[:comments_limit]}")

        meta = item.metadata
        engagement_items = []
        if meta.get("score"):
            engagement_items.append(f"score: {meta['score']}")
        if meta.get("descendants"):
            engagement_items.append(f"{meta['descendants']} comments")
        if meta.get("favorite_count"):
            engagement_items.append(f"{meta['favorite_count']} likes")
        if meta.get("retweet_count"):
            engagement_items.append(f"{meta['retweet_count']} retweets")
        if meta.get("reply_count"):
            engagement_items.append(f"{meta['reply_count']} replies")
        if meta.get("views"):
            engagement_items.append(f"{meta['views']} views")
        if meta.get("bookmarks"):
            engagement_items.append(f"{meta['bookmarks']} bookmarks")
        if meta.get("upvote_ratio"):
            engagement_items.append(f"upvote ratio: {meta['upvote_ratio']:.0%}")
        if engagement_items:
            discussion_parts.append(f"Engagement: {', '.join(engagement_items)}")
        if meta.get("discussion_url"):
            discussion_parts.append(f"Discussion: {meta['discussion_url']}")
        if meta.get("community_note"):
            discussion_parts.append(f"Community Note: {meta['community_note']}")

        discussion_section = "\n".join(discussion_parts) if discussion_parts else ""
        source_tags = meta.get("topics") or meta.get("tags") or []
        if not isinstance(source_tags, list):
            source_tags = []
        source_channel = normalize_channel(
            meta.get("channel") or meta.get("category"),
            fallback=item.source_type.value,
        )

        # Generate user prompt
        user_prompt = CONTENT_ANALYSIS_USER.format(
            title=item.title,
            source=f"{item.source_type.value}",
            author=item.author or "Unknown",
            url=str(item.url),
            source_channel=source_channel,
            source_tags=", ".join(str(tag) for tag in source_tags) or "None",
            content_section=content_section,
            discussion_section=discussion_section
        )

        # Get AI completion
        with token_stage("analysis", item_id=item.id):
            response = await self.client.complete(
                system=CONTENT_ANALYSIS_SYSTEM,
                user=user_prompt,
            )

        # Parse JSON response with robust fallback
        result = self._parse_json_response(response)
        if result is None:
            print(f"Warning: could not parse analysis response for {item.id}, using defaults")
            item.ai_score = 0.0
            item.ai_reason = "Analysis response parse failed"
            item.ai_summary = item.title
            item.ai_tags = []
            return

        # Update item with analysis results. Keep backward compatibility with
        # older prompts that returned "summary" instead of "summary_zh".
        score = max(0.0, min(10.0, float(result.get("score", 0))))
        topics = result.get("topics")
        if not isinstance(topics, list):
            topics = result.get("tags", [])
        if not isinstance(topics, list):
            topics = []
        entities = result.get("entities", [])
        if not isinstance(entities, list):
            entities = []

        item.ai_score = score
        channel = normalize_channel(
            result.get("channel") or result.get("category"),
            fallback=source_channel,
        )
        item.ai_reason = result.get("reason", "")
        item.ai_summary_zh = result.get("summary_zh") or result.get("summary")
        item.ai_summary = result.get("summary") or item.ai_summary_zh or item.title
        normalized_topics = normalize_tags(
            [*topics, *source_tags],
            fallback=channel,
            max_tags=6,
            allow_custom=True,
        )
        item.ai_channel = channel
        item.ai_topics = normalized_topics
        item.ai_category = channel
        item.ai_tags = normalized_topics
        item.ai_signal_strength = normalize_signal_strength(
            result.get("signal_strength"),
            score=score,
        )
        item.ai_signal_type = normalize_signal_type(result.get("signal_type"))
        item.ai_entities = normalize_entities(entities)
        item.ai_is_featured = bool(
            result.get("is_featured", score >= DEFAULT_FEATURED_THRESHOLD)
        )
        item.ai_action_suggestion = result.get("action_suggestion", "")
