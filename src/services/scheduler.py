"""Daily scheduler for Docker Compose deployments."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from rich.console import Console

from ..logging_utils import configure_logging
from ..orchestrator import HorizonOrchestrator
from ..storage.manager import ConfigError, StorageManager
from .daily_push import select_daily_push_items
from .operation_log import safe_emit_operation_event


console = Console()
logger = logging.getLogger(__name__)


def _configure_logging(log_dir: str = "logs") -> None:
    configure_logging(log_dir=log_dir, service="scheduler")


async def run_once(
    hours: int,
    *,
    send_notifications: bool = True,
    write_summaries: bool = True,
    incremental: bool = False,
    enrich: bool = True,
) -> None:
    """Run one Horizon aggregation job."""
    started_at = time.monotonic()
    load_dotenv()
    storage = StorageManager(data_dir="data")
    try:
        config = storage.load_config()
    except FileNotFoundError:
        safe_emit_operation_event(
            category="acquisition",
            action="legacy_scheduler_run",
            outcome="failed",
            level="error",
            error_code="configuration_missing",
            duration_ms=int((time.monotonic() - started_at) * 1000),
        )
        console.print("[bold red]Configuration file not found: data/config.json[/bold red]")
        raise
    except ConfigError as exc:
        safe_emit_operation_event(
            category="acquisition",
            action="legacy_scheduler_run",
            outcome="failed",
            level="error",
            error_code="configuration_invalid",
            duration_ms=int((time.monotonic() - started_at) * 1000),
        )
        console.print(f"[bold red]Configuration error: {exc}[/bold red]")
        raise

    orchestrator = HorizonOrchestrator(config, storage)
    try:
        await orchestrator.run(
            force_hours=hours,
            send_notifications=send_notifications,
            write_summaries=write_summaries,
            incremental=incremental,
            enrich=enrich,
        )
    except Exception as exc:
        safe_emit_operation_event(
            category="acquisition",
            action="legacy_scheduler_run",
            outcome="failed",
            level="error",
            error_code="legacy_run_failed",
            duration_ms=int((time.monotonic() - started_at) * 1000),
        )
        raise
    safe_emit_operation_event(
        category="acquisition",
        action="legacy_scheduler_run",
        outcome="succeeded",
        duration_ms=int((time.monotonic() - started_at) * 1000),
    )


def _parse_hhmm(value: str) -> tuple[int, int]:
    parts = value.split(":", 1)
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("time must be HH:MM")
    hour = int(parts[0])
    minute = int(parts[1])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise argparse.ArgumentTypeError("time must be HH:MM")
    return hour, minute


def _next_run(now: datetime, hour: int, minute: int) -> datetime:
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def _next_poll_run(now: datetime, interval_minutes: int) -> datetime:
    if interval_minutes <= 0:
        raise ValueError("poll interval must be greater than 0 minutes")
    return now + timedelta(minutes=interval_minutes)


async def run_scheduler(
    time_value: str,
    timezone_name: str,
    hours: int,
    run_on_start: bool,
    poll_enabled: bool = False,
    poll_interval_minutes: int = 60,
    poll_hours: int = 2,
) -> None:
    """Run Horizon on a daily schedule, optionally with short polling."""
    hour, minute = _parse_hhmm(time_value)
    tz = ZoneInfo(timezone_name)
    if poll_enabled:
        console.print(
            f"[cyan]Horizon scheduler active: poll every {poll_interval_minutes} min "
            f"(hours={poll_hours}), daily push {time_value} {timezone_name} "
            f"(hours={hours})[/cyan]"
        )
    else:
        console.print(
            f"[cyan]Horizon scheduler active: {time_value} {timezone_name}, hours={hours}[/cyan]"
        )

    if run_on_start:
        logger.info("Running initial scheduled job")
        await run_once(
            poll_hours if poll_enabled else hours,
            send_notifications=not poll_enabled,
            write_summaries=not poll_enabled,
            incremental=poll_enabled,
            enrich=not poll_enabled,
        )

    if poll_enabled:
        next_poll = _next_poll_run(datetime.now(tz), poll_interval_minutes)
        while True:
            now = datetime.now(tz)
            next_daily = _next_run(now, hour, minute)
            target = min(next_daily, next_poll)
            wait_seconds = max((target - now).total_seconds(), 1)
            console.print(
                f"Next Horizon poll: {next_poll.strftime('%Y-%m-%d %H:%M:%S %Z')} · "
                f"daily push: {next_daily.strftime('%Y-%m-%d %H:%M:%S %Z')}"
            )
            await asyncio.sleep(wait_seconds)
            now = datetime.now(tz)
            if now >= next_daily:
                try:
                    logger.info("Starting scheduled daily Horizon job")
                    await run_once(
                        hours,
                        send_notifications=True,
                        write_summaries=True,
                        incremental=False,
                        enrich=True,
                    )
                    logger.info("Scheduled daily Horizon job completed")
                except Exception as exc:
                    logger.exception(
                        "Scheduled daily Horizon job failed error_code=%s",
                        type(exc).__name__,
                    )
                next_poll = _next_poll_run(datetime.now(tz), poll_interval_minutes)
                continue
            if now >= next_poll:
                try:
                    logger.info("Starting scheduled Horizon poll")
                    await run_once(
                        poll_hours,
                        send_notifications=False,
                        write_summaries=False,
                        incremental=True,
                        enrich=False,
                    )
                    logger.info("Scheduled Horizon poll completed")
                except Exception as exc:
                    logger.exception(
                        "Scheduled Horizon poll failed error_code=%s",
                        type(exc).__name__,
                    )
                next_poll = _next_poll_run(datetime.now(tz), poll_interval_minutes)
                continue

    while True:
        now = datetime.now(tz)
        target = _next_run(now, hour, minute)
        wait_seconds = max((target - now).total_seconds(), 1)
        console.print(
            f"Next Horizon run: {target.strftime('%Y-%m-%d %H:%M:%S %Z')}"
        )
        await asyncio.sleep(wait_seconds)
        try:
            logger.info("Starting scheduled Horizon job")
            await run_once(hours)
            logger.info("Scheduled Horizon job completed")
        except Exception as exc:
            logger.exception(
                "Scheduled Horizon job failed error_code=%s",
                type(exc).__name__,
            )


def main() -> None:
    """CLI entry point for horizon-scheduler."""
    load_dotenv()
    parser = argparse.ArgumentParser(description="Run Horizon on a daily schedule")
    parser.add_argument(
        "--time",
        default=os.getenv("HORIZON_DAILY_TIME", "08:30"),
        help="Local run time in HH:MM format",
    )
    parser.add_argument(
        "--timezone",
        default=os.getenv("HORIZON_TIMEZONE", "Asia/Shanghai"),
        help="IANA timezone name",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=int(os.getenv("HORIZON_FETCH_HOURS", "24")),
        help="Fetch time window in hours",
    )
    parser.add_argument(
        "--run-on-start",
        action="store_true",
        default=os.getenv("HORIZON_RUN_ON_START", "").lower() in {"1", "true", "yes"},
        help="Run one aggregation immediately before waiting for the next schedule",
    )
    parser.add_argument(
        "--poll-enabled",
        action="store_true",
        default=os.getenv("HORIZON_POLL_ENABLED", "").lower() in {"1", "true", "yes"},
        help="Run incremental short polling between daily jobs",
    )
    parser.add_argument(
        "--poll-interval-minutes",
        type=int,
        default=int(os.getenv("HORIZON_POLL_INTERVAL_MINUTES", "60")),
        help="Minutes between incremental polls",
    )
    parser.add_argument(
        "--poll-hours",
        type=int,
        default=int(os.getenv("HORIZON_POLL_FETCH_HOURS", "2")),
        help="Fetch window in hours for incremental polls",
    )
    args = parser.parse_args()

    _configure_logging()
    try:
        asyncio.run(
            run_scheduler(
                time_value=args.time,
                timezone_name=args.timezone,
                hours=args.hours,
                run_on_start=args.run_on_start,
                poll_enabled=args.poll_enabled,
                poll_interval_minutes=args.poll_interval_minutes,
                poll_hours=args.poll_hours,
            )
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Scheduler stopped[/yellow]")


if __name__ == "__main__":
    main()
