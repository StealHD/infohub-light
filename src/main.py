"""CLI entry point for Horizon."""

import argparse
import asyncio
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

from .logging_utils import configure_logging
from .storage.manager import ConfigError, StorageManager
from .orchestrator import HorizonOrchestrator
from .services.source_update import run_source_update
from .services.operation_log import safe_emit_operation_event


console = Console()


def print_banner():
    """Print the application banner."""
    banner = r"""
[bold blue]
  _    _            _
 | |  | |          (_)
 | |__| | ___  _ __ _ ___  ___  _ __
 |  __  |/ _ \| '__| |_  / / _ \| '_ \
 | |  | | (_) | |  | |/ / | (_) | | | |
 |_|  |_|\___/|_|  |_/___| \___/|_| |_|
[/bold blue]
[cyan]  AI-Driven Information Aggregation System[/cyan]
    """
    console.print(banner)


def main():
    """Main CLI entry point."""
    load_dotenv()
    configure_logging(service="cli")
    print_banner()

    parser = argparse.ArgumentParser(description="Horizon - AI-Driven Information Aggregation System")
    parser.add_argument("--hours", type=int, help="Force fetch from last N hours")
    parser.add_argument(
        "--source",
        help="Immediately update one source, e.g. rss:0, github:1, apify_social:0, or hackernews",
    )
    args = parser.parse_args()
    started_at = time.monotonic()
    operation_action = (
        "legacy_cli_source_update" if args.source else "legacy_cli_run"
    )

    try:
        # Ensure we're in the project directory or use data/ in current dir
        data_dir = Path("data")

        # Initialize storage manager
        storage = StorageManager(data_dir=str(data_dir))

        # Load configuration
        try:
            config = storage.load_config()
        except FileNotFoundError:
            safe_emit_operation_event(
                category="acquisition",
                action=operation_action,
                outcome="failed",
                level="error",
                error_code="configuration_missing",
                duration_ms=int((time.monotonic() - started_at) * 1000),
            )
            console.print("[bold red]❌ Configuration file not found![/bold red]\n")
            data_dir_path = data_dir if isinstance(data_dir, Path) else Path(data_dir)
            example_path = data_dir_path / "config.example.json"
            if example_path.exists():
                console.print(
                    f"Copy the example config and edit it:\n"
                    f"  [cyan]cp {example_path} {data_dir_path / 'config.json'}[/cyan]\n"
                )
            console.print(
                "Or run [bold cyan]uv run horizon-wizard[/bold cyan] to launch the interactive setup wizard.\n"
            )
            sys.exit(1)
        except ConfigError as e:
            safe_emit_operation_event(
                category="acquisition",
                action=operation_action,
                outcome="failed",
                level="error",
                error_code="configuration_invalid",
                duration_ms=int((time.monotonic() - started_at) * 1000),
            )
            console.print(f"[bold red]❌ Error loading configuration: {e}[/bold red]")
            sys.exit(1)
        except Exception as e:
            safe_emit_operation_event(
                category="acquisition",
                action=operation_action,
                outcome="failed",
                level="error",
                error_code="configuration_load_failed",
                duration_ms=int((time.monotonic() - started_at) * 1000),
            )
            console.print(f"[bold red]❌ Error loading configuration: {e}[/bold red]")
            sys.exit(1)

        if args.source:
            hours = args.hours or config.filtering.time_window_hours
            result = run_source_update(
                data_dir=data_dir,
                source_type=args.source,
                index=None,
                hours=hours,
            )
            safe_emit_operation_event(
                category="acquisition",
                action=operation_action,
                outcome="succeeded",
                duration_ms=int((time.monotonic() - started_at) * 1000),
            )
            console.print(f"[bold green]✅ Source update completed:[/bold green] {result}")
            return

        # Create and run orchestrator
        orchestrator = HorizonOrchestrator(config, storage)
        asyncio.run(orchestrator.run(force_hours=args.hours))
        safe_emit_operation_event(
            category="acquisition",
            action=operation_action,
            outcome="succeeded",
            duration_ms=int((time.monotonic() - started_at) * 1000),
        )

    except KeyboardInterrupt:
        safe_emit_operation_event(
            category="acquisition",
            action=operation_action,
            outcome="cancelled",
            level="warning",
            duration_ms=int((time.monotonic() - started_at) * 1000),
        )
        console.print("\n[yellow]⚠️  Interrupted by user[/yellow]")
        sys.exit(0)
    except Exception as e:
        safe_emit_operation_event(
            category="acquisition",
            action=operation_action,
            outcome="failed",
            level="error",
            error_code=(
                "legacy_source_update_failed"
                if args.source
                else "legacy_run_failed"
            ),
            duration_ms=int((time.monotonic() - started_at) * 1000),
        )
        console.print(f"\n[bold red]❌ Fatal error: {e}[/bold red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def print_config_template():
    """Print configuration template."""
    template = """
{
  "version": "1.0",
  "ai": {
    "provider": "anthropic",
    "model": "claude-sonnet-4.5-20250929",
    "api_key_env": "ANTHROPIC_API_KEY",
    "temperature": 0.3,
    "max_tokens": 4096
  },
  "sources": {
    "github": [
      {
        "type": "user_events",
        "username": "torvalds",
        "enabled": true
      }
    ],
    "hackernews": {
      "enabled": true,
      "fetch_top_stories": 30,
      "min_score": 100
    },
    "rss": [
      {
        "name": "Example Blog",
        "url": "https://example.com/feed.xml",
        "enabled": true,
        "category": "software-engineering"
      }
    ]
  },
  "filtering": {
    "ai_score_threshold": 7.0,
    "time_window_hours": 24
  }
}

Also create a .env file with:
ANTHROPIC_API_KEY=your_api_key_here
GITHUB_TOKEN=your_github_token_here (optional but recommended)
"""
    console.print(template)


if __name__ == "__main__":
    main()
