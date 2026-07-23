"""Main orchestrator coordinating the entire workflow."""

import asyncio
from collections import defaultdict
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List, Dict
from uuid import uuid4
import httpx
from rich.console import Console

from .models import Config, ContentItem
from .storage.manager import StorageManager
from .services.email import EmailManager
from .services.webhook import WebhookNotifier
from .services.daily_push import select_daily_push_items
from .services.article_graph import build_article_graph_snapshot, write_article_graph_snapshot
from .services.fulltext import FullTextFetcher
from .services.feed_run import (
    AcquisitionUsage,
    AnalysisUsage,
    FeedRunResult,
    RunIssue,
    SourceOutcome,
)
from .services.response_schema import extract_response_schema
from .services.legacy_publisher import LegacyPublisher
from .services.canonical_content import canonical_url_key
from .storage.article_store import ArticleStore
from .scrapers.github import GitHubScraper
from .scrapers.hackernews import HackerNewsScraper
from .scrapers.rss import RSSScraper
from .scrapers.reddit import RedditScraper
from .scrapers.telegram import TelegramScraper
from .scrapers.twitter import TwitterScraper
from .scrapers.apify_social import ApifySocialScraper
from .scrapers.openbb import OpenBBScraper
from .scrapers.ossinsight import OSSInsightScraper
from .ai.client import create_ai_client
from .ai.analysis_cache import AnalysisCache
from .ai.analyzer import ContentAnalyzer
from .ai.summarizer import DailySummarizer
from .ai.enricher import ContentEnricher
from .ai.tokens import get_usage_snapshot, token_stage
from .ai.summary_policy import normalize_item_summary, preserve_source_summary
from .tag_policy import (
    normalize_channel,
    normalize_signal_strength,
    normalize_signal_type,
    normalize_tags,
)
from .source_selection import SourceRef
from .ui.site import build_site_payload, load_history_item_ids, write_static_site


_SERVICE_EXECUTION: ContextVar[bool] = ContextVar("horizon_service_execution", default=False)


