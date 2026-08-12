"""Main orchestrator coordinating the entire workflow."""

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, List, Dict
from uuid import uuid4
import httpx
from rich.console import Console

from .models import Config, ContentItem
from .storage.manager import StorageManager
from .services.daily_push import select_daily_push_items
from .services.feed_run import (
    AcquisitionUsage,
    AnalysisUsage,
    FeedRunResult,
    RunIssue,
    SourceOutcome,
)
from .services.response_schema import extract_response_schema
from .services.canonical_content import canonical_url_key
from .scrapers.github import GitHubScraper
from .scrapers.hackernews import HackerNewsScraper
from .scrapers.rss import RSSScraper
from .scrapers.reddit import RedditScraper
from .scrapers.telegram import TelegramScraper
from .scrapers.twitter import TwitterScraper
from .scrapers.apify_social import ApifySocialScraper
from .ai.client import create_ai_client
from .ai.analyzer import ContentAnalyzer
from .ai.enricher import ContentEnricher
from .ai.tokens import get_usage_snapshot, token_stage
from .ai.summary_policy import normalize_item_summary, preserve_source_summary
from .tag_policy import (
    normalize_channel,
    normalize_signal_strength,
    normalize_signal_type,
    normalize_tags,
)


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
        self._service_apify_actor_route: Any | None = None
        self._service_apify_actor_ops: Any | None = None
        self._service_apify_actor_ops_job_id: str | None = None
        self._service_apify_actor_ops_snapshots: list[Any] = []
        self._service_apify_watermark_proofs: list[dict[str, str]] = []
        self._service_apify_actor_route_job_id: str | None = None
        self._service_apify_forced_candidate_id: str | None = None
        self._service_apify_forced_route_generation: int | None = None
        self._service_apify_paid_canary = False
        self._last_analysis_usage = AnalysisUsage()
        self.console = Console()

    def set_service_analysis_cache(self, cache: Any | None) -> None:
        """Attach the user-scoped analysis cache owned by the Service store."""
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

    def set_service_apify_actor_route(
        self,
        route: Any | None,
        *,
        job_id: str | None = None,
        candidate_id: str | None = None,
        expected_generation: int | None = None,
        paid_canary: bool = False,
    ) -> None:
        """Attach the independent X/profile Actor route to Service fetching."""

        self._service_apify_actor_route = route
        self._service_apify_actor_route_job_id = job_id
        self._service_apify_forced_candidate_id = candidate_id
        self._service_apify_forced_route_generation = expected_generation
        self._service_apify_paid_canary = bool(paid_canary)

    def set_service_apify_actor_ops(
        self,
        actor_ops: Any | None,
        *,
        job_id: str | None = None,
    ) -> None:
        """Attach the generic three-slot ActorOps runtime."""

        self._service_apify_actor_ops = actor_ops
        self._service_apify_actor_ops_job_id = job_id

    def assert_service_apify_actor_ops_publishable(self) -> None:
        """Fence Actor-derived results immediately before Feed persistence."""

        assert_acquisition_current = getattr(
            self._service_acquisition_coordinator,
            "assert_publication_current",
            None,
        )
        if callable(assert_acquisition_current):
            assert_acquisition_current()
        if self._service_apify_actor_ops is None:
            return
        for snapshot in self._service_apify_actor_ops_snapshots:
            self._service_apify_actor_ops.assert_publishable(snapshot)

    def _capture_service_apify_watermark(self, items: Any) -> None:
        if str(
            getattr(items, "_apify_actor_semantic_outcome", "") or ""
        ) != "advanced":
            return
        proof = {
            "workspace_id": getattr(
                items, "_apify_actor_workspace_id", None
            ),
            "source_id": getattr(items, "_apify_actor_source_id", None),
            "candidate_id": getattr(
                items, "_apify_actor_candidate_id", None
            ),
            "latest_published_at": getattr(
                items, "_apify_actor_latest_published_at", None
            ),
            "latest_item_id_hash": getattr(
                items, "_apify_actor_latest_item_id_hash", None
            ),
        }
        if all(isinstance(value, str) and value for value in proof.values()):
            self._service_apify_watermark_proofs.append(proof)  # type: ignore[arg-type]

    def publish_service_apify_watermarks(self, *, connection: Any) -> None:
        """Advance Actor source watermarks in the final Feed transaction."""

        if not self._service_apify_watermark_proofs:
            return
        from .services.apify_actor_resilience import (
            ApifyActorResilienceService,
        )

        actor_service = (
            self._service_apify_actor_ops
            if self._service_apify_actor_ops is not None
            else self._service_apify_actor_route
        )
        if actor_service is None:
            raise RuntimeError("Actor watermark proof is missing its runtime")
        for proof in self._service_apify_watermark_proofs:
            ApifyActorResilienceService(
                actor_service.store,
                workspace_id=proof["workspace_id"],
            ).publish_source_advance(
                proof["source_id"],
                candidate_id=proof["candidate_id"],
                latest_published_at=proof["latest_published_at"],
                latest_item_id_hash=proof["latest_item_id_hash"],
                connection=connection,
            )

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
        exclude_item_ids: set[str] | None = None,
    ) -> FeedRunResult:
        """Run the Service pipeline without filesystem publishing side effects."""
        self._service_apify_actor_ops_snapshots = []
        self._service_apify_watermark_proofs = []
        return await self._execute_structured(
            force_hours=force_hours,
            enrich=enrich,
            exclude_item_ids=exclude_item_ids,
        )

    async def _execute_structured(
        self,
        force_hours: int | None = None,
        *,
        enrich: bool = False,
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
            raw_items, source_outcomes = await self.fetch_service_sources(
                since,
                allow_source_window_overrides=force_hours is None,
            )
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
                scraper: Any = RSSScraper([source], client)
                if (
                    self._service_apify_actor_ops is not None
                    and self._service_apify_coordinator is not None
                    and source.source_id
                ):
                    from .services.apify_native_fallback import (
                        YouTubeNativeActorFallbackScraper,
                        is_canonical_youtube_url,
                    )

                    if is_canonical_youtube_url(str(source.url)):
                        scraper = YouTubeNativeActorFallbackScraper(
                            source,
                            client,
                            actor_ops=self._service_apify_actor_ops,
                            apify_coordinator=self._service_apify_coordinator,
                            job_id=self._service_apify_actor_ops_job_id,
                        )
                specs.append((
                    f"RSS:{source.source_id or source.source_key or source.name}",
                    scraper,
                    source,
                ))

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
                    actor_ops_snapshot = None
                    if source.profile_id:
                        if (
                            self._service_apify_actor_ops is None
                            or not source.source_id
                        ):
                            raise RuntimeError(
                                "ActorOps source is missing its Service runtime"
                            )
                        actor_ops_snapshot = (
                            self._service_apify_actor_ops.freeze_execution(
                                str(source.profile_id),
                                source_id=str(source.source_id),
                            )
                        )
                        self._service_apify_actor_ops_snapshots.append(
                            actor_ops_snapshot
                        )
                    config = apify.model_copy(update={"enabled": True, "subscriptions": [source]})
                    specs.append((
                        f"Apify:{source.source_id or source.source_key or source.target}",
                        ApifySocialScraper(
                            config,
                            client,
                            apify_coordinator=self._service_apify_coordinator,
                            apify_actor_route=self._service_apify_actor_route,
                            apify_actor_ops=self._service_apify_actor_ops,
                            actor_ops_snapshot=actor_ops_snapshot,
                            route_job_id=(
                                self._service_apify_actor_ops_job_id
                                or self._service_apify_actor_route_job_id
                            ),
                            forced_candidate_id=(
                                self._service_apify_forced_candidate_id
                            ),
                            forced_route_generation=(
                                self._service_apify_forced_route_generation
                            ),
                            paid_canary=self._service_apify_paid_canary,
                        ),
                        source,
                    ))

        for _label, scraper, _source in specs:
            scraper.strict_errors = True
        return specs

    @staticmethod
    def _is_x_profile_source(source: Any) -> bool:
        platform = getattr(source, "platform", None)
        kind = getattr(source, "kind", "profile")
        if hasattr(platform, "value"):
            platform = platform.value
        if hasattr(kind, "value"):
            kind = kind.value
        return (
            str(platform or "").strip().casefold() == "x"
            and str(kind or "profile").strip().casefold() == "profile"
        )

    async def fetch_service_sources(
        self,
        since: datetime,
        *,
        allow_source_window_overrides: bool = True,
    ) -> tuple[list[ContentItem], tuple[SourceOutcome, ...]]:
        """Fetch service sources independently and retain their outcomes."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            specs = self._service_source_specs(client)
            window_anchor = datetime.now(timezone.utc)
            x_profile_actor_lock = asyncio.Lock()

            async def fetch_spec(
                label: str,
                scraper: Any,
                source: Any,
            ) -> list[ContentItem]:
                source_since = (
                    window_anchor
                    - timedelta(hours=int(source.service_fetch_window_hours))
                    if allow_source_window_overrides
                    and getattr(source, "service_fetch_window_hours", None)
                    else since
                )
                if self._is_x_profile_source(source):
                    async with x_profile_actor_lock:
                        return await self._fetch_service_source(
                            label,
                            scraper,
                            source,
                            source_since,
                        )
                return await self._fetch_service_source(
                    label,
                    scraper,
                    source,
                    source_since,
                )

            results = await asyncio.gather(
                *(
                    fetch_spec(label, scraper, source)
                    for label, scraper, source in specs
                ),
                return_exceptions=True,
            )

        items: list[ContentItem] = []
        outcomes: list[SourceOutcome] = []
        for (label, scraper, source), result in zip(specs, results):
            for snapshot in getattr(scraper, "publication_snapshots", ()):
                if snapshot not in self._service_apify_actor_ops_snapshots:
                    self._service_apify_actor_ops_snapshots.append(snapshot)
            analysis_mode = getattr(source, "analysis_mode", "full")
            if hasattr(analysis_mode, "value"):
                analysis_mode = analysis_mode.value
            source_id = str(getattr(source, "source_id", None) or "")
            catalog_type = str(
                getattr(source, "catalog_source_type", None)
                or label.split(":", 1)[0].strip().lower()
            )
            upstream_schema = getattr(scraper, "upstream_response_schema", None)
            avatar_hints = tuple(
                hint
                for hint in getattr(scraper, "source_avatar_hints", ())
                if hint.source_id == source_id
            )
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
                        avatar_hints=avatar_hints,
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
                    avatar_hints=avatar_hints,
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
            fetched = await acquire(
                source=source,
                provider=provider,
                window_hours=max(int(round(elapsed_hours)), 1),
                fetch=fetch_upstream,
            )
        else:
            fetched = await fetch_upstream()
        self._capture_service_apify_watermark(fetched)
        return fetched

    def _determine_time_window(self, force_hours: int = None) -> datetime:
        if force_hours is not None:
            since = datetime.now(timezone.utc) - timedelta(hours=force_hours)
        else:
            hours = self.config.filtering.time_window_hours
            since = datetime.now(timezone.utc) - timedelta(hours=hours)
        return since

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
        """Prepare fetched items for the Service Feed without model scoring."""
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

    def _analysis_cache(self) -> Any | None:
        """Return only the user-scoped Service cache supplied by the caller."""
        return self._service_analysis_cache

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
