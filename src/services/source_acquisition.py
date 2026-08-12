"""Shared, lease-coordinated acquisition for service catalog sources."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

from ..models import ContentItem
from ..storage.service_store import ServiceStore
from .apify_key_pool import apify_key_pool_enabled, apify_pool_generation


ADAPTER_CONTRACT_VERSION = "service-content-v1"
_PROJECTION_CONFIG_KEYS = {
    "analysis_mode",
    "category",
    "display_name",
    "enabled",
    "hub_channel",
    "name",
    "personal_tags",
    "priority",
    "source_display_name",
    "source_id",
    "source_key",
    "source_priority",
    "subscription_id",
    "tags",
    "topics",
}
_PROJECTION_METADATA_KEYS = {
    "ai_content_format",
    "analysis_status",
    "analysis_mode",
    "category",
    "channel",
    "configured_topics",
    "detailed_summary_zh",
    "hub_channel",
    "inferred_topics",
    "interest_score",
    "personal_tags",
    "scoring_disabled",
    "show_in_personal_feed",
    "signal_strength",
    "signal_type",
    "source_display_name",
    "source_id",
    "source_ids",
    "source_key",
    "source_keys",
    "source_priority",
    "subscription_id",
    "subscription_ids",
    "tags",
    "title_zh",
    "topics",
    "user_state",
}


class AcquisitionBusyError(RuntimeError):
    """Another live claim owns this acquisition and did not finish in time."""

    retryable = True


class AcquisitionBackoffError(RuntimeError):
    """The last upstream failure is still inside its bounded backoff window."""

    retryable = True


class AcquisitionLeaseLostError(RuntimeError):
    """The coordinator no longer owns the claim it is trying to publish."""

    retryable = True


@dataclass(slots=True)
class AcquisitionMetrics:
    """Safe aggregate counters for one user job."""

    cache_hits: int = 0
    cache_misses: int = 0
    upstream_attempts: int = 0
    waits: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "cache_hits": max(int(self.cache_hits), 0),
            "cache_misses": max(int(self.cache_misses), 0),
            "upstream_attempts": max(int(self.upstream_attempts), 0),
            "waits": max(int(self.waits), 0),
        }


@dataclass(frozen=True, slots=True)
class _AcquisitionContext:
    acquisition_key: str
    config_fingerprint: str
    isolation_scope: str
    pool_generation: int | None
    actor_route_id: str | None
    actor_route_generation: int | None
    actor_binding_generation: int | None
    source_id: str
    window_hours: int


def _actor_acquisition_origin(
    items: Any,
    *,
    provider: str | None = None,
) -> str | None:
    for item in items:
        metadata = item.metadata if isinstance(item.metadata, dict) else {}
        if metadata.get("acquisition_origin") == "apify_fallback":
            return "apify_fallback"
    if str(provider or "").strip() == "apify_social":
        return "apify_actor"
    if isinstance(getattr(items, "_apify_actor_route_generation", None), int):
        return "apify_actor"
    return None


def _actor_publication_proof(items: Any) -> dict[str, Any] | None:
    if str(
        getattr(items, "_apify_actor_semantic_outcome", "") or ""
    ) != "advanced":
        return None
    route_generation = getattr(
        items, "_apify_actor_route_generation", None
    )
    proof = {
        "workspace_id": getattr(items, "_apify_actor_workspace_id", None),
        "source_id": getattr(items, "_apify_actor_source_id", None),
        "candidate_id": getattr(items, "_apify_actor_candidate_id", None),
        "latest_published_at": getattr(
            items, "_apify_actor_latest_published_at", None
        ),
        "latest_item_id_hash": getattr(
            items, "_apify_actor_latest_item_id_hash", None
        ),
        "route_generation": route_generation,
        "semantic_outcome": "advanced",
    }
    if (
        not isinstance(route_generation, int)
        or any(
            not isinstance(proof[key], str) or not str(proof[key]).strip()
            for key in (
                "workspace_id",
                "source_id",
                "candidate_id",
                "latest_published_at",
                "latest_item_id_hash",
            )
        )
        or len(str(proof["latest_item_id_hash"])) != 64
    ):
        return None
    return proof


def _with_actor_publication_proof(
    items: list[ContentItem],
    proof: dict[str, Any] | None,
) -> list[ContentItem]:
    if proof is None:
        return items
    from .apify_actor_route import ApifyActorRoutedList

    return ApifyActorRoutedList(
        items,
        route_generation=int(proof["route_generation"]),
        workspace_id=str(proof["workspace_id"]),
        source_id=str(proof["source_id"]),
        candidate_id=str(proof["candidate_id"]),
        latest_published_at=str(proof["latest_published_at"]),
        latest_item_id_hash=str(proof["latest_item_id_hash"]),
        semantic_outcome="advanced",
    )


def shared_acquisition_enabled() -> bool:
    return os.getenv("HORIZON_SHARED_ACQUISITION_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _bounded_env_int(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        return max(int(os.getenv(name, str(default))), minimum)
    except (TypeError, ValueError):
        return max(default, minimum)


def _normalized_network_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _normalized_network_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _PROJECTION_CONFIG_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_normalized_network_value(item) for item in value]
    return value


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _canonical_url(url: str) -> str:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path.rstrip("/")
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{hostname}{port}{path}{query}"


def _source_value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _projection_strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set)):
        return ()
    return tuple(
        dict.fromkeys(
            text
            for item in value
            if (text := str(item).strip())
        )
    )


@dataclass(frozen=True, slots=True)
class TargetSubscriptionProjection:
    """Pure target-owned fields applied after neutral content acquisition."""

    source_id: str
    subscription_id: str | None
    source_key: str | None
    source_display_name: str | None
    catalog_source_type: str | None
    source_priority: int
    channel: str | None
    topics: tuple[str, ...]
    personal_tags: tuple[str, ...]
    analysis_mode: str

    def metadata(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "topics": list(self.topics),
            "tags": list(self.topics),
            "configured_topics": list(self.topics),
            "personal_tags": list(self.personal_tags),
            "source_id": self.source_id,
            "subscription_id": self.subscription_id,
            "source_key": self.source_key,
            "source_display_name": self.source_display_name,
            "catalog_source_type": self.catalog_source_type,
            "source_priority": self.source_priority,
            "analysis_mode": self.analysis_mode,
            **(
                {"show_in_personal_feed": True}
                if self.analysis_mode == "personal_only"
                else {}
            ),
        }


def target_subscription_projection(source: Any) -> TargetSubscriptionProjection:
    """Compute the complete user/subscription projection without side effects."""

    analysis_mode = _source_value(source, "analysis_mode", "full")
    if hasattr(analysis_mode, "value"):
        analysis_mode = analysis_mode.value
    analysis_mode = (
        "personal_only" if str(analysis_mode) == "personal_only" else "full"
    )
    channel_value = (
        _source_value(source, "override_channel")
        or _source_value(source, "hub_channel")
        or _source_value(source, "channel")
        or _source_value(source, "category")
        or _source_value(source, "default_channel")
    )
    override_topics = _projection_strings(
        _source_value(source, "override_topics")
    )
    configured_topics = (
        override_topics
        or _projection_strings(_source_value(source, "topics"))
        or _projection_strings(_source_value(source, "default_topics"))
    )
    topics = list(configured_topics)
    for tag in _projection_strings(_source_value(source, "tags")):
        if tag not in topics:
            topics.append(tag)
    source_priority = _source_value(source, "source_priority")
    if source_priority is None:
        source_priority = _source_value(source, "priority", 0)
    source_display_name = (
        _source_value(source, "source_display_name")
        or _source_value(source, "display_name")
    )
    catalog_source_type = (
        _source_value(source, "catalog_source_type")
        or _source_value(source, "type")
        or _source_value(source, "source_type")
    )
    subscription_id = _source_value(source, "subscription_id")
    source_key = _source_value(source, "source_key")
    return TargetSubscriptionProjection(
        source_id=str(_source_value(source, "source_id") or ""),
        subscription_id=(
            str(subscription_id) if subscription_id not in {None, ""} else None
        ),
        source_key=str(source_key) if source_key not in {None, ""} else None,
        source_display_name=(
            str(source_display_name)
            if source_display_name not in {None, ""}
            else None
        ),
        catalog_source_type=(
            str(catalog_source_type)
            if catalog_source_type not in {None, ""}
            else None
        ),
        source_priority=int(source_priority or 0),
        channel=(
            str(channel_value).strip()
            if channel_value not in {None, ""} and str(channel_value).strip()
            else None
        ),
        topics=tuple(topics),
        personal_tags=_projection_strings(
            _source_value(source, "personal_tags")
        ),
        analysis_mode=analysis_mode,
    )


class SourceAcquisitionCoordinator:
    """Reuse neutral source content while keeping user projection isolated."""

    def __init__(
        self,
        store: ServiceStore,
        *,
        workspace_id: str,
        user_id: str,
        job_id: str,
        lease_seconds: float | None = None,
        wait_seconds: float = 5.0,
        poll_seconds: float = 0.1,
    ) -> None:
        self.store = store
        self.workspace_id = str(workspace_id)
        self.user_id = str(user_id)
        self.job_id = str(job_id)
        self.lease_seconds = max(
            float(
                lease_seconds
                if lease_seconds is not None
                else os.getenv("HORIZON_WORKER_LEASE_SECONDS", "900")
            ),
            1.0,
        )
        self.wait_seconds = max(float(wait_seconds), 0.0)
        self.poll_seconds = max(float(poll_seconds), 0.001)
        self.metrics = AcquisitionMetrics()
        self._origins: dict[str, str] = {}
        self._publication_contexts: dict[str, _AcquisitionContext] = {}

    def origin_for(self, source_id: str) -> str | None:
        """Return whether this coordinator used upstream or cache for one source."""

        return self._origins.get(str(source_id))

    def assert_publication_current(self) -> None:
        """Reject results whose frozen paid-route context changed before Feed write."""

        for context in tuple(self._publication_contexts.values()):
            self._assert_context_current(context)

    async def acquire(
        self,
        *,
        source: Any,
        provider: str,
        window_hours: int,
        fetch: Callable[[], Awaitable[list[ContentItem]]],
    ) -> list[ContentItem]:
        """Return a fresh neutral acquisition projected for the current user."""

        context = self._context(source, window_hours=max(int(window_hours), 1))
        deadline = time.monotonic() + self.wait_seconds
        while True:
            cached = self._load_fresh(context, source)
            if cached is not None:
                self.metrics.cache_hits += 1
                self._origins[context.source_id] = "cache"
                actor_acquisition_origin = _actor_acquisition_origin(
                    cached,
                    provider=provider,
                )
                if actor_acquisition_origin is not None:
                    self._publication_contexts[context.acquisition_key] = context
                return cached

            claim_token = uuid.uuid4().hex
            decision = self._try_claim(context, claim_token)
            if decision == "cached":
                continue
            if decision == "backoff":
                raise AcquisitionBackoffError("source acquisition is backing off")
            if decision == "wait":
                self.metrics.waits += 1
                if time.monotonic() >= deadline:
                    raise AcquisitionBusyError("source acquisition is already running")
                await asyncio.sleep(self.poll_seconds)
                continue

            self.metrics.cache_misses += 1
            self.metrics.upstream_attempts += 1
            try:
                fetched = await fetch()
                actor_publication_proof = _actor_publication_proof(fetched)
                actor_acquisition_origin = _actor_acquisition_origin(
                    fetched,
                    provider=provider,
                )
                publication_context = (
                    context
                    if actor_acquisition_origin is not None
                    else replace(
                        context,
                        pool_generation=None,
                        actor_route_id=None,
                        actor_route_generation=None,
                        actor_binding_generation=None,
                    )
                )
                if (
                    actor_acquisition_origin is not None
                    and context.actor_route_generation is not None
                ):
                    refreshed_context = self._context(
                        source,
                        window_hours=max(int(window_hours), 1),
                    )
                    if (
                        refreshed_context.actor_route_generation
                        != context.actor_route_generation
                        or refreshed_context.actor_binding_generation
                        != context.actor_binding_generation
                    ):
                        routed_generation = getattr(
                            fetched,
                            "_apify_actor_route_generation",
                            None,
                        )
                        if (
                            refreshed_context.pool_generation
                            != context.pool_generation
                            or not isinstance(routed_generation, int)
                            or routed_generation
                            != refreshed_context.actor_route_generation
                        ):
                            raise AcquisitionLeaseLostError(
                                "Apify Actor route generation changed before "
                                "cache publication"
                            )
                        publication_context = refreshed_context
                neutral = self._neutral_items(fetched)
                self._store_success(
                    publication_context,
                    claim_context=context,
                    claim_token=claim_token,
                    provider=provider,
                    items=neutral,
                    actor_publication_proof=actor_publication_proof,
                )
            except BaseException as exc:
                self._record_failure(context, claim_token=claim_token, exc=exc)
                raise
            self._origins[context.source_id] = "upstream"
            if actor_acquisition_origin is not None:
                self._publication_contexts[
                    publication_context.acquisition_key
                ] = publication_context
            return _with_actor_publication_proof(
                self._project_items(neutral, source),
                actor_publication_proof,
            )

    def run_probe(
        self,
        *,
        source: Any,
        call: Callable[[], Any],
    ) -> Any:
        """Serialize an explicit source test without reading or writing content."""

        base_context = self._context(source, window_hours=1)
        context = _AcquisitionContext(
            acquisition_key=hashlib.sha256(
                f"probe:{base_context.acquisition_key}".encode("utf-8")
            ).hexdigest(),
            config_fingerprint=base_context.config_fingerprint,
            isolation_scope=base_context.isolation_scope,
            pool_generation=base_context.pool_generation,
            actor_route_id=base_context.actor_route_id,
            actor_route_generation=base_context.actor_route_generation,
            actor_binding_generation=base_context.actor_binding_generation,
            source_id=base_context.source_id,
            window_hours=1,
        )
        deadline = time.monotonic() + self.wait_seconds
        while True:
            claim_token = uuid.uuid4().hex
            decision = self._try_claim(context, claim_token)
            if decision in {"cached", "wait"}:
                self.metrics.waits += 1
                if time.monotonic() >= deadline:
                    raise AcquisitionBusyError("source test is already running")
                time.sleep(self.poll_seconds)
                continue
            if decision == "backoff":
                raise AcquisitionBackoffError("source test is backing off")
            self.metrics.cache_misses += 1
            self.metrics.upstream_attempts += 1
            try:
                result = call()
            except BaseException as exc:
                self._release_probe(context, claim_token=claim_token, exc=exc)
                raise
            self._release_probe(context, claim_token=claim_token)
            return result

    def _context(self, source: Any, *, window_hours: int) -> _AcquisitionContext:
        source_id = str(_source_value(source, "source_id") or "")
        catalog = self.store.get_source(source_id)
        if not catalog or catalog["workspace_id"] != self.workspace_id:
            raise LookupError("catalog source not found for acquisition")
        isolation_scope = (
            f"user:{self.user_id}"
            if catalog["scope"] == "private"
            else f"workspace:{self.workspace_id}"
        )
        actor_ops_binding = self.store.connect().execute(
            """
            SELECT binding.route_id,
                   binding.generation AS binding_generation,
                   profile.generation AS route_generation,
                   binding.mode
            FROM apify_source_route_bindings AS binding
            JOIN apify_actor_route_profiles AS profile
              ON profile.workspace_id = binding.workspace_id
             AND profile.route_id = binding.route_id
            WHERE binding.workspace_id = ? AND binding.source_id = ?
            """,
            (self.workspace_id, source_id),
        ).fetchone()
        pool_managed = bool(
            apify_key_pool_enabled()
            and (
                catalog["type"] == "apify_social"
                or (
                    actor_ops_binding is not None
                    and str(actor_ops_binding["mode"]) == "fallback"
                )
            )
        )
        pool_generation = (
            apify_pool_generation(self.store, self.workspace_id)
            if pool_managed
            else None
        )
        catalog_config = (
            catalog.get("config")
            if isinstance(catalog.get("config"), dict)
            else {}
        )
        actor_route_managed = bool(
            pool_managed
            and (
                bool(str(catalog_config.get("profile_id") or "").strip())
                or actor_ops_binding is not None
                or (
                    str(catalog_config.get("platform") or "").casefold() == "x"
                    and str(catalog_config.get("kind") or "profile").casefold()
                    == "profile"
                )
            )
        )
        actor_route_id: str | None = None
        actor_route_generation: int | None = None
        actor_binding_generation: int | None = None
        if actor_route_managed:
            profile_id = str(catalog_config.get("profile_id") or "").strip()
            if actor_ops_binding is not None:
                actor_route_id = str(actor_ops_binding["route_id"])
                actor_route_generation = int(
                    actor_ops_binding["route_generation"]
                )
                actor_binding_generation = int(
                    actor_ops_binding["binding_generation"]
                )
                route_row = None
            elif profile_id:
                actor_route_id = profile_id
                route_row = self.store.connect().execute(
                    """
                    SELECT profile.generation,
                           binding.generation AS binding_generation
                    FROM apify_actor_route_profiles AS profile
                    LEFT JOIN apify_source_route_bindings AS binding
                      ON binding.workspace_id = profile.workspace_id
                     AND binding.route_id = profile.route_id
                     AND binding.source_id = ?
                    WHERE profile.workspace_id = ? AND profile.route_id = ?
                    """,
                    (source_id, self.workspace_id, profile_id),
                ).fetchone()
                actor_binding_generation = (
                    int(route_row["binding_generation"])
                    if route_row is not None
                    and route_row["binding_generation"] is not None
                    else None
                )
            else:
                route_row = self.store.connect().execute(
                    """
                    SELECT generation
                    FROM apify_actor_routes
                    WHERE workspace_id = ? AND route_key = 'x/profile'
                    """,
                    (self.workspace_id,),
                ).fetchone()
            if actor_ops_binding is None:
                actor_route_generation = (
                    int(route_row["generation"])
                    if route_row is not None
                    else None
                )
        secret_identity: dict[str, Any] | None = None
        if pool_managed:
            secret_identity = {
                "mode": "workspace_apify_pool",
                "generation": pool_generation,
                "actor_route_id": actor_route_id,
                "actor_route_generation": actor_route_generation,
                "actor_binding_generation": actor_binding_generation,
            }
        else:
            secret_env = str(catalog.get("secret_env") or "")
            if secret_env:
                secret = self.store.get_secret_ref_by_env(
                    workspace_id=self.workspace_id,
                    env_name=secret_env,
                )
                secret_identity = (
                    {
                        "id": secret["id"],
                        "updated_at": secret["updated_at"],
                    }
                    if secret
                    else {"env_name": secret_env}
                )
        fingerprint_payload = {
            "adapter_contract": ADAPTER_CONTRACT_VERSION,
            "source_type": catalog["type"],
            "network_config": _normalized_network_value(catalog.get("config") or {}),
            "network_policy": {
                "enforce_public_network": bool(
                    _source_value(source, "enforce_public_network", False)
                )
            },
            "secret_ref": secret_identity,
        }
        config_fingerprint = hashlib.sha256(
            _stable_json(fingerprint_payload).encode("utf-8")
        ).hexdigest()
        acquisition_payload = {
            "workspace_id": self.workspace_id,
            "isolation_scope": isolation_scope,
            "source_id": source_id,
            "config_fingerprint": config_fingerprint,
            "window_hours": window_hours,
        }
        acquisition_key = hashlib.sha256(
            _stable_json(acquisition_payload).encode("utf-8")
        ).hexdigest()
        return _AcquisitionContext(
            acquisition_key=acquisition_key,
            config_fingerprint=config_fingerprint,
            isolation_scope=isolation_scope,
            pool_generation=pool_generation,
            actor_route_id=actor_route_id,
            actor_route_generation=actor_route_generation,
            actor_binding_generation=actor_binding_generation,
            source_id=source_id,
            window_hours=window_hours,
        )

    def _freshness_minutes(self, source_id: str) -> int:
        row = self.store.connect().execute(
            """
            SELECT MIN(interval_minutes) AS interval_minutes
            FROM (
                SELECT schedules.interval_minutes AS interval_minutes
                FROM user_source_schedules AS schedules
                JOIN user_subscriptions AS subscriptions
                  ON subscriptions.id = schedules.subscription_id
                JOIN users ON users.id = subscriptions.user_id
                JOIN source_catalog AS sources ON sources.id = subscriptions.source_id
                WHERE schedules.source_id = ?
                  AND schedules.enabled = 1
                  AND subscriptions.enabled = 1
                  AND users.enabled = 1
                  AND users.role != 'viewer'
                  AND sources.enabled = 1
                UNION ALL
                SELECT feeds.interval_minutes AS interval_minutes
                FROM user_feed_schedules AS feeds
                JOIN users ON users.id = feeds.user_id
                JOIN user_subscriptions AS subscriptions
                  ON subscriptions.user_id = feeds.user_id
                JOIN source_catalog AS sources ON sources.id = subscriptions.source_id
                WHERE subscriptions.source_id = ?
                  AND feeds.enabled = 1
                  AND subscriptions.enabled = 1
                  AND users.enabled = 1
                  AND users.role != 'viewer'
                  AND sources.enabled = 1
            )
            """,
            (source_id, source_id),
        ).fetchone()
        minimum = _bounded_env_int("HORIZON_SHARED_ACQUISITION_MIN_TTL_MINUTES", 5)
        maximum = _bounded_env_int("HORIZON_SHARED_ACQUISITION_MAX_TTL_MINUTES", 60)
        if maximum < minimum:
            maximum = minimum
        fallback = _bounded_env_int(
            "HORIZON_SHARED_ACQUISITION_FALLBACK_TTL_MINUTES", 30
        )
        scheduled = int(row["interval_minutes"]) if row and row["interval_minutes"] else fallback
        return min(max(scheduled, minimum), maximum)

    def _latest_snapshot(self, context: _AcquisitionContext) -> Any | None:
        return self.store.connect().execute(
            """
            SELECT * FROM source_content_snapshots
            WHERE acquisition_key = ? AND config_fingerprint = ?
            ORDER BY generated_at DESC, created_at DESC, id DESC
            LIMIT 1
            """,
            (context.acquisition_key, context.config_fingerprint),
        ).fetchone()

    def _load_fresh(
        self,
        context: _AcquisitionContext,
        source: Any,
    ) -> list[ContentItem] | None:
        snapshot = self._latest_snapshot(context)
        if snapshot is None:
            return None
        fresh_until = _parse_time(snapshot["fresh_until"])
        if fresh_until is None or fresh_until <= _utcnow():
            return None
        rows = self.store.connect().execute(
            """
            SELECT item_json FROM source_content_items
            WHERE snapshot_id = ?
            ORDER BY position, id
            """,
            (snapshot["id"],),
        ).fetchall()
        neutral = [
            ContentItem.model_validate(json.loads(row["item_json"]))
            for row in rows
        ]
        try:
            diagnostics = json.loads(str(snapshot["diagnostics_json"] or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            diagnostics = {}
        proof = (
            diagnostics.get("actor_publication")
            if isinstance(diagnostics, dict)
            and isinstance(diagnostics.get("actor_publication"), dict)
            else None
        )
        return _with_actor_publication_proof(
            self._project_items(neutral, source),
            proof,
        )

    def _try_claim(self, context: _AcquisitionContext, claim_token: str) -> str:
        conn = self.store.connect()
        if conn.in_transaction:
            raise RuntimeError("source acquisition requires no active transaction")
        now = _utcnow()
        now_iso = now.isoformat()
        try:
            conn.execute("BEGIN IMMEDIATE")
            snapshot = self._latest_snapshot(context)
            if snapshot is not None:
                fresh_until = _parse_time(snapshot["fresh_until"])
                if fresh_until is not None and fresh_until > now:
                    conn.commit()
                    return "cached"
            live_claim = conn.execute(
                """
                SELECT 1
                FROM source_acquisition_states
                WHERE workspace_id = ?
                  AND source_id = ?
                  AND isolation_scope = ?
                  AND config_fingerprint = ?
                  AND claim_token IS NOT NULL
                  AND locked_until > ?
                LIMIT 1
                """,
                (
                    self.workspace_id,
                    context.source_id,
                    context.isolation_scope,
                    context.config_fingerprint,
                    now_iso,
                ),
            ).fetchone()
            if live_claim is not None:
                conn.commit()
                return "wait"
            state = conn.execute(
                "SELECT * FROM source_acquisition_states WHERE acquisition_key = ?",
                (context.acquisition_key,),
            ).fetchone()
            retry_after = _parse_time(state["retry_after"]) if state else None
            if retry_after is not None and retry_after > now:
                conn.commit()
                return "backoff"
            locked_until = _parse_time(state["locked_until"]) if state else None
            if locked_until is not None and locked_until > now and state["claim_token"]:
                conn.commit()
                return "wait"
            conn.execute(
                """
                INSERT INTO source_acquisition_states (
                    acquisition_key, workspace_id, source_id, isolation_scope,
                    config_fingerprint, owner_job_id, claim_token, locked_until,
                    retry_after, last_error_code, failure_count, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 0, ?)
                ON CONFLICT(acquisition_key) DO UPDATE SET
                    workspace_id = excluded.workspace_id,
                    source_id = excluded.source_id,
                    isolation_scope = excluded.isolation_scope,
                    config_fingerprint = excluded.config_fingerprint,
                    owner_job_id = excluded.owner_job_id,
                    claim_token = excluded.claim_token,
                    locked_until = excluded.locked_until,
                    retry_after = NULL,
                    last_error_code = NULL,
                    updated_at = excluded.updated_at
                """,
                (
                    context.acquisition_key,
                    self.workspace_id,
                    context.source_id,
                    context.isolation_scope,
                    context.config_fingerprint,
                    self.job_id,
                    claim_token,
                    (now + timedelta(seconds=self.lease_seconds)).isoformat(),
                    now_iso,
                ),
            )
            conn.commit()
            return "claimed"
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise

    @staticmethod
    def _neutral_items(items: list[ContentItem]) -> list[ContentItem]:
        neutral_by_id: dict[str, ContentItem] = {}
        for item in items:
            copied = item.model_copy(deep=True)
            copied.ai_score = None
            copied.ai_reason = None
            copied.ai_summary = None
            copied.ai_summary_zh = None
            copied.ai_category = None
            copied.ai_is_featured = False
            copied.ai_action_suggestion = None
            copied.ai_tags = []
            copied.ai_channel = None
            copied.ai_topics = []
            copied.ai_signal_strength = None
            copied.ai_signal_type = None
            copied.ai_entities = []
            copied.metadata = {
                key: value
                for key, value in copied.metadata.items()
                if key not in _PROJECTION_METADATA_KEYS
            }
            neutral_by_id.setdefault(copied.id, copied)
        return list(neutral_by_id.values())

    @staticmethod
    def _project_items(items: list[ContentItem], source: Any) -> list[ContentItem]:
        projection = target_subscription_projection(source)
        projected: list[ContentItem] = []
        for item in items:
            copied = item.model_copy(deep=True)
            copied.metadata.update(projection.metadata())
            if projection.analysis_mode != "personal_only":
                copied.metadata.pop("show_in_personal_feed", None)
            projected.append(copied)
        return projected

    def _store_success(
        self,
        context: _AcquisitionContext,
        *,
        claim_context: _AcquisitionContext | None = None,
        claim_token: str,
        provider: str,
        items: list[ContentItem],
        actor_publication_proof: dict[str, Any] | None = None,
    ) -> None:
        conn = self.store.connect()
        now = _utcnow()
        snapshot_id = f"acq_{uuid.uuid4().hex}"
        original_context = claim_context or context
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._assert_context_current(context, connection=conn)
            state = conn.execute(
                """
                SELECT claim_token FROM source_acquisition_states
                WHERE acquisition_key = ?
                """,
                (original_context.acquisition_key,),
            ).fetchone()
            if state is None or state["claim_token"] != claim_token:
                raise AcquisitionLeaseLostError("source acquisition lease was lost")
            if original_context.acquisition_key != context.acquisition_key:
                collision = conn.execute(
                    """
                    SELECT 1 FROM source_acquisition_states
                    WHERE acquisition_key = ?
                    """,
                    (context.acquisition_key,),
                ).fetchone()
                if collision is not None:
                    raise AcquisitionLeaseLostError(
                        "new Actor route generation is already being acquired"
                    )
                cursor = conn.execute(
                    """
                    UPDATE source_acquisition_states
                    SET acquisition_key = ?, config_fingerprint = ?,
                        updated_at = ?
                    WHERE acquisition_key = ? AND claim_token = ?
                    """,
                    (
                        context.acquisition_key,
                        context.config_fingerprint,
                        now.isoformat(),
                        original_context.acquisition_key,
                        claim_token,
                    ),
                )
                if cursor.rowcount != 1:
                    raise AcquisitionLeaseLostError(
                        "source acquisition lease was lost"
                    )
            fresh_until = now + timedelta(
                minutes=self._freshness_minutes(context.source_id)
            )
            conn.execute(
                """
                INSERT INTO source_content_snapshots (
                    id, acquisition_key, workspace_id, source_id,
                    config_fingerprint, isolation_scope, window_hours,
                    generated_at, fresh_until, item_count, producer_job_id,
                    diagnostics_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    context.acquisition_key,
                    self.workspace_id,
                    context.source_id,
                    context.config_fingerprint,
                    context.isolation_scope,
                    context.window_hours,
                    now.isoformat(),
                    fresh_until.isoformat(),
                    len(items),
                    self.job_id,
                    _stable_json(
                        {
                            "adapter_contract": ADAPTER_CONTRACT_VERSION,
                            "provider": str(provider),
                            "upstream_attempts": 1,
                            **(
                                {
                                    "actor_publication": actor_publication_proof
                                }
                                if actor_publication_proof is not None
                                else {}
                            ),
                        }
                    ),
                    now.isoformat(),
                ),
            )
            for position, item in enumerate(items):
                conn.execute(
                    """
                    INSERT INTO source_content_items (
                        id, snapshot_id, canonical_key, source_item_id,
                        position, item_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"aci_{uuid.uuid4().hex}",
                        snapshot_id,
                        _canonical_url(str(item.url)),
                        item.id,
                        position,
                        _stable_json(item.model_dump(mode="json")),
                        now.isoformat(),
                    ),
                )
            cursor = conn.execute(
                """
                UPDATE source_acquisition_states
                SET owner_job_id = NULL, claim_token = NULL, locked_until = NULL,
                    retry_after = NULL, last_error_code = NULL, failure_count = 0,
                    updated_at = ?
                WHERE acquisition_key = ? AND claim_token = ?
                """,
                (now.isoformat(), context.acquisition_key, claim_token),
            )
            if cursor.rowcount != 1:
                raise AcquisitionLeaseLostError("source acquisition lease was lost")
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise

    def _assert_context_current(
        self,
        context: _AcquisitionContext,
        *,
        connection: Any | None = None,
    ) -> None:
        conn = connection or self.store.connect()
        if (
            context.pool_generation is not None
            and apify_pool_generation(self.store, self.workspace_id)
            != context.pool_generation
        ):
            raise AcquisitionLeaseLostError(
                "Apify key pool generation changed before publication"
            )
        if context.actor_route_generation is None:
            return
        if context.actor_route_id is not None:
            route_row = conn.execute(
                """
                SELECT profile.generation,
                       binding.generation AS binding_generation
                FROM apify_actor_route_profiles AS profile
                LEFT JOIN apify_source_route_bindings AS binding
                  ON binding.workspace_id = profile.workspace_id
                 AND binding.route_id = profile.route_id
                 AND binding.source_id = ?
                WHERE profile.workspace_id = ? AND profile.route_id = ?
                """,
                (
                    context.source_id,
                    self.workspace_id,
                    context.actor_route_id,
                ),
            ).fetchone()
        else:
            route_row = conn.execute(
                """
                SELECT generation, NULL AS binding_generation
                FROM apify_actor_routes
                WHERE workspace_id = ? AND route_key = 'x/profile'
                """,
                (self.workspace_id,),
            ).fetchone()
        current_route_generation = (
            int(route_row["generation"]) if route_row is not None else None
        )
        current_binding_generation = (
            int(route_row["binding_generation"])
            if route_row is not None
            and route_row["binding_generation"] is not None
            else None
        )
        if (
            current_route_generation != context.actor_route_generation
            or current_binding_generation != context.actor_binding_generation
        ):
            raise AcquisitionLeaseLostError(
                "Apify Actor route generation changed before publication"
            )

    def _record_failure(
        self,
        context: _AcquisitionContext,
        *,
        claim_token: str,
        exc: BaseException,
    ) -> None:
        conn = self.store.connect()
        now = _utcnow()
        base_seconds = _bounded_env_int(
            "HORIZON_SHARED_ACQUISITION_FAILURE_BACKOFF_SECONDS", 30
        )
        try:
            if conn.in_transaction:
                conn.rollback()
            conn.execute("BEGIN IMMEDIATE")
            state = conn.execute(
                """
                SELECT failure_count FROM source_acquisition_states
                WHERE acquisition_key = ? AND claim_token = ?
                """,
                (context.acquisition_key, claim_token),
            ).fetchone()
            if state is not None:
                failure_count = int(state["failure_count"] or 0) + 1
                backoff_seconds = min(base_seconds * (2 ** (failure_count - 1)), 300)
                conn.execute(
                    """
                    UPDATE source_acquisition_states
                    SET owner_job_id = NULL, claim_token = NULL, locked_until = NULL,
                        retry_after = ?, last_error_code = ?, failure_count = ?,
                        updated_at = ?
                    WHERE acquisition_key = ? AND claim_token = ?
                    """,
                    (
                        (now + timedelta(seconds=backoff_seconds)).isoformat(),
                        type(exc).__name__,
                        failure_count,
                        now.isoformat(),
                        context.acquisition_key,
                        claim_token,
                    ),
                )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()

    def _release_probe(
        self,
        context: _AcquisitionContext,
        *,
        claim_token: str,
        exc: BaseException | None = None,
    ) -> None:
        conn = self.store.connect()
        now = _utcnow().isoformat()
        try:
            if conn.in_transaction:
                conn.rollback()
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                """
                UPDATE source_acquisition_states
                SET owner_job_id = NULL, claim_token = NULL, locked_until = NULL,
                    retry_after = NULL, last_error_code = ?, failure_count = 0,
                    updated_at = ?
                WHERE acquisition_key = ? AND claim_token = ?
                """,
                (
                    type(exc).__name__ if exc is not None else None,
                    now,
                    context.acquisition_key,
                    claim_token,
                ),
            )
            if cursor.rowcount != 1 and exc is None:
                raise AcquisitionLeaseLostError("source test lease was lost")
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            if exc is None:
                raise
