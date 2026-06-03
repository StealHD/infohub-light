"""CLI for printing direct source endpoint registry."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from ..storage.manager import ConfigError, StorageManager
from .source_registry import build_direct_source_registry


console = Console()


def _load_config_or_none(data_dir: str):
    try:
        return StorageManager(data_dir=data_dir).load_config()
    except (FileNotFoundError, ConfigError):
        return None


def main() -> None:
    """Print direct source endpoint registry."""
    parser = argparse.ArgumentParser(
        description="Show Horizon direct source endpoints and adapters",
    )
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    load_dotenv()
    config = _load_config_or_none(args.data_dir)
    endpoints = build_direct_source_registry(config)

    if args.json:
        json.dump(
            [endpoint.__dict__ for endpoint in endpoints],
            sys.stdout,
            ensure_ascii=False,
            indent=2,
        )
        sys.stdout.write("\n")
        return

    title = "Direct Source Endpoints"
    if config is None:
        title += " (generic patterns; config not loaded)"
    else:
        title += f" ({Path(args.data_dir) / 'config.json'})"

    table = Table(title=title)
    table.add_column("Source", style="cyan", no_wrap=True)
    table.add_column("Adapter", style="green")
    table.add_column("Endpoint")
    table.add_column("Auth")
    table.add_column("Notes")

    for endpoint in endpoints:
        table.add_row(
            endpoint.source,
            endpoint.adapter,
            endpoint.endpoint,
            endpoint.auth,
            endpoint.notes,
        )

    console.print(table)


if __name__ == "__main__":
    main()
