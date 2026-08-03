"""Low-frequency, read-only metadata checks for active Actor revisions."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from ..storage.service_store import ServiceStore
from .apify_actor_discovery import (
    ActorDiscoveryError,
    ActorMetadataClient,
    ApifyStoreRestClient,
    _actor_id,
    _json_hash,
    _pricing,
    _publisher,
    _safe_pricing_summary,
    _schemas,
    _tagged_build,
    _validate_pricing,
)
from .apify_actor_ops import ApifyActorOpsService


ATTEMPT_RETRY_SECONDS = 3600
MAX_ROUTES_PER_PASS = 10


@dataclass(frozen=True, slots=True)
class MetadataRevisionSnapshot:
    revision_id: str
    actor_id: str
    publisher: str
    build_id: str
    build_number: str
    input_schema_hash: str | None
    output_schema_hash: str | None
    pricing: Mapping[str, Any]
    permission_level: str


@dataclass(frozen=True, slots=True)
class MetadataRouteSnapshot:
    workspace_id: str
    route_id: str
    generation: int
    per_run_cap_usd: float
    revisions: tuple[MetadataRevisionSnapshot, ...]


class ApifyActorMetadataMaintenance:
    """Claim due Routes, read Store metadata, and CAS-apply safe summaries."""

    def __init__(
        self,
        store: ServiceStore,
        client_factory: Callable[
            [str],
            ActorMetadataClient | None,
        ],
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.client_factory = client_factory
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def run_if_due(
        self,
        *,
        force: bool = False,
        max_routes: int = MAX_ROUTES_PER_PASS,
    ) -> dict[str, int]:
        current = _utc(self._now())
        claims = self._claim_due(
            current,
            force=force,
            max_routes=max_routes,
        )
        result = {
            "claimed": len(claims),
            "unchanged": 0,
            "changed": 0,
            "quarantined": 0,
            "stale": 0,
            "failed": 0,
        }
        for snapshot in claims:
            client = self.client_factory(snapshot.workspace_id)
            if client is None:
                result["failed"] += 1
                continue
            try:
                changes, unsafe, fingerprints = await self._inspect(
                    snapshot,
                    client,
                )
                applied = ApifyActorOpsService(
                    self.store,
                    workspace_id=snapshot.workspace_id,
                    now=lambda: current,
                ).apply_metadata_check(
                    snapshot.route_id,
                    expected_generation=snapshot.generation,
                    expected_revision_ids=tuple(
                        revision.revision_id
                        for revision in snapshot.revisions
                    ),
                    observed_fingerprints=fingerprints,
                    changes=changes,
                    unsafe_revision_ids=frozenset(unsafe),
                )
            except ActorDiscoveryError:
                # Transient Store/API failures do not mutate a production Route.
                result["failed"] += 1
                continue
            status = str(applied["status"])
            if status == "stale":
                result["stale"] += 1
                continue
            self._mark_success(snapshot.route_id, current)
            if status == "unchanged":
                result["unchanged"] += 1
            elif status == "quarantined":
                result["quarantined"] += 1
            else:
                result["changed"] += 1
        return result

    def _claim_due(
        self,
        current: datetime,
        *,
        force: bool,
        max_routes: int,
    ) -> tuple[MetadataRouteSnapshot, ...]:
        connection = self.store.connect()
        routes = connection.execute(
            """
            SELECT profile.workspace_id, profile.route_id,
                   profile.generation, profile.per_run_cap_usd,
                   profile.metadata_check_interval_seconds
            FROM apify_actor_route_profiles AS profile
            WHERE EXISTS (
                SELECT 1
                FROM apify_route_active_slots AS slot
                JOIN apify_actor_adapter_revisions AS revision
                  ON revision.workspace_id = slot.workspace_id
                 AND revision.revision_id = slot.revision_id
                WHERE slot.workspace_id = profile.workspace_id
                  AND slot.route_id = profile.route_id
                  AND revision.lifecycle != 'legacy_builtin'
            )
            ORDER BY profile.workspace_id, profile.route_id
            """
        ).fetchall()
        claims: list[MetadataRouteSnapshot] = []
        for route in routes:
            if len(claims) >= max(1, min(int(max_routes), 100)):
                break
            route_id = str(route["route_id"])
            success_key = _state_key("success", route_id)
            attempt_key = _state_key("attempt", route_id)
            try:
                connection.execute("BEGIN IMMEDIATE")
                current_route = connection.execute(
                    """
                    SELECT generation, per_run_cap_usd,
                           metadata_check_interval_seconds
                    FROM apify_actor_route_profiles
                    WHERE workspace_id = ? AND route_id = ?
                    """,
                    (route["workspace_id"], route_id),
                ).fetchone()
                state_rows = connection.execute(
                    """
                    SELECT key, last_run_at
                    FROM maintenance_state
                    WHERE key IN (?, ?)
                    """,
                    (success_key, attempt_key),
                ).fetchall()
                states = {
                    str(row["key"]): _parse_time(row["last_run_at"])
                    for row in state_rows
                }
                if current_route is None:
                    connection.commit()
                    continue
                last_success = states.get(success_key)
                last_attempt = states.get(attempt_key)
                interval = int(
                    current_route["metadata_check_interval_seconds"]
                )
                if (
                    not force
                    and last_success is not None
                    and current < last_success + timedelta(seconds=interval)
                ):
                    connection.commit()
                    continue
                if (
                    not force
                    and last_attempt is not None
                    and current
                    < last_attempt + timedelta(seconds=ATTEMPT_RETRY_SECONDS)
                ):
                    connection.commit()
                    continue
                revision_rows = connection.execute(
                    """
                    SELECT revision.revision_id, revision.actor_id,
                           revision.publisher, revision.build_id,
                           revision.build_number,
                           revision.input_schema_hash,
                           revision.output_schema_hash,
                           revision.pricing_json,
                           revision.permission_level
                    FROM apify_route_active_slots AS slot
                    JOIN apify_actor_adapter_revisions AS revision
                      ON revision.workspace_id = slot.workspace_id
                     AND revision.revision_id = slot.revision_id
                    WHERE slot.workspace_id = ? AND slot.route_id = ?
                      AND revision.lifecycle != 'legacy_builtin'
                    ORDER BY CASE slot.slot_name
                        WHEN 'primary' THEN 1
                        WHEN 'backup_1' THEN 2
                        ELSE 3 END
                    """,
                    (route["workspace_id"], route_id),
                ).fetchall()
                revisions = tuple(
                    MetadataRevisionSnapshot(
                        revision_id=str(row["revision_id"]),
                        actor_id=str(row["actor_id"]),
                        publisher=str(row["publisher"]),
                        build_id=str(row["build_id"]),
                        build_number=str(row["build_number"]),
                        input_schema_hash=(
                            str(row["input_schema_hash"])
                            if row["input_schema_hash"]
                            else None
                        ),
                        output_schema_hash=(
                            str(row["output_schema_hash"])
                            if row["output_schema_hash"]
                            else None
                        ),
                        pricing=_json_object(row["pricing_json"]),
                        permission_level=str(row["permission_level"]),
                    )
                    for row in revision_rows
                    if row["build_id"] and row["build_number"]
                )
                if not revisions:
                    connection.commit()
                    continue
                now_iso = current.isoformat()
                connection.execute(
                    """
                    INSERT INTO maintenance_state (key, last_run_at, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        last_run_at = excluded.last_run_at,
                        updated_at = excluded.updated_at
                    """,
                    (attempt_key, now_iso, now_iso),
                )
                connection.commit()
            except BaseException:
                if connection.in_transaction:
                    connection.rollback()
                raise
            claims.append(
                MetadataRouteSnapshot(
                    workspace_id=str(route["workspace_id"]),
                    route_id=route_id,
                    generation=int(current_route["generation"]),
                    per_run_cap_usd=float(
                        current_route["per_run_cap_usd"]
                    ),
                    revisions=revisions,
                )
            )
        return tuple(claims)

    async def _inspect(
        self,
        snapshot: MetadataRouteSnapshot,
        client: ActorMetadataClient,
    ) -> tuple[
        dict[str, tuple[str, ...]],
        set[str],
        dict[str, str],
    ]:
        changes: dict[str, tuple[str, ...]] = {}
        unsafe: set[str] = set()
        fingerprints: dict[str, str] = {}
        for revision in snapshot.revisions:
            codes: set[str] = set()
            revision_unsafe = False
            try:
                actor = dict(
                    await _maybe_await(client.get_actor(revision.actor_id))
                )
            except ActorDiscoveryError as exc:
                if exc.code != "apify_actor_metadata_not_found":
                    raise
                changes[revision.revision_id] = (
                    "actor_metadata_not_found",
                )
                unsafe.add(revision.revision_id)
                fingerprints[revision.revision_id] = _metadata_fingerprint(
                    {
                        "actor_id": revision.actor_id,
                        "actor_status": "not_found",
                        "build_id": revision.build_id,
                    }
                )
                continue
            identities = {
                value
                for value in (
                    _actor_id(actor),
                    str(actor.get("id") or "").replace("~", "/"),
                    str(actor.get("actorId") or "").replace("~", "/"),
                )
                if value
            }
            username = str(
                actor.get("username") or actor.get("userUsername") or ""
            ).strip()
            name = str(
                actor.get("name") or actor.get("actorName") or ""
            ).strip()
            if username and name:
                identities.add(f"{username}/{name}")
            if identities and revision.actor_id not in identities:
                codes.add("actor_identity_changed")
                revision_unsafe = True
            if actor.get("isPublic") is not True:
                codes.add("actor_not_public")
                revision_unsafe = True
            if actor.get("isDeprecated") is not False:
                codes.add(
                    "actor_deprecated"
                    if actor.get("isDeprecated") is True
                    else "actor_deprecation_unverifiable"
                )
                revision_unsafe = True
            if actor.get("isRunnable") is False or actor.get("canRun") is False:
                codes.add("actor_not_runnable")
                revision_unsafe = True
            permission = str(actor.get("actorPermissionLevel") or "unknown")
            if permission != revision.permission_level:
                codes.add("actor_permission_changed")
            if permission.casefold() != "limited_permissions":
                codes.add(
                    "actor_full_permission"
                    if permission.casefold() == "full_permissions"
                    else "actor_permission_unverifiable"
                )
                revision_unsafe = True
            try:
                publisher = _publisher(revision.actor_id, actor)
            except ActorDiscoveryError:
                publisher = ""
            if publisher and publisher != revision.publisher.casefold():
                codes.add("actor_publisher_changed")
                revision_unsafe = True

            pricing = _pricing(actor)
            try:
                _validate_pricing(pricing, snapshot.per_run_cap_usd)
            except ActorDiscoveryError:
                codes.add("actor_pricing_unsafe")
                revision_unsafe = True
            if _safe_pricing_summary(pricing) != _safe_pricing_summary(
                revision.pricing
            ):
                codes.add("actor_pricing_changed")

            latest_build_id, latest_build_number = _tagged_build(actor)
            if (
                latest_build_id
                and (
                    latest_build_id != revision.build_id
                    or latest_build_number != revision.build_number
                )
            ):
                codes.add("actor_default_build_changed")
            if not latest_build_id or not latest_build_number:
                codes.add("actor_tagged_build_missing")

            try:
                build = dict(
                    await _maybe_await(client.get_build(revision.build_id))
                )
            except ActorDiscoveryError as exc:
                if exc.code != "apify_actor_metadata_not_found":
                    raise
                codes.add("actor_exact_build_unavailable")
                revision_unsafe = True
                build = {}
            input_schema_digest = ""
            output_schema_digest = ""
            if build:
                if str(build.get("status") or "").upper() != "SUCCEEDED":
                    codes.add("actor_exact_build_unsuccessful")
                    revision_unsafe = True
                actual_number = str(build.get("buildNumber") or "")
                if (
                    actual_number
                    and actual_number != revision.build_number
                ):
                    codes.add("actor_exact_build_identity_changed")
                    revision_unsafe = True
                input_schema, output_schema = _schemas(build)
                if not input_schema or not output_schema:
                    codes.add("actor_schema_unverifiable")
                    revision_unsafe = True
                else:
                    input_schema_digest = _json_hash(input_schema)
                    output_schema_digest = _json_hash(output_schema)
                    if (
                        revision.input_schema_hash
                        and input_schema_digest != revision.input_schema_hash
                    ):
                        codes.add("actor_input_schema_changed")
                        revision_unsafe = True
                    if (
                        revision.output_schema_hash
                        and output_schema_digest != revision.output_schema_hash
                    ):
                        codes.add("actor_output_schema_changed")
                        revision_unsafe = True

            # Persist only this bounded digest. Raw metadata is never stored
            # or sent to AI when the digest is unchanged.
            fingerprints[revision.revision_id] = _metadata_fingerprint(
                {
                    "actor_id": revision.actor_id,
                    "public": actor.get("isPublic") is True,
                    "deprecated": actor.get("isDeprecated") is True,
                    "store_unrunnable_actors_excluded": True,
                    "permission": permission,
                    "latest_build_id": latest_build_id,
                    "latest_build_number": latest_build_number,
                    "pinned_build_status": str(
                        build.get("status") or ""
                    ).upper(),
                    "pinned_build_number": str(
                        build.get("buildNumber") or ""
                    ),
                    "input_schema_hash": input_schema_digest,
                    "output_schema_hash": output_schema_digest,
                    "pricing": _safe_pricing_summary(pricing),
                }
            )
            if codes:
                changes[revision.revision_id] = tuple(sorted(codes))
            if revision_unsafe:
                unsafe.add(revision.revision_id)
        return changes, unsafe, fingerprints

    def _mark_success(
        self,
        route_id: str,
        current: datetime,
    ) -> None:
        connection = self.store.connect()
        now_iso = current.isoformat()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO maintenance_state (key, last_run_at, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    last_run_at = excluded.last_run_at,
                    updated_at = excluded.updated_at
                """,
                (_state_key("success", route_id), now_iso, now_iso),
            )
            connection.commit()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise


