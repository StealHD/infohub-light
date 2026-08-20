#!/usr/bin/env python3
"""Inspect, reconcile, or retire the unpublished Actor auto-pool workflow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.services.apify_actor_auto_pool_reconcile import (  # noqa: E402
    reconcile_retirement,
)
from src.services.apify_actor_auto_pool_retirement import (  # noqa: E402
    apply_retirement,
    inspect_retirement,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline retirement tool for historical Actor auto-pool work"
    )
    parser.add_argument(
        "--data-dir", type=Path, default=REPOSITORY_ROOT / "data"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("inspect")
    reconcile = commands.add_parser("reconcile")
    reconcile.add_argument("--limit", type=int, default=20)
    reconcile.add_argument("--confirm-worker-stopped", action="store_true")
    apply = commands.add_parser("apply")
    apply.add_argument("--backup-dir", type=Path)
    apply.add_argument("--confirm-api-stopped", action="store_true")
    apply.add_argument("--confirm-worker-stopped", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            result = inspect_retirement(args.data_dir)
        elif args.command == "reconcile":
            result = reconcile_retirement(
                args.data_dir,
                limit=args.limit,
                confirm_worker_stopped=bool(args.confirm_worker_stopped),
            )
        else:
            result = apply_retirement(
                args.data_dir,
                backup_dir=args.backup_dir or args.data_dir / "backups",
                confirm_api_stopped=bool(args.confirm_api_stopped),
                confirm_worker_stopped=bool(args.confirm_worker_stopped),
            )
    except RuntimeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, "result": result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
