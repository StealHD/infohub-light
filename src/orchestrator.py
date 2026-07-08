"""Main orchestrator coordinating the entire workflow."""

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict
from urllib.parse import urlparse
import httpx
from rich.console import Console

from .models import Config, ContentItem
from .storage.manager import StorageManager
from .services.email import EmailManager
from .services.webhook import WebhookNotifier
from .services.daily_push import select_daily_push_items
from .services.article_graph import build_article_graph_snapshot, write_article_graph_snapshot
from .services.fulltext import FullTextFetcher
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
from .tag_policy import (
    normalize_channel,
    normalize_signal_strength,
    normalize_signal_type,
    normalize_tags,
)
from .source_selection import SourceRef
from .ui.site import build_site_payload, load_history_item_ids, write_static_site


class HorizonOrchestrator:
    """Orchestrates the complete workflow for content aggregation and analysis."""

    def __init__(self, config: Config, storage: StorageManager):
        """Initialize orchestrator.

        Args:
            config: Application configuration
            storage: Storage manager
        """
        self.config = config
        self.storage = storage
        self.console = Console()
        self.email_manager = EmailManager(config.email, console=self.console) if config.email else None
        self.webhook_notifier = (
            WebhookNotifier(config.webhook, console=self.console)
            if config.webhook and config.webhook.enabled
            else None
        )

    async def run(
        self,
        force_hours: int = None,
        *,
        send_notifications: bool = True,
        write_summaries: bool = True,
        incremental: bool = False,
        enrich: bool = True,
    ) -> None:
        """Execute the complete workflow.

        Args:
            force_hours: Optional override for time window in hours
            send_notifications: Whether to send email/webhook notifications
            write_summaries: Whether to write Markdown daily summaries
            incremental: If True, skip items already present in UI history
            enrich: Whether to run second-stage background enrichment
        """
        self.console.print("[bold cyan]🌅 Horizon - Starting aggregation...[/bold cyan]\n")

        # Check email subscriptions if configured
        if (
            self.email_manager
            and self.config.email
            and self.config.email.enabled
            and self.config.email.imap_enabled
        ):
            self.console.print("📧 Checking for new email subscriptions...")
            self.email_manager.check_subscriptions(self.storage)

        try:
            # 1. Determine time window
            since = self._determine_time_window(force_hours)
            self.console.print(f"📅 Fetching content since: {since.strftime('%Y-%m-%d %H:%M:%S')}\n")

            # 2. Fetch content from all sources
            all_items = await self.fetch_all_sources(since)
            self.console.print(f"📥 Fetched {len(all_items)} items from all sources\n")

            if not all_items:
                self.console.print("[yellow]No new content found. Exiting.[/yellow]")
                return

            # 3. Merge cross-source duplicates (same URL from different sources)
            merged_items = self.merge_cross_source_duplicates(all_items)
            if len(merged_items) < len(all_items):
                self.console.print(
                    f"🔗 Merged {len(all_items) - len(merged_items)} cross-source duplicates "
                    f"→ {len(merged_items)} unique items\n"
                )

            if incremental:
                known_ids = load_history_item_ids(self.storage.data_dir / "site")
                if known_ids:
                    new_items = [item for item in merged_items if item.id not in known_ids]
                    skipped = len(merged_items) - len(new_items)
                    if skipped:
                        self.console.print(f"⏭️  Skipped {skipped} already-published items\n")
                    merged_items = new_items
                if not merged_items:
                    self.console.print("[yellow]No unpublished content found. Exiting.[/yellow]")
                    return

            if not self._ai_enabled():
                published_items = self.publish_without_ai(merged_items)
                await self._write_web_ui(
                    all_items=published_items,
                    today=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    total_fetched=len(all_items),
                )
                self.console.print(
                    "[dim]AI scoring disabled; skipped scoring, enrichment, summaries, notifications, and article graph.[/dim]\n"
                )
                self.console.print("[bold green]✅ Horizon completed successfully![/bold green]")
                return

            # 4. Analyze with AI
            analysis_items, passthrough_items = self.partition_analysis_items(merged_items)
            analyzed_items = await self._analyze_content(analysis_items)
            analyzed_items = analyzed_items + passthrough_items
            self.console.print(f"🤖 Analyzed {len(analyzed_items)} items with AI\n")

            # 5. Filter by featured score threshold
            threshold = self.config.filtering.featured_score_threshold
            important_items = [
                item for item in analyzed_items
                if item.ai_score and item.ai_score >= threshold
            ]
            important_items.sort(key=lambda x: x.ai_score or 0, reverse=True)

            self.console.print(
                f"⭐️ {len(important_items)} items scored ≥ {threshold}\n"
            )

            # 5.5 Semantic deduplication: drop items covering the same topic
            deduped_items = await self.merge_topic_duplicates(important_items)
            if len(deduped_items) < len(important_items):
                self.console.print(
                    f"🧹 Removed {len(important_items) - len(deduped_items)} topic duplicates "
                    f"→ {len(deduped_items)} unique items\n"
                )
            important_items = deduped_items

            # 5.6 Optional second-stage Twitter reply expansion + targeted re-analysis
            await self._expand_twitter_discussion(important_items)

            # Show per-sub-source selection breakdown
            selected_counts: Dict[str, int] = defaultdict(int)
            for item in important_items:
                key = f"{item.source_type.value}/{self._sub_source_label(item)}"
                selected_counts[key] += 1
            for source_key, count in sorted(selected_counts.items()):
                self.console.print(f"      • {source_key}: {count}")
            self.console.print("")

            # 6. Search related stories + enrich with background knowledge (2nd AI pass)
            if enrich:
                await self._enrich_important_items(important_items)
            elif important_items:
                self.console.print("[dim]Skipping background enrichment for incremental poll.[/dim]\n")

            # 6.5 Build static web UI data from all analyzed items.
            daily_push_items = select_daily_push_items(
                important_items,
                threshold=self.config.filtering.daily_push_score_threshold,
                limit=self.config.filtering.daily_push_limit,
            )
            await self._write_web_ui(
                all_items=analyzed_items,
                today=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                total_fetched=len(all_items),
            )
            await self._run_article_graph_pipeline(analyzed_items)

            if not write_summaries and not send_notifications:
                self.console.print("[dim]Skipping daily summary and notifications for incremental poll.[/dim]\n")
                self.console.print("[bold green]✅ Horizon completed successfully![/bold green]")
                return

            # 7. Generate and save daily summaries for each configured language
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            for lang in self.config.ai.languages:
                summarizer = DailySummarizer()
                with token_stage("summary"):
                    summary = await summarizer.generate_summary(
                        important_items,
                        today,
                        len(all_items),
                        language=lang,
                    )
                    push_summary = await summarizer.generate_summary(
                        daily_push_items,
                        today,
                        len(all_items),
                        language=lang,
                    )

                if write_summaries:
                    # Save to data/summaries/
                    summary_path = self.storage.save_daily_summary(today, summary, language=lang)
                    self.console.print(f"💾 Saved {lang.upper()} summary to: {summary_path}\n")

                    # Copy to docs/ for GitHub Pages
                    try:
                        post_filename = f"{today}-summary-{lang}.md"
                        posts_dir = Path("docs/_posts")
                        posts_dir.mkdir(parents=True, exist_ok=True)

                        dest_path = posts_dir / post_filename

                        # Add Jekyll front matter
                        front_matter = (
                            "---\n"
                            "layout: default\n"
                            f"title: \"Horizon Summary: {today} ({lang.upper()})\"\n"
                            f"date: {today}\n"
                            f"lang: {lang}\n"
                            "---\n\n"
                        )

                        # Strip leading H1 header to avoid duplication with Jekyll title
                        summary_content = summary
                        first_line = summary_content.strip().split("\n")[0]
                        if first_line.startswith("# "):
                            parts = summary_content.split("\n", 1)
                            if len(parts) > 1:
                                summary_content = parts[1].strip()

                        with open(dest_path, "w", encoding="utf-8") as f:
                            f.write(front_matter + summary_content)

                        self.console.print(f"📄 Copied {lang.upper()} summary to GitHub Pages: {dest_path}\n")
                    except Exception as e:
                        self.console.print(f"[yellow]⚠️  Failed to copy {lang.upper()} summary to docs/: {e}[/yellow]\n")

                # Send email if configured
                if send_notifications and self.email_manager and self.config.email and self.config.email.enabled:
                    self.console.print(f"📧 Sending {lang.upper()} email summary...")
                    subscribers = self.storage.load_subscribers()
                    subject = f"Horizon Summary ({lang.upper()}) - {today}"
                    self.email_manager.send_daily_summary(summary, subject, subscribers)

                # Send webhook notification if configured
                if send_notifications and self.webhook_notifier:
                    await self.webhook_notifier.send_daily_summary(
                        summary=push_summary,
                        important_items=daily_push_items,
                        all_items_count=len(all_items),
                        date=today,
                        lang=lang,
                        summarizer=summarizer,
                    )

            self.console.print("[bold green]✅ Horizon completed successfully![/bold green]")
            usage = get_usage_snapshot()
            if usage.total_tokens > 0:
                self.console.print(
                    f"\n🧮 Token usage this run: "
                    f"{usage.total_tokens} tokens "
                    f"(input: {usage.total_input_tokens}, output: {usage.total_output_tokens})"
                )
                for provider, u in sorted(usage.per_provider.items()):
                    if u.total <= 0:
                        continue
                    self.console.print(
                        f"   • {provider}: {u.total} tokens "
                        f"(in: {u.input_tokens}, out: {u.output_tokens})"
                    )
                if usage.per_stage:
                    self.console.print("   By stage:")
                    for stage, u in sorted(usage.per_stage.items()):
                        if u.total <= 0:
                            continue
                        self.console.print(
                            f"   • {stage}: {u.total} tokens "
                            f"(in: {u.input_tokens}, out: {u.output_tokens})"
                        )

        except Exception as e:
            self.console.print(f"[bold red]❌ Error: {e}[/bold red]")

            # Send webhook failure notification if configured
            if send_notifications and self.webhook_notifier:
                await self.webhook_notifier.send_failure(
                    date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    error_message=str(e),
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
        web_ui_updated = await self._write_web_ui(
            all_items=published_items,
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
        def normalize_url(url: str) -> str:
            parsed = urlparse(str(url))
            # Strip www prefix, trailing slashes, and fragments
            host = parsed.hostname or ""
            if host.startswith("www."):
                host = host[4:]
            path = parsed.path.rstrip("/")
            return f"{host}{path}"

        # Group by normalized URL
        url_groups: Dict[str, List[ContentItem]] = {}
        for item in items:
            key = normalize_url(str(item.url))
            url_groups.setdefault(key, []).append(item)

        merged = []
        for key, group in url_groups.items():
            if len(group) == 1:
                merged.append(group[0])
                continue

            # Pick the item with the richest content as primary
            primary = max(group, key=lambda x: len(x.content or ""))

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
        analyzer = ContentAnalyzer(ai_client, cache=self._analysis_cache())
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
                item.ai_reason = "Personal-only item skipped AI analysis"
                item.ai_summary = item.ai_summary or item.content or item.title
                item.ai_summary_zh = item.ai_summary_zh or item.ai_summary
                item.ai_channel = item.ai_channel or channel
                item.ai_topics = item.ai_topics or topics
                item.ai_category = item.ai_category or channel
                item.ai_tags = item.ai_tags or topics
                item.ai_signal_strength = item.ai_signal_strength or "thin"
                item.ai_signal_type = item.ai_signal_type or "personal_update"
                item.ai_is_featured = False
                item.metadata["show_in_personal_feed"] = True
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
            item.ai_reason = item.ai_reason or "AI scoring is disabled for this run."
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
            item.ai_action_suggestion = (
                item.ai_action_suggestion or "打开原文后自行判断是否需要跟进。"
            )
            item.metadata["scoring_disabled"] = True
            if item.metadata.get("analysis_mode") == "personal_only":
                item.metadata["show_in_personal_feed"] = True
            published.append(item)
        return published

    def _analysis_cache(self) -> AnalysisCache:
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
        analyzer = ContentAnalyzer(ai_client, cache=self._analysis_cache())

        return await analyzer.analyze_batch(items)

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