def _is_retryable_source_exception(exc: BaseException) -> bool:
    explicit = getattr(exc, "retryable", None)
    if explicit is not None:
        return bool(explicit)
    if isinstance(exc, (ConnectionError, TimeoutError, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False


class HorizonOrchestrator:
    """Orchestrates the complete workflow for content aggregation and analysis."""

    def __init__(
        self,
        config: Config,
        storage: StorageManager,
        *,
        analysis_cache: Any | None = None,
    ):
        """Initialize orchestrator.

        Args:
            config: Application configuration
            storage: Storage manager
        """
        self.config = config
        self.storage = storage
        self._service_analysis_cache = analysis_cache
        self._service_attempt_meter: Any | None = None
        self._service_acquisition_coordinator: Any | None = None
        self._service_apify_coordinator: Any | None = None
        self._last_analysis_usage = AnalysisUsage()
        self.console = Console()
        self.email_manager = EmailManager(config.email, console=self.console) if config.email else None
        self.webhook_notifier = (
            WebhookNotifier(config.webhook, console=self.console)
            if config.webhook and config.webhook.enabled
            else None
        )

    def set_service_analysis_cache(self, cache: Any | None) -> None:
        """Attach a user-scoped cache without changing legacy constructor callers."""
        self._service_analysis_cache = cache

    def set_service_attempt_meter(self, meter: Any | None) -> None:
        """Attach a service-owned upstream attempt admission hook."""
        self._service_attempt_meter = meter

    def set_service_acquisition_coordinator(self, coordinator: Any | None) -> None:
        """Attach the optional shared source-content coordinator."""
        self._service_acquisition_coordinator = coordinator

    def set_service_apify_coordinator(self, coordinator: Any | None) -> None:
        """Attach the workspace Key-pool coordinator for Service Apify Runs."""
        self._service_apify_coordinator = coordinator

    def _service_acquisition_usage(self) -> AcquisitionUsage:
        metrics = getattr(self._service_acquisition_coordinator, "metrics", None)
        values = metrics.as_dict() if hasattr(metrics, "as_dict") else {}
        return AcquisitionUsage(
            cache_hits=int(values.get("cache_hits", 0)),
            cache_misses=int(values.get("cache_misses", 0)),
            upstream_attempts=int(values.get("upstream_attempts", 0)),
            waits=int(values.get("waits", 0)),
        )

    async def execute(
        self,
        force_hours: int | None = None,
        *,
        enrich: bool = False,
        legacy_sources: bool = False,
        exclude_item_ids: set[str] | None = None,
    ) -> FeedRunResult:
        """Run the side-effect-free service pipeline without the global disk cache."""
        token = _SERVICE_EXECUTION.set(not legacy_sources)
        try:
            return await self._execute_structured(
                force_hours=force_hours,
                enrich=enrich,
                legacy_sources=legacy_sources,
                exclude_item_ids=exclude_item_ids,
            )
        finally:
            _SERVICE_EXECUTION.reset(token)

    async def _execute_structured(
        self,
        force_hours: int | None = None,
        *,
        enrich: bool = False,
        legacy_sources: bool = False,
        exclude_item_ids: set[str] | None = None,
    ) -> FeedRunResult:
        """Fetch content and return a fresh structured result for services."""
        started_at = datetime.now(timezone.utc)
        run_id = f"run_{uuid4().hex}"
        source_outcomes: tuple[SourceOutcome, ...] = ()
        fetch_issues: tuple[RunIssue, ...] = ()
        has_failed_sources = False
        analysis_usage = AnalysisUsage()
        try:
            since = self._determine_time_window(force_hours)
            if legacy_sources:
                raw_items = await self.fetch_all_sources(since)
                source_outcomes = (
                    SourceOutcome(
                        source_id="",
                        subscription_id=None,
                        source_key="legacy:all",
                        analysis_mode="full",
                        status="succeeded",
                        fetched_count=len(raw_items),
                    ),
                )
            else:
                raw_items, source_outcomes = await self.fetch_service_sources(since)
            fetch_issues = tuple(
                outcome.issue
                for outcome in source_outcomes
                if outcome.issue is not None
            )
            has_failed_sources = any(
                outcome.status == "failed" for outcome in source_outcomes
            )
            if source_outcomes and all(
                outcome.status == "failed" for outcome in source_outcomes
            ):
                return FeedRunResult(
                    run_id=run_id,
                    status="failed",
                    started_at=started_at.isoformat(),
                    finished_at=datetime.now(timezone.utc).isoformat(),
                    source_outcomes=source_outcomes,
                    issues=fetch_issues,
                    acquisition_usage=self._service_acquisition_usage(),
                )
            merged_items = self.merge_cross_source_duplicates(raw_items)
            for item in merged_items:
                preserve_source_summary(item)
            if exclude_item_ids:
                merged_items = [
                    item for item in merged_items if item.id not in exclude_item_ids
                ]
            if not merged_items:
                return FeedRunResult(
                    run_id=run_id,
                    status=("partial" if has_failed_sources else "succeeded"),
                    started_at=started_at.isoformat(),
                    finished_at=datetime.now(timezone.utc).isoformat(),
                    source_outcomes=source_outcomes,
                    issues=fetch_issues,
                    acquisition_usage=self._service_acquisition_usage(),
                )

            if self._ai_enabled():
                analysis_items, passthrough_items = self.partition_analysis_items(
                    merged_items
                )
                analyzed_items = await self._analyze_content(analysis_items)
                usage = self._last_analysis_usage
                analysis_usage = AnalysisUsage(
                    item_count=len(merged_items),
                    cache_hits=usage.cache_hits,
                    ai_calls=usage.ai_calls,
                    provider_attempts=usage.provider_attempts,
                    fallbacks=usage.fallbacks,
                    skipped=len(passthrough_items),
                )
                result_items = analyzed_items + passthrough_items

                threshold = self.config.filtering.featured_score_threshold
                featured_items = [
                    item
                    for item in result_items
                    if item.ai_score and item.ai_score >= threshold
                ]
                featured_items.sort(
                    key=lambda item: item.ai_score or 0,
                    reverse=True,
                )
                featured_items = await self.merge_topic_duplicates(featured_items)
                await self._expand_twitter_discussion(featured_items)
                if enrich:
                    await self._enrich_important_items(featured_items)
                daily_push_items = select_daily_push_items(
                    featured_items,
                    threshold=self.config.filtering.daily_push_score_threshold,
                    limit=self.config.filtering.daily_push_limit,
                )
            else:
                result_items = self.publish_without_ai(merged_items)
                analysis_usage = AnalysisUsage(
                    item_count=len(merged_items),
                    skipped=len(merged_items),
                )
                featured_items = []
                daily_push_items = []
            for item in result_items:
                normalize_item_summary(item, self.config.ai.summary_max_chars)
        except Exception as exc:
            issue = RunIssue(
                stage="pipeline",
                code=type(exc).__name__,
                message=str(exc),
                retryable=_is_retryable_source_exception(exc),
            )
            return FeedRunResult(
                run_id=run_id,
                status="failed",
                started_at=started_at.isoformat(),
                finished_at=datetime.now(timezone.utc).isoformat(),
                source_outcomes=source_outcomes,
                issues=fetch_issues + (issue,),
                analysis_usage=analysis_usage,
                acquisition_usage=self._service_acquisition_usage(),
            )
        return FeedRunResult(
            run_id=run_id,
            status=("partial" if has_failed_sources else "succeeded"),
            started_at=started_at.isoformat(),
            finished_at=datetime.now(timezone.utc).isoformat(),
            items=tuple(result_items),
            featured_item_ids=tuple(item.id for item in featured_items),
            daily_push_item_ids=tuple(item.id for item in daily_push_items),
            source_outcomes=source_outcomes,
            issues=fetch_issues,
            analysis_usage=analysis_usage,
            acquisition_usage=self._service_acquisition_usage(),
        )

    def _service_source_specs(self, client: httpx.AsyncClient) -> list[tuple[str, Any, Any]]:
        """Build one strict scraper task per configured service source."""
        specs: list[tuple[str, Any, Any]] = []

        for source in self.config.sources.github:
            if source.enabled:
                specs.append((f"GitHub:{source.source_id or source.source_key or source.type}", GitHubScraper([source], client), source))
        if self.config.sources.hackernews.enabled:
            source = self.config.sources.hackernews
            specs.append((f"HackerNews:{source.source_id or source.source_key or 'default'}", HackerNewsScraper(source, client), source))
        for source in self.config.sources.rss:
            if source.enabled:
                specs.append((f"RSS:{source.source_id or source.source_key or source.name}", RSSScraper([source], client), source))

        reddit = self.config.sources.reddit
        if reddit.enabled:
            for source in reddit.subreddits:
                if source.enabled:
                    config = reddit.model_copy(update={"enabled": True, "subreddits": [source], "users": []})
                    specs.append((f"Reddit:{source.source_id or source.source_key or source.subreddit}", RedditScraper(config, client), source))
            for source in reddit.users:
                if source.enabled:
                    config = reddit.model_copy(update={"enabled": True, "subreddits": [], "users": [source]})
                    specs.append((f"Reddit:{source.source_id or source.source_key or source.username}", RedditScraper(config, client), source))

        telegram = self.config.sources.telegram
        if telegram.enabled:
            for source in telegram.channels:
                if source.enabled:
                    config = telegram.model_copy(update={"enabled": True, "channels": [source]})
                    specs.append((f"Telegram:{source.source_id or source.source_key or source.channel}", TelegramScraper(config, client), source))

        apify = self.config.sources.apify_social
        if apify and apify.enabled:
            for source in apify.subscriptions:
                if source.enabled:
                    config = apify.model_copy(update={"enabled": True, "subscriptions": [source]})
                    specs.append((
                        f"Apify:{source.source_id or source.source_key or source.target}",
                        ApifySocialScraper(
                            config,
                            client,
                            apify_coordinator=self._service_apify_coordinator,
                        ),
                        source,
                    ))

        for _label, scraper, _source in specs:
            scraper.strict_errors = True
        return specs

    async def fetch_service_sources(
        self,
        since: datetime,
    ) -> tuple[list[ContentItem], tuple[SourceOutcome, ...]]:
        """Fetch service sources independently and retain their outcomes."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            specs = self._service_source_specs(client)
            results = await asyncio.gather(
                *(
                    self._fetch_service_source(label, scraper, source, since)
                    for label, scraper, source in specs
                ),
                return_exceptions=True,
            )

        items: list[ContentItem] = []
        outcomes: list[SourceOutcome] = []
        for (label, scraper, source), result in zip(specs, results):
            analysis_mode = getattr(source, "analysis_mode", "full")
            if hasattr(analysis_mode, "value"):
                analysis_mode = analysis_mode.value
            source_id = str(getattr(source, "source_id", None) or "")
            catalog_type = str(
                getattr(source, "catalog_source_type", None)
                or label.split(":", 1)[0].strip().lower()
            )
            upstream_schema = getattr(scraper, "upstream_response_schema", None)
            origin_for = getattr(self._service_acquisition_coordinator, "origin_for", None)
            acquisition_origin = origin_for(source_id) if callable(origin_for) else None
            if isinstance(result, Exception):
                issue = RunIssue(
                    stage="fetch",
                    code=str(getattr(result, "code", None) or type(result).__name__),
                    message=str(result),
                    retryable=_is_retryable_source_exception(result),
                )
                outcomes.append(
                    SourceOutcome(
                        source_id=source_id,
                        subscription_id=getattr(source, "subscription_id", None),
                        source_key=str(getattr(source, "source_key", None) or label),
                        analysis_mode=str(analysis_mode or "full"),
                        status="failed",
                        fetched_count=0,
                        issue=issue,
                        catalog_type=catalog_type,
                        capture_status="captured" if upstream_schema else "unavailable",
                        upstream_schema=upstream_schema,
                        normalized_schema=extract_response_schema([]),
                    )
                )
                continue
            fetched = result if isinstance(result, list) else []
            source_priority = int(getattr(source, "source_priority", 0) or 0)
            for item in fetched:
                item.metadata["source_priority"] = source_priority
            items.extend(fetched)
            outcomes.append(
                SourceOutcome(
                    source_id=source_id,
                    subscription_id=getattr(source, "subscription_id", None),
                    source_key=str(getattr(source, "source_key", None) or label),
                    analysis_mode=str(analysis_mode or "full"),
                    status="succeeded",
                    fetched_count=len(fetched),
                    catalog_type=catalog_type,
                    capture_status=(
                        "cached"
                        if acquisition_origin == "cache"
                        else "captured"
                        if upstream_schema and (upstream_schema.get("fields") or fetched)
                        else "empty"
                        if upstream_schema is not None
                        else "unavailable"
                    ),
                    upstream_schema=upstream_schema,
                    normalized_schema=extract_response_schema(
                        [item.model_dump(mode="json") for item in fetched]
                    ),
                )
            )
        return items, tuple(outcomes)

    async def _fetch_service_source(
        self,
        label: str,
        scraper: Any,
        source: Any,
        since: datetime,
    ) -> list[ContentItem]:
        provider = label.split(":", 1)[0].strip().lower().replace(" ", "_")

        async def fetch_upstream() -> list[ContentItem]:
            meter = self._service_attempt_meter
            before_fetch_attempt = getattr(meter, "before_fetch_attempt", None)
            if callable(before_fetch_attempt):
                before_fetch_attempt(
                    provider=provider,
                    source_id=str(getattr(source, "source_id", None) or ""),
                )
            return await self._fetch_with_progress(label, scraper, since)

        coordinator = self._service_acquisition_coordinator
        acquire = getattr(coordinator, "acquire", None)
        if callable(acquire):
            elapsed_hours = (
                datetime.now(timezone.utc) - since.astimezone(timezone.utc)
            ).total_seconds() / 3600
            return await acquire(
                source=source,
                provider=provider,
                window_hours=max(int(round(elapsed_hours)), 1),
                fetch=fetch_upstream,
            )
        return await fetch_upstream()

    async def run(
        self,
        force_hours: int = None,
        *,
        send_notifications: bool = True,
        write_summaries: bool = True,
        incremental: bool = False,
        enrich: bool = True,
    ) -> None:
        """Run the legacy CLI/scheduler path through structured execution and publishing."""
        self.console.print("[bold cyan]🌅 Horizon - Starting aggregation...[/bold cyan]\n")
        publisher = LegacyPublisher(self)
        try:
            publisher.prepare()
            known_ids = (
                load_history_item_ids(self.storage.data_dir / "site")
                if incremental
                else set()
            )
            result = await self.execute(
                force_hours=force_hours,
                enrich=enrich,
                legacy_sources=True,
                exclude_item_ids=known_ids,
            )
            await publisher.publish(
                result,
                send_notifications=send_notifications,
                write_summaries=write_summaries,
            )
        except Exception as exc:
            self.console.print(f"[bold red]❌ Error: {exc}[/bold red]")
            try:
                await publisher.notify_failure(
                    exc,
                    send_notifications=send_notifications,
                )
            except Exception as notify_exc:
                self.console.print(
                    f"[yellow]⚠️  Failed to send failure notification: {notify_exc}[/yellow]"
                )
            raise

    def _determine_time_window(self, force_hours: int = None) -> datetime:
        if force_hours:
            since = datetime.now(timezone.utc) - timedelta(hours=force_hours)
        else:
            hours = self.config.filtering.time_window_hours
            since = datetime.now(timezone.utc) - timedelta(hours=hours)
        return since

    async def run_single_source_update(
        self,
        source_ref: SourceRef,
        force_hours: int,
    ) -> dict[str, object]:
        """Fetch and publish one explicitly selected source without side effects.

        This path is used by the config UI/CLI for immediate source refreshes.
        It deliberately skips notifications, summaries, enrichment, and article
        graph/full-text work so the user only pays for the requested source.
        """
        self.console.print(
            f"[bold cyan]Horizon - Updating source {source_ref.ref}...[/bold cyan]\n"
        )
        since = self._determine_time_window(force_hours)
        self.console.print(f"📅 Fetching content since: {since.strftime('%Y-%m-%d %H:%M:%S')}\n")

        raw_items = await self.fetch_all_sources(since)
        merged_items = self.merge_cross_source_duplicates(raw_items)
        skipped_existing = 0

        known_ids = load_history_item_ids(self.storage.data_dir / "site")
        if known_ids:
            new_items = [item for item in merged_items if item.id not in known_ids]
            skipped_existing = len(merged_items) - len(new_items)
            merged_items = new_items

        if not merged_items:
            self.console.print("[yellow]No unpublished content found for selected source.[/yellow]")
            return {
                "ok": True,
                "source_ref": source_ref.ref,
                "hours": force_hours,
                "fetched": len(merged_items),
                "raw_before_merge": len(raw_items),
                "merged": 0,
                "skipped_existing": skipped_existing,
                "analyzed": 0,
                "passthrough": 0,
                "web_ui_updated": False,
            }

        if self._ai_enabled():
            analysis_items, passthrough_items = self.partition_analysis_items(merged_items)
            analyzed_items = await self._analyze_content(analysis_items)
            published_items = analyzed_items + passthrough_items
        else:
            analyzed_items = []
            passthrough_items = self.publish_without_ai(merged_items)
            published_items = passthrough_items
            self.console.print("[dim]AI scoring disabled; publishing fetched items without model analysis.[/dim]\n")
        web_ui_updated = await LegacyPublisher(self).write_web_ui(
            items=published_items,
            today=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            total_fetched=len(raw_items),
        )

        return {
            "ok": True,
            "source_ref": source_ref.ref,
            "hours": force_hours,
            "fetched": len(published_items),
            "raw_before_merge": len(raw_items),
            "merged": len(merged_items),
            "skipped_existing": skipped_existing,
            "analyzed": len(analyzed_items),
            "passthrough": len(passthrough_items),
            "web_ui_updated": web_ui_updated,
        }

    async def fetch_all_sources(self, since: datetime) -> List[ContentItem]:
        """Fetch content from all configured sources.

        This is a stable stage entry point for integrations such as MCP.

        Args:
            since: Fetch items published after this time

        Returns:
            List[ContentItem]: All fetched items
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            tasks = []

            # GitHub sources
            if self.config.sources.github:
                github_scraper = GitHubScraper(self.config.sources.github, client)
                tasks.append(self._fetch_with_progress("GitHub", github_scraper, since))

            # Hacker News
            if self.config.sources.hackernews.enabled:
                hn_scraper = HackerNewsScraper(self.config.sources.hackernews, client)
                tasks.append(self._fetch_with_progress("Hacker News", hn_scraper, since))

            # RSS feeds
            if self.config.sources.rss:
                rss_scraper = RSSScraper(self.config.sources.rss, client)
                tasks.append(self._fetch_with_progress("RSS Feeds", rss_scraper, since))

            # Reddit
            if self.config.sources.reddit.enabled:
                reddit_scraper = RedditScraper(self.config.sources.reddit, client)
                tasks.append(self._fetch_with_progress("Reddit", reddit_scraper, since))

            # Telegram
            if self.config.sources.telegram.enabled:
                telegram_scraper = TelegramScraper(self.config.sources.telegram, client)
                tasks.append(self._fetch_with_progress("Telegram", telegram_scraper, since))

            # Twitter
            if self.config.sources.twitter and self.config.sources.twitter.enabled:
                twitter_scraper = TwitterScraper(self.config.sources.twitter, client)
                tasks.append(self._fetch_with_progress("Twitter", twitter_scraper, since))

            # Unified Apify social subscriptions (X, Instagram, Facebook, Telegram)
            if (
                self.config.sources.apify_social
                and self.config.sources.apify_social.enabled
            ):
                apify_social_scraper = ApifySocialScraper(
                    self.config.sources.apify_social,
                    client,
                )
                tasks.append(
                    self._fetch_with_progress("Apify Social", apify_social_scraper, since)
                )

            # OpenBB (financial news / filings via the OpenBB Platform SDK)
            if self.config.sources.openbb and self.config.sources.openbb.enabled:
                openbb_scraper = OpenBBScraper(self.config.sources.openbb, client)
                tasks.append(self._fetch_with_progress("OpenBB", openbb_scraper, since))

            # OSS Insight trending repos
            if self.config.sources.ossinsight and self.config.sources.ossinsight.enabled:
                oss_scraper = OSSInsightScraper(self.config.sources.ossinsight, client)
                tasks.append(self._fetch_with_progress("OSS Insight", oss_scraper, since))

            # Fetch all concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Flatten results
            all_items = []
            for result in results:
                if isinstance(result, Exception):
                    self.console.print(f"[red]Error fetching source: {result}[/red]")
                elif isinstance(result, list):
                    all_items.extend(result)

            return all_items

    async def _fetch_with_progress(self, name: str, scraper, since: datetime) -> List[ContentItem]:
        """Fetch from a scraper with progress indication.

        Args:
            name: Source name for display
            scraper: Scraper instance
            since: Fetch items after this time

        Returns:
            List[ContentItem]: Fetched items
        """
        self.console.print(f"🔍 Fetching from {name}...")
        items = await scraper.fetch(since)
        self.console.print(f"   Found {len(items)} items from {name}")

        # Show per-sub-source breakdown when there are multiple sub-sources
        sub_counts: Dict[str, int] = defaultdict(int)
        for item in items:
            sub_counts[self._sub_source_label(item)] += 1
        if len(sub_counts) > 1:
            for sub, count in sorted(sub_counts.items()):
                self.console.print(f"      • {sub}: {count}")

        return items

    @staticmethod
    def _sub_source_label(item: ContentItem) -> str:
        """Return a human-readable sub-source label for an item."""
        meta = item.metadata
        if meta.get("subreddit"):
            return f"r/{meta['subreddit']}"
        if meta.get("feed_name"):
            return meta["feed_name"]
        if meta.get("channel"):
            return f"@{meta['channel']}"
        if meta.get("period") and meta.get("repo"):
            return f"ossinsight:{meta.get('primary_language', 'all')}"
        if meta.get("repo"):
            return meta["repo"]
        if meta.get("watchlist"):
            return meta["watchlist"]
        return item.author or "unknown"

    def merge_cross_source_duplicates(self, items: List[ContentItem]) -> List[ContentItem]:
        """Merge items that point to the same URL from different sources.

        This is a stable stage helper for integrations such as MCP.

        Keeps the item with the richest content and combines metadata.

        Args:
            items: Items to deduplicate

        Returns:
            List[ContentItem]: Deduplicated items
        """
        # Group by normalized URL
        url_groups: Dict[str, List[ContentItem]] = {}
        for item in items:
            key = canonical_url_key(item.url)
            url_groups.setdefault(key, []).append(item)

        merged = []
        for key, group in url_groups.items():
            source_priority = max(
                (
                    int(item.metadata.get("source_priority") or 0)
                    for item in group
                ),
                default=0,
            )
            source_ids = list(dict.fromkeys(
                str(value)
                for item in group
                for value in [
                    *(item.metadata.get("source_ids") or []),
                    item.metadata.get("source_id"),
                ]
                if value
            ))
            subscription_ids = list(dict.fromkeys(
                str(value)
                for item in group
                for value in [
                    *(item.metadata.get("subscription_ids") or []),
                    item.metadata.get("subscription_id"),
                ]
                if value
            ))
            source_keys = list(dict.fromkeys(
                str(value)
                for item in group
                for value in [
                    *(item.metadata.get("source_keys") or []),
                    item.metadata.get("source_key"),
                ]
                if value
            ))
            if len(group) == 1:
                group[0].metadata["source_priority"] = source_priority
                group[0].metadata["source_ids"] = source_ids
                group[0].metadata["subscription_ids"] = subscription_ids
                group[0].metadata["source_keys"] = source_keys
                merged.append(group[0])
                continue

            # Preserve the richest source payload; Feed finalization stabilizes identity.
            primary = max(group, key=lambda item: len(item.content or ""))

            # Merge metadata and source info from other items
            all_sources = set()
            for item in group:
                all_sources.add(item.source_type.value)
                # Merge metadata (engagement, discussion, etc.)
                for mk, mv in item.metadata.items():
                    if mk not in primary.metadata or not primary.metadata[mk]:
                        primary.metadata[mk] = mv

                # Append content (e.g., comments from another source)
                if item is not primary and item.content:
                    if primary.content and item.content not in primary.content:
                        primary.content = (primary.content or "") + f"\n\n--- From {item.source_type.value} ---\n" + item.content

            primary.metadata["merged_sources"] = list(all_sources)
            primary.metadata["source_priority"] = source_priority
            primary.metadata["source_ids"] = source_ids
            primary.metadata["subscription_ids"] = subscription_ids
            primary.metadata["source_keys"] = source_keys
            if any(
                item.metadata.get("analysis_mode") == "personal_only"
                for item in group
            ):
                primary.metadata["analysis_mode"] = "personal_only"
                primary.metadata["show_in_personal_feed"] = True
            merged.append(primary)

        return merged

    async def merge_topic_duplicates(self, items: List[ContentItem]) -> List[ContentItem]:
        """Merge items covering the same topic using AI semantic deduplication.

        This is a stable stage helper for integrations such as MCP.

        Sends all item titles, tags, and summaries to AI in a single call.
        Items must already be sorted by ai_score descending so that the first
        item in each duplicate group is always the highest-scored one.
        Content (comments) from duplicate items is merged into the primary.

        Falls back to returning items unchanged if the AI call fails.
        """
        if len(items) <= 1:
            return items

        from .ai.prompts import TOPIC_DEDUP_SYSTEM, TOPIC_DEDUP_USER
        from .ai.utils import parse_json_response

        # Build the item list for the prompt
        lines = []
        for i, item in enumerate(items):
            tags = ", ".join(item.ai_tags) if item.ai_tags else "—"
            summary = item.ai_summary or "—"
            lines.append(f"[{i}] {item.title}\n    Tags: {tags}\n    Summary: {summary}")
        items_text = "\n\n".join(lines)

        try:
            ai_client = create_ai_client(self.config.ai)
            with token_stage("dedupe"):
                response = await ai_client.complete(
                    system=TOPIC_DEDUP_SYSTEM,
                    user=TOPIC_DEDUP_USER.format(items=items_text),
                )
            result = parse_json_response(response)
            if result is None:
                self.console.print("[yellow]  dedup: could not parse AI response, skipping[/yellow]")
                return items

            duplicate_groups = result.get("duplicates", [])
        except Exception as e:
            self.console.print(f"[yellow]  dedup: AI call failed ({e}), skipping[/yellow]")
            return items

        if not duplicate_groups:
            return items

        # Build a set of indices to drop (all non-primary duplicates)
        drop_indices: set[int] = set()
        for group in duplicate_groups:
            if not isinstance(group, list) or len(group) < 2:
                continue
            primary_idx = group[0]
            if primary_idx < 0 or primary_idx >= len(items):
                continue
            primary = items[primary_idx]
            for dup_idx in group[1:]:
                if not isinstance(dup_idx, int) or dup_idx < 0 or dup_idx >= len(items):
                    continue
                if dup_idx == primary_idx:
                    continue
                dup = items[dup_idx]
                # Merge comments/content from the duplicate into the primary
                if dup.content:
                    if not primary.content or dup.content not in primary.content:
                        label = dup.source_type.value
                        primary.content = (primary.content or "") + f"\n\n--- From {label} ---\n{dup.content}"
                self.console.print(
                    f"   [dim]dedup: keep [{primary_idx}] {primary.title}[/dim]\n"
                    f"   [dim]       drop [{dup_idx}] {dup.title}[/dim]"
                )
                drop_indices.add(dup_idx)

        return [item for i, item in enumerate(items) if i not in drop_indices]

    async def _expand_twitter_discussion(self, items: List[ContentItem]) -> None:
        """Second-stage: fetch reply text for important Twitter items and re-analyze.

        Only runs when sources.twitter.fetch_reply_text is True.
        Bounded by max_tweets_to_expand to control cost.
        """
        tw_cfg = self.config.sources.twitter
        if not tw_cfg or not tw_cfg.enabled or not tw_cfg.fetch_reply_text:
            return

        from .models import SourceType

        twitter_items = [
            item for item in items
            if item.source_type == SourceType.TWITTER
        ][:tw_cfg.max_tweets_to_expand]

        if not twitter_items:
            return

        self.console.print(
            f"💬 Fetching reply text for {len(twitter_items)} Twitter items..."
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            scraper = TwitterScraper(tw_cfg, client)
            expanded = []
            for item in twitter_items:
                try:
                    reply_lines = await scraper.fetch_replies_for_item(item)
                    if TwitterScraper.append_discussion_content(item, reply_lines):
                        expanded.append(item)
                        self.console.print(
                            f"   💬 {len(reply_lines)} replies added to: {item.title[:60]}"
                        )
                except Exception as exc:
                    self.console.print(
                        f"   [yellow]⚠️  Reply fetch failed for {item.id}: {exc}[/yellow]"
                    )

        if not expanded:
            return

        self.console.print(
            f"   Re-analyzing {len(expanded)} Twitter items with reply context...\n"
        )
        ai_client = create_ai_client(self.config.ai)
        analyzer = ContentAnalyzer(ai_client, cache=self._analysis_cache(), topic_library=self.config.tags)
        await analyzer.analyze_batch(expanded)

    async def _enrich_important_items(self, items: List[ContentItem]) -> None:
        """Enrich items with background knowledge (2nd AI pass).

        For each item that passed the score threshold, call AI to generate
        background knowledge based on the item's actual content.

        Args:
            items: Important items to enrich (modified in-place)
        """
        if not items:
            return

        self.console.print("📚 Enriching with background knowledge...")
        ai_client = create_ai_client(self.config.ai)
        enricher = ContentEnricher(ai_client)
        with token_stage("enrichment"):
            await enricher.enrich_batch(items)
        self.console.print(f"   Enriched {len(items)} items\n")

    @staticmethod
    def _source_topics(item: ContentItem) -> list[str]:
        topics = item.metadata.get("topics") or item.metadata.get("tags") or []
        return topics if isinstance(topics, list) else []

    @classmethod
    def _source_channel(cls, item: ContentItem) -> str:
        return normalize_channel(
            item.metadata.get("channel") or item.metadata.get("category"),
            fallback=(cls._source_topics(item) or [item.source_type.value])[0],
        )

    @classmethod
    def partition_analysis_items(cls, items: List[ContentItem]) -> tuple[List[ContentItem], List[ContentItem]]:
        """Split items that should call AI from personal-only passthrough items."""
        analysis_items: List[ContentItem] = []
        passthrough_items: List[ContentItem] = []
        for item in items:
            if item.metadata.get("analysis_mode") == "personal_only":
                channel = cls._source_channel(item)
                topics = normalize_tags(
                    cls._source_topics(item),
                    fallback=channel,
                    max_tags=6,
                    allow_custom=True,
                )
                item.ai_score = 0.0
                item.ai_reason = None
                item.ai_summary = item.ai_summary or item.content or item.title
                item.ai_summary_zh = item.ai_summary_zh or item.ai_summary
                item.ai_channel = item.ai_channel or channel
                item.ai_topics = item.ai_topics or topics
                item.ai_category = item.ai_category or channel
                item.ai_tags = item.ai_tags or topics
                item.ai_signal_strength = item.ai_signal_strength or "thin"
                item.ai_signal_type = item.ai_signal_type or "personal_update"
                item.ai_is_featured = False
                item.ai_action_suggestion = None
                item.metadata["show_in_personal_feed"] = True
                item.metadata["analysis_status"] = "personal_only"
                passthrough_items.append(item)
            else:
                analysis_items.append(item)
        return analysis_items, passthrough_items

    def _ai_enabled(self) -> bool:
        return bool(getattr(self.config.ai, "enabled", True))

    @staticmethod
    def _fallback_category(item: ContentItem) -> str:
        return HorizonOrchestrator._source_channel(item)

    @classmethod
    def publish_without_ai(cls, items: List[ContentItem]) -> List[ContentItem]:
        """Prepare fetched items for the static UI without model scoring."""
        published: List[ContentItem] = []
        for item in items:
            summary = item.ai_summary_zh or item.ai_summary or item.content or item.title
            channel = cls._source_channel(item)
            topics = normalize_tags(
                cls._source_topics(item),
                fallback=channel,
                max_tags=6,
                allow_custom=True,
            )
            item.ai_score = 0.0
            item.ai_reason = None
            item.ai_summary = item.ai_summary or summary
            item.ai_summary_zh = item.ai_summary_zh or summary
            item.ai_channel = item.ai_channel or channel
            item.ai_topics = item.ai_topics or topics
            item.ai_category = item.ai_category or channel
            item.ai_tags = item.ai_tags or topics
            item.ai_signal_strength = item.ai_signal_strength or normalize_signal_strength(
                None,
                score=0.0,
            )
            item.ai_signal_type = item.ai_signal_type or normalize_signal_type(
                item.metadata.get("signal_type"),
            )
            item.ai_is_featured = False
            # New analysis and no-AI fallback runs no longer manufacture a
            # suggested action.  The field remains serializable only so old
            # snapshots can still be read during the compatibility window.
            item.ai_action_suggestion = None
            item.metadata["scoring_disabled"] = True
            item.metadata["analysis_status"] = (
                "personal_only"
                if item.metadata.get("analysis_mode") == "personal_only"
                else "disabled"
            )
            if item.metadata.get("analysis_mode") == "personal_only":
                item.metadata["show_in_personal_feed"] = True
            published.append(item)
        return published

    def _analysis_cache(self) -> AnalysisCache | None:
        if self._service_analysis_cache is not None:
            return self._service_analysis_cache
        if _SERVICE_EXECUTION.get():
            return None
        return AnalysisCache(self.storage.data_dir / "cache" / "analysis-cache.jsonl")

    async def _write_web_ui(
        self,
        all_items: List[ContentItem],
        today: str,
        total_fetched: int,
    ) -> bool:
        """Write the static private radar UI under data/site."""
        try:
            payload = build_site_payload(
                all_items=all_items,
                date=today,
                total_fetched=total_fetched,
                featured_threshold=self.config.filtering.featured_score_threshold,
                daily_push_threshold=self.config.filtering.daily_push_score_threshold,
                daily_push_limit=self.config.filtering.daily_push_limit,
                homepage_min_score=self.config.filtering.homepage_min_score,
                recent_item_limit=self.config.filtering.recent_item_limit,
                tag_library=self.config.tags,
                personal_tag_library=self.config.personal_tags,
                ai_enabled=self._ai_enabled(),
            )
            data_path = write_static_site(self.storage.data_dir / "site", payload)
            self.console.print(f"🌐 Updated web UI data: {data_path}\n")
            return True
        except Exception as exc:
            self.console.print(f"[yellow]⚠️  Failed to update web UI: {exc}[/yellow]\n")
            return False

    async def _run_article_graph_pipeline(self, items: List[ContentItem]) -> None:
        """Optionally persist light article data and build static relationship graph."""
        if not (
            getattr(self.config.premium_analysis, "enabled", False)
            or getattr(self.config.article_graph, "enabled", False)
        ):
            return

        try:
            store = ArticleStore(self.storage.data_dir)
            store.initialize()
            stored = store.upsert_articles_light(items)
            self.console.print(f"🕸️  Stored {stored} light articles for relationship analysis")

            if self.config.premium_analysis.enabled:
                fetcher = FullTextFetcher(
                    store,
                    score_threshold=self.config.premium_analysis.full_fetch_score_threshold,
                    max_articles=self.config.premium_analysis.max_full_fetch_per_run,
                    max_chars=self.config.premium_analysis.max_full_text_chars,
                    concurrency=self.config.premium_analysis.full_fetch_concurrency,
                )
                fetched = await fetcher.fetch_missing()
                self.console.print(f"   Full-text fetched for {fetched} premium articles")

            if self.config.article_graph.enabled:
                snapshot = build_article_graph_snapshot(
                    store,
                    premium_score_threshold=self.config.article_graph.premium_score_threshold,
                    relation_top_k=self.config.article_graph.relation_top_k,
                    min_relation_score=self.config.article_graph.min_relation_score,
                    max_visible_nodes=self.config.article_graph.max_visible_nodes,
                    max_visible_edges=self.config.article_graph.max_visible_edges,
                )
                graph_path = write_article_graph_snapshot(
                    self.storage.data_dir / "site",
                    snapshot,
                )
                self.console.print(
                    "   Article graph: "
                    f"{snapshot['stats']['nodes']} nodes, "
                    f"{snapshot['stats']['edges']} edges → {graph_path}\n"
                )
        except Exception as exc:
            self.console.print(
                f"[yellow]⚠️  Article relationship analysis skipped: {exc}[/yellow]\n"
            )

    async def _analyze_content(self, items: List[ContentItem]) -> List[ContentItem]:
        """Analyze content items with AI.

        Args:
            items: Items to analyze

        Returns:
            List[ContentItem]: Analyzed items
        """
        if not items:
            return []
        self.console.print("🤖 Analyzing content with AI...")

        ai_client = create_ai_client(self.config.ai)
        analyzer = ContentAnalyzer(ai_client, cache=self._analysis_cache(), topic_library=self.config.tags)
        analyzed = await analyzer.analyze_batch(items)
        self._last_analysis_usage = AnalysisUsage(**analyzer.usage)
        return analyzed

    async def _generate_summary(
        self,
        items: List[ContentItem],
        date: str,
        total_fetched: int,
        language: str = "en",
    ) -> str:
        """Generate daily summary.

        Args:
            items: Important items to include (already enriched with background/related)
            date: Date string
            total_fetched: Total items fetched
            language: Output language ("en" or "zh")

        Returns:
            str: Markdown summary
        """
        self.console.print("📝 Generating daily summary...")

        summarizer = DailySummarizer()

        with token_stage("summary"):
            return await summarizer.generate_summary(items, date, total_fetched, language=language)