def run_due_actor_metadata_checks(
    store: ServiceStore,
) -> dict[str, int]:
    """Worker entrypoint; metadata reads use only the active SecretStore ref."""

    def client_factory(workspace_id: str) -> ActorMetadataClient | None:
        row = store.connect().execute(
            """
            SELECT secret.env_name
            FROM apify_key_pool_state AS state
            JOIN secret_refs AS secret
              ON secret.workspace_id = state.workspace_id
             AND secret.id = state.active_secret_id
            WHERE state.workspace_id = ?
            """,
            (workspace_id,),
        ).fetchone()
        env_name = str(row["env_name"]) if row is not None else ""
        token = os.getenv(env_name) if env_name else None
        return ApifyStoreRestClient(token) if token else None

    return asyncio.run(
        ApifyActorMetadataMaintenance(
            store,
            client_factory,
        ).run_if_due()
    )


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _state_key(kind: str, route_id: str) -> str:
    digest = hashlib.sha256(str(route_id).encode("utf-8")).hexdigest()
    return f"apify_actor_metadata:{kind}:{digest}"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return _utc(datetime.fromisoformat(str(value)))
    except ValueError:
        return None


def _json_object(value: Any) -> Mapping[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _metadata_fingerprint(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    if len(payload.encode("utf-8")) > 16 * 1024:
        raise ActorDiscoveryError(
            "apify_actor_metadata_too_large",
            "Actor metadata fingerprint exceeds the safety limit",
            retryable=False,
            status_code=502,
        )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "ApifyActorMetadataMaintenance",
    "MetadataRevisionSnapshot",
    "MetadataRouteSnapshot",
    "run_due_actor_metadata_checks",
]
