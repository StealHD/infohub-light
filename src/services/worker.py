"""Worker loop for queued InfoHub service jobs."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from ..ui.server import run_source_test
from .job_queue import JobQueue
from .source_type_registry import build_source_payload
from .user_feed_store import UserFeedStore
from ..storage.service_store import ServiceStore


def _source_payload_from_catalog(
    job: dict[str, Any],
    *,
    store: ServiceStore,
) -> dict[str, Any]:
    payload = dict(job.get("payload_json") or {})
    if payload.get("source_type") or not job.get("source_id"):
        return payload
    source = store.get_source(str(job["source_id"]))
    if not source:
        return payload

    return {**build_source_payload(source), **payload}


def _run_user_feed_refresh(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
) -> dict[str, Any]:
    import asyncio

    from ..orchestrator import HorizonOrchestrator
    from ..storage.manager import StorageManager
    from .user_config_builder import build_user_config

    storage = StorageManager(data_dir=data_dir)
    base_config = storage.load_config()
    config = build_user_config(
        store=store,
        workspace_id=job["workspace_id"],
        user_id=job["user_id"],
        base_config=base_config,
    )
    orchestrator = HorizonOrchestrator(config, storage)
    asyncio.run(
        orchestrator.run(
            force_hours=int((job.get("payload_json") or {}).get("hours") or config.filtering.time_window_hours),
            send_notifications=False,
            write_summaries=False,
            incremental=True,
            enrich=False,
        )
    )
    payload_path = Path(data_dir) / "site" / "radar-data.json"
    if payload_path.exists():
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    else:
        payload = {"items": [], "generated_at": ""}
    snapshot = UserFeedStore(store).save_snapshot(
        workspace_id=job["workspace_id"],
        user_id=job["user_id"],
        job_id=job["id"],
        payload=payload,
    )
    return {
        "ok": True,
        "job_type": "user_feed_refresh",
        "snapshot_id": snapshot["id"],
        "item_count": snapshot["item_count"],
    }


def _run_job(job: dict[str, Any], *, data_dir: str, store: ServiceStore) -> dict[str, Any]:
    payload = _source_payload_from_catalog(job, store=store)
    job_type = job["job_type"]

    if job_type == "source_test":
        return run_source_test(payload)

    if job_type == "source_fetch":
        if job.get("source_id"):
            from .catalog_source_runner import run_catalog_source_fetch

            return run_catalog_source_fetch(job, data_dir=data_dir, store=store)
        if not payload.get("source_type"):
            return _run_user_feed_refresh(job, data_dir=data_dir, store=store)
        from .source_update import run_source_update

        source_type = str(payload.get("source_type") or "")
        if not source_type:
            raise ValueError("source_fetch payload requires source_type")
        return run_source_update(
            data_dir=data_dir,
            source_type=source_type,
            index=payload.get("index"),
            hours=int(payload.get("hours") or 24),
        )

    if job_type == "user_feed_refresh":
        return _run_user_feed_refresh(job, data_dir=data_dir, store=store)

    raise ValueError(f"unsupported job_type: {job_type}")


def run_worker_once(
    *,
    data_dir: str = "data",
    worker_id: str = "horizon-worker",
    lease_seconds: float | None = None,
    retry_base_seconds: float | None = None,
) -> dict[str, Any] | None:
    store = ServiceStore(data_dir)
    store.initialize()
    queue = JobQueue(store)
    lease = float(lease_seconds if lease_seconds is not None else os.getenv("HORIZON_WORKER_LEASE_SECONDS", "900"))
    retry_base = float(
        retry_base_seconds
        if retry_base_seconds is not None
        else os.getenv("HORIZON_WORKER_RETRY_BASE_SECONDS", "30")
    )
    queue.requeue_stale_running_jobs()
    queue.prune_terminal_jobs()
    job = queue.claim_next_job(worker_id=worker_id, lease_seconds=lease)
    if not job:
        return None
    try:
        result = _run_job(job, data_dir=data_dir, store=store)
    except Exception as exc:
        return queue.fail_or_retry_job(
            job["id"],
            error_code=type(exc).__name__,
            error_message=str(exc),
            retryable=True,
            retry_base_seconds=retry_base,
        )
    return queue.complete_job(job["id"], status="succeeded", result=result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run InfoHub queued jobs")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--worker-id", default=os.getenv("HORIZON_WORKER_ID", "horizon-worker"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=float(os.getenv("HORIZON_WORKER_POLL_SECONDS", "5")))
    parser.add_argument("--lease-seconds", type=float, default=float(os.getenv("HORIZON_WORKER_LEASE_SECONDS", "900")))
    parser.add_argument(
        "--retry-base-seconds",
        type=float,
        default=float(os.getenv("HORIZON_WORKER_RETRY_BASE_SECONDS", "30")),
    )
    args = parser.parse_args()

    load_dotenv()
    if args.once:
        run_worker_once(
            data_dir=args.data_dir,
            worker_id=args.worker_id,
            lease_seconds=args.lease_seconds,
            retry_base_seconds=args.retry_base_seconds,
        )
        return

    while True:
        run_worker_once(
            data_dir=args.data_dir,
            worker_id=args.worker_id,
            lease_seconds=args.lease_seconds,
            retry_base_seconds=args.retry_base_seconds,
        )
        time.sleep(max(args.poll_seconds, 0.5))


if __name__ == "__main__":
    main()
