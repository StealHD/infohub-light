#!/usr/bin/env python3
"""Prepare a local Inteliscope + OpenClaw browser chat and read-only MCP setup."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

# Keep the historical executable entrypoint working from any current directory.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.openclaw_setup_compose import (
    compose_file as _compose_file,
    compose_image_from_ps,
    resolve_compose_image as _resolve_compose_image,
)
from scripts.openclaw_setup_env import (
    ENV_ASSIGNMENT,
    MANAGED_COMMENT,
    MANAGED_ENV_VALUES,
    default_origin,
    managed_updates as _managed_updates,
    parse_env_values,
    update_env_text,
    write_env_atomic,
)
from scripts.openclaw_setup_gateway import (
    GatewayInfo,
    merge_allowed_origins,
    parse_gateway_status,
    wait_for_ready as _wait_for_ready,
)
from scripts.openclaw_setup_mcp import (
    FULL_TOOL_FILTER,
    LEGACY_FULL_TOOL_FILTER,
    LEGACY_READ_TOOL_FILTER,
    READ_TOOL_FILTER,
    standard_tool_filter_upgrade,
)
from scripts.openclaw_setup_process import CommandRunner, json_output as _json_output
from scripts.openclaw_setup_skill import skill_tree_matches
from scripts.openclaw_setup_validation import (
    TARGET_OPENCLAW_VERSION,
    SetupError,
    validate_gateway_url,
    validate_origin,
    version_tuple as _version_tuple,
)
from scripts.openclaw_setup_workflow import run_setup


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect and print planned mutations only.",
    )
    parser.add_argument(
        "--origin",
        help="Exact Inteliscope browser Origin; defaults from HORIZON_WEB_PORT.",
    )
    parser.add_argument(
        "--gateway-url",
        help="Override the Gateway URL reported by OpenClaw.",
    )
    parser.add_argument("--env-file", help="Path to the Inteliscope .env file.")
    parser.add_argument("--project-root", default=str(ROOT), help=argparse.SUPPRESS)
    parser.add_argument(
        "--skip-skill",
        action="store_true",
        help="Do not install the bundled Inteliscope Skill.",
    )
    parser.add_argument(
        "--skip-service",
        action="store_true",
        help="Do not start/recreate Docker services.",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Rebuild the current workspace with up-latest.sh.",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open the /agents page after setup.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Readiness timeout in seconds (default: 120).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.timeout < 1:
        parser.error("--timeout must be at least 1 second")
    try:
        run_setup(args)
    except SetupError as exc:
        print(f"OpenClaw setup failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
