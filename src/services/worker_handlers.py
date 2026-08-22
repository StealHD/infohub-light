"""Explicit Worker job handler registry for source and Feed work."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..rsshub import DEFAULT_RSSHUB_BASE_URL, is_managed_rsshub_config
from ..storage.manager import StorageManager
from ..storage.service_store import ServiceStore
from .source_acquisition import SourceAcquisitionCoordinator
from .source_type_registry import build_source_payload
from .usage_attempt_meter import UsageAttemptMeter


class PaidCanaryUnavailableError(RuntimeError):
    """Legacy-only error retained for the offline v1 Canary handler."""

    code = "apify_actor_routing_disabled"
    retryable = False


class PaidCanaryAuthorizationError(RuntimeError):
    """Legacy-only error retained for the offline v1 Canary handler."""

    code = "apify_actor_canary_unavailable"
    retryable = False


class RetiredActorOpsV1CanaryError(RuntimeError):
    code = "actorops_v1_retired"
    retryable = False


@dataclass(frozen=True, slots=True)
class WorkerHandlerPorts:
    actor_handlers: dict[str, Callable[..., dict[str, Any]]]
    run_user_feed_refresh: Callable[..., dict[str, Any]]
    run_source_test: Callable[..., dict[str, Any]]
    apify_coordinator: Callable[..., Any]
    shared_acquisition_enabled: Callable[[], bool]


def source_payload_from_catalog(
    job: dict[str, Any],
    *,
    store: ServiceStore,
) -> dict[str, Any]:
    payload = dict(job.get("payload_json") or {})
    if not job.get("source_id"):
        return payload
    source = store.get_source(str(job["source_id"]))
    if not source:
        return payload
    managed_rsshub = bool(
        source.get("type") == "rss"
        and is_managed_rsshub_config(source.get("config"))
    )
    rsshub_base_url = DEFAULT_RSSHUB_BASE_URL
    if managed_rsshub:
        rsshub_base_url = StorageManager(
            data_dir=str(store.data_dir)
        ).load_config().rsshub.base_url
    canonical = build_source_payload(source, rsshub_base_url=rsshub_base_url)
    for reserved in (
        "reason",
        "apify_actor_candidate_id",
        "apify_actor_route_generation",
    ):
        canonical.pop(reserved, None)
    if source.get("type") == "rss":
        if managed_rsshub:
            canonical["enforce_public_network"] = False
        else:
            owner = store.get_user(str(source.get("owner_user_id") or ""))
            canonical["enforce_public_network"] = bool(
                source.get("enforce_public_network")
            ) or not (owner and owner.get("role") in {"owner", "admin"})
    runtime = {
        key: value
        for key, value in payload.items()
        if key
        in {
            "hours",
            "reason",
            "apify_actor_candidate_id",
            "apify_actor_route_generation",
        }
    }
    return {**canonical, **runtime}


def _run_source_test_job(
    job: dict[str, Any],
    payload: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
    ports: WorkerHandlerPorts,
) -> dict[str, Any]:
    raw_payload = (
        job.get("payload_json")
        if isinstance(job.get("payload_json"), dict)
        else {}
    )
    meter = UsageAttemptMeter(
        store,
        workspace_id=job["workspace_id"],
        user_id=job["user_id"],
        job_id=job["id"],
    )

    def run_metered_test() -> dict[str, Any]:
        if raw_payload.get("reason") == "apify_actor_canary":
            raise RetiredActorOpsV1CanaryError(
                "ActorOps v1 Canary source tests are retired"
            )
        meter.before_fetch_attempt(
            provider=str(payload.get("source_type") or "unknown"),
            source_id=str(job.get("source_id") or ""),
        )
        coordinator = ports.apify_coordinator(
            store,
            workspace_id=str(job["workspace_id"]),
            data_dir=data_dir,
        )
        if coordinator is not None:
            return ports.run_source_test(payload, apify_coordinator=coordinator)
        return ports.run_source_test(payload)

    if ports.shared_acquisition_enabled() and job.get("source_id"):
        return SourceAcquisitionCoordinator(
            store,
            workspace_id=job["workspace_id"],
            user_id=job["user_id"],
            job_id=job["id"],
        ).run_probe(source=payload, call=run_metered_test)
    return run_metered_test()


def _run_source_fetch(
    job: dict[str, Any],
    payload: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
    ports: WorkerHandlerPorts,
) -> dict[str, Any]:
    if job.get("source_id"):
        from .catalog_source_runner import run_catalog_source_fetch

        return run_catalog_source_fetch(
            job,
            data_dir=data_dir,
            store=store,
            commit=False,
        )
    if not payload.get("source_type"):
        return ports.run_user_feed_refresh(job, data_dir=data_dir, store=store)
    raise ValueError("service source_fetch requires a catalog source_id")


def run_job(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
    ports: WorkerHandlerPorts,
) -> dict[str, Any]:
    job_type = str(job["job_type"])
    actor_handler = ports.actor_handlers.get(job_type)
    if actor_handler is not None:
        return actor_handler(job, data_dir=data_dir, store=store)
    payload = source_payload_from_catalog(job, store=store)
    if job_type == "source_test":
        return _run_source_test_job(
            job,
            payload,
            data_dir=data_dir,
            store=store,
            ports=ports,
        )
    if job_type == "source_fetch":
        return _run_source_fetch(
            job,
            payload,
            data_dir=data_dir,
            store=store,
            ports=ports,
        )
    if job_type == "user_feed_refresh":
        return ports.run_user_feed_refresh(job, data_dir=data_dir, store=store)
    if job_type == "content_repair":
        from .content_repair import repair_existing_content

        return repair_existing_content(job, data_dir=data_dir, store=store)
    raise ValueError(f"unsupported job_type: {job_type}")
