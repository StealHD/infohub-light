"""Content analysis using AI."""

import asyncio
import hashlib
import json
import logging
from typing import List, Optional
import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, MofNCompleteColumn

from .client import AIClient
from .analysis_cache import ANALYSIS_PROMPT_VERSION, AnalysisCache
from .prompts import CONTENT_ANALYSIS_USER, content_analysis_system
from .tokens import token_stage
from .utils import parse_json_response
from .summary_policy import normalize_item_summary, preserve_source_summary
from ..models import ContentItem
from ..services.content_presentation import build_content_presentation, normalize_content_format
from ..tag_policy import (
    normalize_channel,
    normalize_entities,
    normalize_signal_strength,
    normalize_signal_type,
    normalize_tags,
)

DEFAULT_THROTTLE_SEC = 0.0
DEFAULT_FEATURED_THRESHOLD = 7.5
logger = logging.getLogger(__name__)


def _retryable_ai_exception(exc: BaseException) -> bool:
    explicit = getattr(exc, "retryable", None)
    if explicit is not None:
        return bool(explicit)
    if isinstance(exc, (ConnectionError, TimeoutError, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False


class ContentAnalyzer:
    """Analyzes content items using AI to determine importance."""

    def __init__(self, ai_client: AIClient, cache: AnalysisCache | None = None, *, topic_library: list[str] | None = None):
        self.client = ai_client
        self.cache = cache
        self.topic_library = None if topic_library is None else list(topic_library)
        self.usage = {
            "item_count": 0,
            "cache_hits": 0,
            "ai_calls": 0,
            "provider_attempts": 0,
            "fallbacks": 0,
            "skipped": 0,
        }

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

    def _analysis_provider(self) -> str:
        config = getattr(self.client, "config", None)
        provider = getattr(config, "provider", "unknown-provider")
        return str(getattr(provider, "value", provider) or "unknown-provider")

    @staticmethod
    def _analysis_source_id(item: ContentItem) -> str | None:
        source_id = item.metadata.get("source_id")
        if source_id:
            return str(source_id)
        source_ids = item.metadata.get("source_ids")
        if isinstance(source_ids, list):
            return next((str(value) for value in source_ids if value), None)
        return None

    def _analysis_content_chars(self) -> int:
        config = getattr(self.client, "config", None)
        return max(100, int(getattr(config, "analysis_content_chars", 1000)))

    def _analysis_comments_chars(self) -> int:
        config = getattr(self.client, "config", None)
        return max(0, int(getattr(config, "analysis_comments_chars", 1500)))

    def _summary_max_chars(self) -> int:
        config = getattr(self.client, "config", None)
        return max(100, min(500, int(getattr(config, "summary_max_chars", 200))))

    def _analysis_max_output_tokens(self) -> int:
        config = getattr(self.client, "config", None)
        return max(256, min(2048, int(getattr(config, "analysis_max_output_tokens", 800))))

    def _prompt_version(self, item: ContentItem) -> str:
        system_prompt, user_prompt, _source_tags, _source_channel = (
            self._render_analysis_prompt(item)
        )
        payload = {
            "cache_version": f"{ANALYSIS_PROMPT_VERSION}:rendered-v1",
            "system": system_prompt,
            "user": user_prompt,
            "model": self._analysis_model(),
            "analysis_mode": str(item.metadata.get("analysis_mode") or "full"),
            "analysis_content_chars": self._analysis_content_chars(),
            "analysis_comments_chars": self._analysis_comments_chars(),
            "summary_max_chars": self._summary_max_chars(),
            "analysis_max_output_tokens": self._analysis_max_output_tokens(),
        }
        digest = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return f"{ANALYSIS_PROMPT_VERSION}:rendered:{digest}"

    async def analyze_batch(self, items: List[ContentItem]) -> List[ContentItem]:
        self.usage = {
            "item_count": len(items),
            "cache_hits": 0,
            "ai_calls": 0,
            "provider_attempts": 0,
            "fallbacks": 0,
            "skipped": 0,
        }
        throttle_sec = self._get_throttle_sec()
        concurrency = self._get_concurrency()
        semaphore = asyncio.Semaphore(concurrency)

        async def _process(item: ContentItem, index: int, progress_task) -> ContentItem:
            async with semaphore:
                try:
                    prompt_version = self._prompt_version(item)
                    cache_hit = bool(
                        self.cache
                        and self.cache.apply(
                            item,
                            model=self._analysis_model(),
                            prompt_version=prompt_version,
                        )
                    )
                    if cache_hit:
                        self.usage["cache_hits"] += 1
                        item.metadata["analysis_cache_hit"] = True
                    else:
                        before_ai_item_for_source = getattr(
                            self.cache,
                            "before_ai_item_for_source",
                            None,
                        )
                        before_ai_item = getattr(
                            self.cache,
                            "before_ai_item",
                            None,
                        )
                        if callable(before_ai_item_for_source):
                            before_ai_item_for_source(
                                provider=self._analysis_provider(),
                                source_id=self._analysis_source_id(item),
                            )
                        elif callable(before_ai_item):
                            before_ai_item(provider=self._analysis_provider())
                        self.usage["ai_calls"] += 1
                        analysis_succeeded = await self._analyze_item(item)
                        if analysis_succeeded is False:
                            self.usage["fallbacks"] += 1
                        if self.cache and analysis_succeeded is not False:
                            self.cache.store(
                                item,
                                model=self._analysis_model(),
                                prompt_version=prompt_version,
                            )
                except Exception as exc:
                    logger.exception(
                        "content analysis failed; fallback applied",
                        extra={
                            "stage": "analysis",
                            "error_code": type(exc).__name__,
                        },
                    )
                    item.ai_score = 0.0
                    item.ai_reason = None
                    item.ai_summary = item.title
                    item.metadata["analysis_status"] = "fallback"
                    self.usage["fallbacks"] += 1
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

    def _render_analysis_prompt(
        self,
        item: ContentItem,
    ) -> tuple[str, str, list[str], str]:
        """Render the exact bounded prompt used for cache fingerprinting."""

        preserve_source_summary(item)
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

        discussion_parts = []
        if item.content and "--- Top Comments ---" in item.content:
            comments_part = item.content.split("--- Top Comments ---", 1)[1]
            if comments_limit:
                discussion_parts.append(f"Community Comments:\n{comments_part[:comments_limit]}")

        meta = item.metadata
        presentation = build_content_presentation(
            item,
            summary_max_chars=self._summary_max_chars(),
        )
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

        user_prompt = CONTENT_ANALYSIS_USER.format(
            title=item.title,
            source_name=presentation["source"]["name"],
            catalog_source_type=presentation["source"]["catalog_type"],
            platform=presentation["source"]["platform"],
            content_kind=presentation["content"]["content_kind"],
            author=item.author or "Unknown",
            published_at=presentation["timing"]["published_at"],
            url=str(item.url),
            source_channel=source_channel,
            source_tags=", ".join(str(tag) for tag in source_tags) or "None",
            content_section=content_section,
            discussion_section=discussion_section,
            summary_limit=self._summary_max_chars(),
        )
        return (
            content_analysis_system(self.topic_library),
            user_prompt,
            source_tags,
            source_channel,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=2, max=10),
        retry=retry_if_exception(_retryable_ai_exception),
        reraise=True,
    )
    async def _analyze_item(self, item: ContentItem) -> bool:
        """Analyze a single content item and meter every provider attempt."""

        system_prompt, user_prompt, source_tags, source_channel = (
            self._render_analysis_prompt(item)
        )
        before_ai_network_attempt = getattr(
            self.cache,
            "before_ai_network_attempt",
            None,
        )
        before_ai_attempt = getattr(self.cache, "before_ai_attempt", None)
        if callable(before_ai_network_attempt):
            before_ai_network_attempt(
                provider=self._analysis_provider(),
                source_id=self._analysis_source_id(item),
            )
        elif callable(before_ai_attempt):
            before_ai_attempt(provider=self._analysis_provider())
        self.usage["provider_attempts"] += 1

        # Get AI completion
        with token_stage("analysis", item_id=item.id):
            response = await self.client.complete(
                system=system_prompt,
                user=user_prompt,
                max_tokens=self._analysis_max_output_tokens(),
            )

        # Parse JSON response with robust fallback
        result = self._parse_json_response(response)
        if result is None:
            logger.warning(
                "content analysis response was invalid; fallback applied",
                extra={
                    "stage": "analysis",
                    "error_code": "invalid_ai_response",
                },
            )
            item.ai_score = 0.0
            item.ai_reason = None
            item.ai_summary = item.title
            item.ai_tags = []
            item.metadata["analysis_status"] = "fallback"
            return False

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
        item.ai_reason = None
        item.ai_summary_zh = result.get("summary_zh") or result.get("summary")
        item.ai_summary = result.get("summary") or item.ai_summary_zh or item.title
        normalized_topics = normalize_tags(
            [*topics, *source_tags],
            fallback=channel,
            max_tags=6,
            allow_custom=True,
        )
        item.metadata["inferred_topics"] = normalize_tags(
            topics,
            max_tags=6,
            allow_custom=True,
        )
        item.metadata["configured_topics"] = normalize_tags(
            source_tags,
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
        item.ai_action_suggestion = None
        content_format = normalize_content_format(result.get("content_format"))
        if content_format:
            item.metadata["ai_content_format"] = content_format
        else:
            item.metadata.pop("ai_content_format", None)
        normalize_item_summary(item, self._summary_max_chars())
        item.metadata["analysis_status"] = "ai"
        return True
