"""Legacy CLI/static publisher kept outside the user-scoped service pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from ..ai.summarizer import DailySummarizer
from ..ai.tokens import get_usage_snapshot, token_stage
from .feed_run import FeedRunResult

if TYPE_CHECKING:
    from ..orchestrator import HorizonOrchestrator


class LegacyPublisher:
    """Own static files, summaries, graph persistence, email, and webhooks."""

    def __init__(self, orchestrator: "HorizonOrchestrator") -> None:
        self.orchestrator = orchestrator

    def prepare(self) -> None:
        owner = self.orchestrator
        if (
            owner.email_manager
            and owner.config.email
            and owner.config.email.enabled
            and owner.config.email.imap_enabled
        ):
            owner.console.print("📧 Checking for new email subscriptions...")
            owner.email_manager.check_subscriptions(owner.storage)

    async def write_web_ui(self, *, items, today: str, total_fetched: int) -> bool:
        return await self.orchestrator._write_web_ui(
            all_items=list(items),
            today=today,
            total_fetched=total_fetched,
        )

    async def publish(
        self,
        result: FeedRunResult,
        *,
        send_notifications: bool,
        write_summaries: bool,
    ) -> None:
        owner = self.orchestrator
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if result.status == "failed":
            message = "; ".join(issue.message for issue in result.issues) or "legacy feed run failed"
            raise RuntimeError(message)

        items = list(result.items)
        if not items:
            owner.console.print("[yellow]No new content found. Exiting.[/yellow]")
            return
        total_fetched = sum(outcome.fetched_count for outcome in result.source_outcomes) or len(items)
        await self.write_web_ui(items=items, today=today, total_fetched=total_fetched)

        if not owner._ai_enabled():
            owner.console.print(
                "[dim]AI scoring disabled; skipped scoring, enrichment, summaries, notifications, and article graph.[/dim]\n"
            )
            owner.console.print("[bold green]✅ Horizon completed successfully![/bold green]")
            return

        await owner._run_article_graph_pipeline(items)
        by_id = {item.id: item for item in items}
        important_items = [by_id[item_id] for item_id in result.featured_item_ids if item_id in by_id]
        daily_push_items = [by_id[item_id] for item_id in result.daily_push_item_ids if item_id in by_id]

        if not write_summaries and not send_notifications:
            owner.console.print("[dim]Skipping daily summary and notifications for incremental poll.[/dim]\n")
            owner.console.print("[bold green]✅ Horizon completed successfully![/bold green]")
            return

        for lang in owner.config.ai.languages:
            summarizer = DailySummarizer()
            with token_stage("summary"):
                summary = await summarizer.generate_summary(
                    important_items,
                    today,
                    total_fetched,
                    language=lang,
                )
                push_summary = await summarizer.generate_summary(
                    daily_push_items,
                    today,
                    total_fetched,
                    language=lang,
                )

            if write_summaries:
                summary_path = owner.storage.save_daily_summary(today, summary, language=lang)
                owner.console.print(f"💾 Saved {lang.upper()} summary to: {summary_path}\n")
                self._write_github_pages_summary(today=today, lang=lang, summary=summary)

            if send_notifications and owner.email_manager and owner.config.email and owner.config.email.enabled:
                owner.console.print(f"📧 Sending {lang.upper()} email summary...")
                subscribers = owner.storage.load_subscribers()
                subject = f"Horizon Summary ({lang.upper()}) - {today}"
                owner.email_manager.send_daily_summary(summary, subject, subscribers)

            if send_notifications and owner.webhook_notifier:
                await owner.webhook_notifier.send_daily_summary(
                    summary=push_summary,
                    important_items=daily_push_items,
                    all_items_count=total_fetched,
                    date=today,
                    lang=lang,
                    summarizer=summarizer,
                )

        owner.console.print("[bold green]✅ Horizon completed successfully![/bold green]")
        self._print_token_usage()

    async def notify_failure(self, error: Exception, *, send_notifications: bool) -> None:
        owner = self.orchestrator
        if send_notifications and owner.webhook_notifier:
            await owner.webhook_notifier.send_failure(
                date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                error_message=str(error),
            )

    def _write_github_pages_summary(self, *, today: str, lang: str, summary: str) -> None:
        owner = self.orchestrator
        try:
            posts_dir = Path("docs/_posts")
            posts_dir.mkdir(parents=True, exist_ok=True)
            destination = posts_dir / f"{today}-summary-{lang}.md"
            front_matter = (
                "---\n"
                "layout: default\n"
                f'title: "Horizon Summary: {today} ({lang.upper()})"\n'
                f"date: {today}\n"
                f"lang: {lang}\n"
                "---\n\n"
            )
            content = summary
            if content.strip().split("\n")[0].startswith("# "):
                parts = content.split("\n", 1)
                if len(parts) > 1:
                    content = parts[1].strip()
            destination.write_text(front_matter + content, encoding="utf-8")
            owner.console.print(
                f"📄 Copied {lang.upper()} summary to GitHub Pages: {destination}\n"
            )
        except Exception as exc:
            owner.console.print(
                f"[yellow]⚠️  Failed to copy {lang.upper()} summary to docs/: {exc}[/yellow]\n"
            )

    def _print_token_usage(self) -> None:
        usage = get_usage_snapshot()
        if usage.total_tokens <= 0:
            return
        console = self.orchestrator.console
        console.print(
            f"\n🧮 Token usage this run: {usage.total_tokens} tokens "
            f"(input: {usage.total_input_tokens}, output: {usage.total_output_tokens})"
        )
        for provider, provider_usage in sorted(usage.per_provider.items()):
            if provider_usage.total > 0:
                console.print(
                    f"   • {provider}: {provider_usage.total} tokens "
                    f"(in: {provider_usage.input_tokens}, out: {provider_usage.output_tokens})"
                )
        if usage.per_stage:
            console.print("   By stage:")
            for stage, stage_usage in sorted(usage.per_stage.items()):
                if stage_usage.total > 0:
                    console.print(
                        f"   • {stage}: {stage_usage.total} tokens "
                        f"(in: {stage_usage.input_tokens}, out: {stage_usage.output_tokens})"
                    )
