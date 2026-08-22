"""ActorOps runtime projection and free provisioning for YouTube channels."""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from ..storage.service_store import ServiceStore
from .actorops.binding_service import ActorOpsBindingService
from .actorops.repository import ActorOpsRepository
from .job_queue import JobQueue
from .source_type_registry import is_youtube_channel_config


YOUTUBE_ROUTE_KEY = "youtube/channel/items"
_DISCOVERY_COOLDOWN = timedelta(hours=24)


def is_youtube_channel_record(record: dict[str, Any]) -> bool:
    """Return whether one catalog record is an official YouTube channel feed."""

    return bool(
        str(record.get("type") or "") == "rss"
        and is_youtube_channel_config(record.get("config"))
    )


def project_youtube_actor_runtime_record(
    record: dict[str, Any],
    *,
    route_id: str,
) -> dict[str, Any]:
    """Convert one catalog YouTube RSS identity into a routed Actor runtime row."""

    config = record.get("config") if isinstance(record.get("config"), dict) else {}
    target = str(config.get("url") or "").strip()
    if not target:
        raise ValueError("YouTube Actor runtime requires a canonical channel feed")
    runtime_config = {
        "profile_id": str(route_id),
        "platform": "youtube",
        "kind": "channel",
        "target": target,
        "fetch_limit": int(config.get("fetch_limit") or 20),
        "enabled": True,
        "analysis_mode": str(config.get("analysis_mode") or "full"),
    }
    projected = dict(record)
    projected["type"] = "apify_social"
    projected["config"] = runtime_config
    return projected


def provision_youtube_actor_sources(store: ServiceStore) -> dict[str, int]:
    """Ensure pending v2 bindings and queue only v2 Discovery jobs."""

    connection = store.connect()
    rows = connection.execute(
        """SELECT DISTINCT source.id, source.workspace_id, source.config_json
           FROM source_catalog AS source
           JOIN user_subscriptions AS subscription
             ON subscription.source_id=source.id AND subscription.enabled=1
           WHERE source.type='rss'
           ORDER BY source.workspace_id, source.id"""
    ).fetchall()
    bound = discoveries = skipped = 0
    now = datetime.now(timezone.utc)
    for row in rows:
        try:
            config = json.loads(str(row["config_json"] or "{}"))
        except json.JSONDecodeError:
            skipped += 1
            continue
        if not is_youtube_channel_record({"type": "rss", "config": config}):
            continue
        workspace_id = str(row["workspace_id"])
        source_id = str(row["id"])
        existed = connection.execute(
            """SELECT 1 FROM actor_source_bindings_v2
               WHERE workspace_id=? AND source_id=?""",
            (workspace_id, source_id),
        ).fetchone() is not None
        binding = ActorOpsBindingService(
            store, workspace_id=workspace_id
        ).ensure(source_id)
        bound += int(not existed)
        repository = ActorOpsRepository(connection, workspace_id)
        selectable = connection.execute(
            """SELECT 1 FROM actor_candidates_v2
               WHERE workspace_id=? AND route_id=?
                 AND assignment_role IN ('active','standby')
                 AND lifecycle IN ('probationary','certified')
               LIMIT 1""",
            (workspace_id, binding.route_id),
        ).fetchone()
        if selectable is not None:
            continue
        recent = connection.execute(
            """SELECT updated_at FROM actor_discovery_jobs_v2
               WHERE workspace_id=? AND route_id=?
               ORDER BY updated_at DESC, discovery_id DESC LIMIT 1""",
            (workspace_id, binding.route_id),
        ).fetchone()
        if recent is not None and _utc(str(recent["updated_at"])) >= (
            now - _DISCOVERY_COOLDOWN
        ):
            continue
        operator_id = _operator(connection, workspace_id)
        if operator_id is None:
            skipped += 1
            continue
        bucket = now.strftime("%Y%m%d")
        key = _hash("youtube_source_provisioning", binding.route_id, bucket)
        discovery_id = f"youtube-provisioning-{key[:24]}"
        try:
            with repository.transaction():
                discovery, _created = repository.discovery.ensure(
                    discovery_id=discovery_id,
                    idempotency_key=key,
                    route_id=binding.route_id,
                    trigger_reason="youtube_source_provisioning",
                    input_fingerprint=_hash(YOUTUBE_ROUTE_KEY),
                )
                if _active_job(
                    connection, workspace_id, str(discovery["discovery_id"])
                ):
                    continue
                JobQueue(store).create_job(
                    workspace_id=workspace_id,
                    user_id=operator_id,
                    job_type="actorops_v2_discovery",
                    payload={"discovery_id": str(discovery["discovery_id"])},
                    priority=50,
                    max_attempts=1,
                    retention_days=14,
                    commit=False,
                )
                discoveries += 1
        except Exception:
            skipped += 1
    return {"bound": bound, "discoveries": discoveries, "skipped": skipped}


def _active_job(
    connection: Any, workspace_id: str, discovery_id: str
) -> bool:
    return connection.execute(
        """SELECT 1 FROM fetch_jobs
           WHERE workspace_id=? AND job_type='actorops_v2_discovery'
             AND status IN ('queued','running')
             AND json_extract(payload_json, '$.discovery_id')=?
           LIMIT 1""",
        (workspace_id, discovery_id),
    ).fetchone() is not None


def _operator(connection: Any, workspace_id: str) -> str | None:
    row = connection.execute(
        """SELECT id FROM users WHERE workspace_id=? AND enabled=1
           AND role IN ('owner','admin')
           ORDER BY CASE role WHEN 'owner' THEN 0 ELSE 1 END, created_at, id
           LIMIT 1""",
        (workspace_id,),
    ).fetchone()
    return str(row["id"]) if row else None


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _hash(*values: str) -> str:
    return hashlib.sha256("\x1f".join(values).encode("utf-8")).hexdigest()


__all__ = [
    "YOUTUBE_ROUTE_KEY",
    "is_youtube_channel_record",
    "project_youtube_actor_runtime_record",
    "provision_youtube_actor_sources",
]
