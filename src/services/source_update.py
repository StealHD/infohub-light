"""Immediate single-source update service."""

from __future__ import annotations

import asyncio
from pathlib import Path

from dotenv import load_dotenv

from ..orchestrator import HorizonOrchestrator
from ..source_selection import filter_config_for_source_ref, parse_source_ref
from ..storage.manager import StorageManager


async def run_source_update_async(
    *,
    data_dir: str | Path,
    source_type: str,
    index: int | None,
    hours: int,
) -> dict[str, object]:
    """Reload config and run one explicitly selected source."""

    load_dotenv()
    if hours < 1 or hours > 720:
        raise ValueError("hours must be between 1 and 720")

    storage = StorageManager(data_dir=str(data_dir))
    config = storage.load_config()
    source_ref = parse_source_ref(source_type, index)
    filtered_config = filter_config_for_source_ref(config, source_ref)
    orchestrator = HorizonOrchestrator(filtered_config, storage)
    return await orchestrator.run_single_source_update(source_ref, force_hours=hours)


def run_source_update(
    *,
    data_dir: str | Path,
    source_type: str,
    index: int | None,
    hours: int,
) -> dict[str, object]:
    """Synchronous wrapper for the local HTTP server."""

    return asyncio.run(
        run_source_update_async(
            data_dir=data_dir,
            source_type=source_type,
            index=index,
            hours=hours,
        )
    )
