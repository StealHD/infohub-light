"""ActorOps compatibility, freshness, watermark and safe diagnostic state."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from ..storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore
from .operation_log import safe_emit_operation_event


FRESHNESS_MIN_HOURS = 6
FRESHNESS_MAX_HOURS = 168
FRESHNESS_DEFAULT_HOURS = 24
FRESHNESS_PER_ACTOR_CAP_USD = 0.02
DIAGNOSTIC_RETENTION_DAYS = 30
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")


class ActorResilienceError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _utc_now()).astimezone(timezone.utc).isoformat()


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_code(value: Any, fallback: str) -> str:
    normalized = str(value or "").strip().casefold().replace("-", "_")
    return normalized if _SAFE_CODE.fullmatch(normalized) else fallback


def _encode_cursor(created_at: str, event_id: str) -> str:
    payload = json.dumps(
        [created_at, event_id], separators=(",", ":")
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(value: str) -> tuple[str, str]:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        payload = json.loads(raw)
    except Exception as exc:
        raise ActorResilienceError(
            "invalid_cursor", "Diagnostic cursor is invalid", status_code=400
        ) from exc
    if (
        not isinstance(payload, list)
        or len(payload) != 2
        or not all(isinstance(item, str) and item for item in payload)
    ):
        raise ActorResilienceError(
            "invalid_cursor", "Diagnostic cursor is invalid", status_code=400
        )
    return payload[0], payload[1]


class ApifyActorResilienceService:
    """Own the product-first admission and operational diagnosis state."""

    def __init__(
        self,
        store: ServiceStore,
        *,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> None:
        self.store = store
        self.workspace_id = str(workspace_id)

    @property
    def connection(self) -> sqlite3.Connection:
        return self.store.connect()

    def _route(self, route_id: str) -> sqlite3.Row:
        row = self.connection.execute(
            """
            SELECT * FROM apify_actor_route_profiles
            WHERE workspace_id = ? AND route_id = ?
            """,
            (self.workspace_id, str(route_id)),
        ).fetchone()
        if row is None:
            raise ActorResilienceError(
                "apify_actor_route_not_found",
                "Actor route not found",
                status_code=404,
            )
        return row

    def validation_key_state(self) -> dict[str, Any]:
        row = self.connection.execute(
            """
            SELECT secret_id, status, last_checked_at, last_error_code
            FROM apify_key_pool_members
            WHERE workspace_id = ? AND role = 'validation'
            LIMIT 1
            """,
            (self.workspace_id,),
        ).fetchone()
        return {
            "configured": row is not None,
            "secret_id": str(row["secret_id"]) if row else None,
            "status": str(row["status"]) if row else "unassigned",
            "usable": bool(row is not None and row["status"] == "standby"),
            "last_checked_at": row["last_checked_at"] if row else None,
            "last_error_code": row["last_error_code"] if row else None,
        }

    def route_resilience(self, route_id: str) -> dict[str, Any]:
        route = self._route(route_id)
        slots = self.connection.execute(
            """
            SELECT slot.slot_name, slot.candidate_id, slot.revision_id,
                   candidate.display_name, candidate.state,
                   revision.execution_mode, revision.observed_manifest,
                   result.status AS freshness_status,
                   result.latest_published_at,
                   result.consecutive_fresh_count,
                   result.consecutive_stale_count,
                   result.reason_code AS freshness_reason_code,
                   result.updated_at AS freshness_updated_at
            FROM apify_route_active_slots AS slot
            LEFT JOIN apify_actor_candidates AS candidate
              ON candidate.id = slot.candidate_id
            LEFT JOIN apify_actor_adapter_revisions AS revision
              ON revision.workspace_id = slot.workspace_id
             AND revision.revision_id = slot.revision_id
            LEFT JOIN apify_actor_freshness_results AS result
              ON result.rowid = (
                  SELECT latest.rowid
                  FROM apify_actor_freshness_results AS latest
                  JOIN apify_actor_freshness_checks AS check_row
                    ON check_row.workspace_id = latest.workspace_id
                   AND check_row.check_id = latest.check_id
                  WHERE latest.workspace_id = slot.workspace_id
                    AND latest.candidate_id = slot.candidate_id
                    AND check_row.route_id = slot.route_id
                  ORDER BY latest.updated_at DESC, latest.rowid DESC
                  LIMIT 1
              )
            WHERE slot.workspace_id = ? AND slot.route_id = ?
            ORDER BY CASE slot.slot_name
                WHEN 'primary' THEN 0 WHEN 'backup_1' THEN 1 ELSE 2 END
            """,
            (self.workspace_id, str(route_id)),
        ).fetchall()
        active_count = sum(
            1
            for row in slots
            if row["candidate_id"] is not None
            and str(row["state"] or "") != "disabled"
        )
        interval = int(route["freshness_interval_hours"] or 24)
        round_cap = round(
            active_count * FRESHNESS_PER_ACTOR_CAP_USD, 6
        )
        monthly_rounds = 0.0
        if bool(route["freshness_enabled"]):
            monthly_rounds = (24.0 * 30.0) / interval
        return {
            "admission_mode": str(route["admission_mode"]),
            "actual_min_runtime_healthy": int(route["min_runtime_healthy"]),
            "actual_min_publishers": int(route["min_publishers"]),
            "active_slot_count": active_count,
            "compatibility_risk": (
                {
                    "code": str(
                        route["compatibility_risk_code"]
                        or "single_actor_no_redundancy"
                    ),
                    "requires_operator_acknowledgement": True,
                }
                if str(route["admission_mode"]) == "compatibility"
                else None
            ),
            "freshness": {
                "enabled": bool(route["freshness_enabled"]),
                "interval_hours": interval,
                "status": str(route["freshness_status"]),
                "authorized_at": route["freshness_authorized_at"],
                "last_checked_at": route["freshness_last_checked_at"],
                "next_check_at": route["freshness_next_check_at"],
                "last_actual_cost_usd": route["freshness_last_cost_usd"],
                "per_round_max_usd": round_cap,
                "theoretical_monthly_max_usd": round(
                    round_cap * monthly_rounds, 4
                ),
                "validation_key": self.validation_key_state(),
            },
            "slot_freshness": [
                {
                    "slot_name": str(row["slot_name"]),
                    "candidate_id": row["candidate_id"],
                    "actor_name": row["display_name"],
                    "execution_mode": row["execution_mode"],
                    "follows_current_build": row["execution_mode"] == "current",
                    "observed_manifest": bool(row["observed_manifest"] or 0),
                    "status": row["freshness_status"] or "not_checked",
                    "latest_published_at": row["latest_published_at"],
                    "consecutive_fresh_count": int(
                        row["consecutive_fresh_count"] or 0
                    ),
                    "consecutive_stale_count": int(
                        row["consecutive_stale_count"] or 0
                    ),
                    "reason_code": row["freshness_reason_code"],
                    "checked_at": row["freshness_updated_at"],
                }
                for row in slots
            ],
        }

    def update_freshness_settings(
        self,
        route_id: str,
        *,
        enabled: bool,
        interval_hours: int,
        expected_generation: int,
        actor_user_id: str,
        standing_authorization_confirmed: bool,
    ) -> dict[str, Any]:
        route = self._route(route_id)
        if int(route["generation"]) != int(expected_generation):
            raise ActorResilienceError(
                "apify_actor_route_generation_conflict",
                "Actor route changed; reload before updating freshness",
            )
        interval = int(interval_hours)
        if not FRESHNESS_MIN_HOURS <= interval <= FRESHNESS_MAX_HOURS:
            raise ActorResilienceError(
                "invalid_freshness_interval",
                "Freshness interval must be between 6 and 168 hours",
                status_code=400,
            )
        validation_key = self.validation_key_state()
        if enabled and not standing_authorization_confirmed:
            raise ActorResilienceError(
                "freshness_authorization_required",
                "Standing cost authorization must be confirmed",
                status_code=412,
            )
        if enabled and not validation_key["usable"]:
            raise ActorResilienceError(
                "apify_validation_key_required",
                "A usable validation key is required for automatic freshness checks",
                status_code=412,
            )
        if enabled and int(self.route_resilience(route_id)["active_slot_count"]) < 1:
            raise ActorResilienceError(
                "apify_actor_route_empty",
                "Automatic freshness checks require at least one active Actor",
                status_code=412,
            )
        now = _utc_now()
        next_check = now + timedelta(hours=interval) if enabled else None
        cursor = self.connection.execute(
            """
            UPDATE apify_actor_route_profiles
            SET freshness_enabled = ?, freshness_interval_hours = ?,
                freshness_authorized_at = ?,
                freshness_authorized_by_user_id = ?,
                freshness_next_check_at = ?, freshness_status = ?,
                generation = generation + 1, updated_at = ?
            WHERE workspace_id = ? AND route_id = ? AND generation = ?
            """,
            (
                int(enabled),
                interval,
                _iso(now) if enabled else None,
                str(actor_user_id) if enabled else None,
                _iso(next_check) if next_check else None,
                "scheduled" if enabled else "disabled",
                _iso(now),
                self.workspace_id,
                str(route_id),
                int(expected_generation),
            ),
        )
        if cursor.rowcount != 1:
            raise ActorResilienceError(
                "apify_actor_route_generation_conflict",
                "Actor route changed; reload before updating freshness",
            )
        self.connection.commit()
        self.emit_event(
            route_id=route_id,
            phase="freshness_settings",
            outcome="succeeded",
            reason_code=("standing_authorized" if enabled else "disabled"),
        )
        return self.route_resilience(route_id)

    def freshness_plan(self, route_id: str) -> dict[str, Any]:
        route_state = self.route_resilience(route_id)
        count = int(route_state["active_slot_count"])
        max_total = min(
            round(count * FRESHNESS_PER_ACTOR_CAP_USD, 6), 0.06
        )
        return {
            "route_id": str(route_id),
            "actor_count": int(route_state["active_slot_count"]),
            "serial_execution": True,
            "same_reference_target": True,
            "reference_target_exposed": False,
            "per_actor_cap_usd": FRESHNESS_PER_ACTOR_CAP_USD,
            "max_total_charge_usd": max_total,
            "actual_cost_usd": None,
            "frequency": route_state["freshness"],
            "requires_cost_confirmation": True,
            "requires_validation_key": True,
        }

    def create_freshness_check(
        self,
        route_id: str,
        *,
        trigger_kind: Literal["manual", "automatic"],
        actor_user_id: str | None,
        cost_confirmed: bool,
        expected_generation: int | None = None,
        approved_max_total_charge_usd: float | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        route = self._route(route_id)
        plan = self.freshness_plan(route_id)
        if int(plan["actor_count"]) < 1:
            raise ActorResilienceError(
                "apify_actor_route_empty",
                "Freshness check requires at least one active Actor",
                status_code=412,
            )
        if not self.validation_key_state()["usable"]:
            raise ActorResilienceError(
                "apify_validation_key_required",
                "A usable validation key is required for freshness checks",
                status_code=412,
            )
        unresolved_validation = self.connection.execute(
            """
            SELECT 1 FROM apify_actor_runs
            WHERE workspace_id = ? AND purpose = 'validation'
              AND status IN (
                  'reserved', 'starting', 'running', 'start_outcome_unknown'
              )
            LIMIT 1
            """,
            (self.workspace_id,),
        ).fetchone()
        if unresolved_validation is not None:
            raise ActorResilienceError(
                "apify_validation_reconciliation_required",
                "An earlier validation Run must be reconciled first",
                status_code=409,
            )
        if trigger_kind == "manual" and not cost_confirmed:
            raise ActorResilienceError(
                "freshness_cost_confirmation_required",
                "Freshness cost must be confirmed",
                status_code=412,
            )
        if trigger_kind == "manual" and (
            expected_generation is None
            or int(route["generation"]) != int(expected_generation)
        ):
            raise ActorResilienceError(
                "apify_actor_route_generation_conflict",
                "Actor route changed after the freshness plan was shown",
            )
        if trigger_kind == "manual" and (
            approved_max_total_charge_usd is None
            or not math.isclose(
                float(approved_max_total_charge_usd),
                float(plan["max_total_charge_usd"]),
                rel_tol=0.0,
                abs_tol=1e-9,
            )
        ):
            raise ActorResilienceError(
                "freshness_plan_conflict",
                "Freshness cost cap changed after confirmation",
            )
        if trigger_kind == "automatic" and not bool(route["freshness_enabled"]):
            raise ActorResilienceError(
                "freshness_schedule_disabled",
                "Automatic freshness checks are disabled",
                status_code=412,
            )
        now = _utc_now()
        check_id = f"freshness_{uuid.uuid4().hex}"
        reference_slot = int(
            hashlib.sha256(
                f"{self.workspace_id}:{route_id}:{now.date()}".encode()
            ).hexdigest(),
            16,
        ) % 2
        try:
            self.connection.execute(
                """
                INSERT INTO apify_actor_freshness_checks (
                    check_id, workspace_id, route_id, route_generation,
                    trigger_kind,
                    reference_slot, status, planned_count,
                    max_total_charge_usd, request_id, created_by_user_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?)
                """,
                (
                    check_id,
                    self.workspace_id,
                    str(route_id),
                    int(route["generation"]),
                    trigger_kind,
                    reference_slot,
                    int(plan["actor_count"]),
                    float(plan["max_total_charge_usd"]),
                    request_id,
                    actor_user_id,
                    _iso(now),
                    _iso(now),
                ),
            )
            self.connection.commit()
        except sqlite3.IntegrityError as exc:
            self.connection.rollback()
            raise ActorResilienceError(
                "freshness_check_active",
                "A freshness check is already queued or running",
            ) from exc
        self.emit_event(
            route_id=route_id,
            phase="freshness",
            outcome="queued",
            reason_code=trigger_kind,
            request_id=request_id,
        )
        return self.get_freshness_check(check_id)

    def attach_freshness_job(self, check_id: str, job_id: str) -> None:
        cursor = self.connection.execute(
            """
            UPDATE apify_actor_freshness_checks
            SET job_id = ?, updated_at = ?
            WHERE workspace_id = ? AND check_id = ? AND status = 'queued'
            """,
            (str(job_id), _iso(), self.workspace_id, str(check_id)),
        )
        if cursor.rowcount != 1:
            raise ActorResilienceError(
                "freshness_check_not_queued",
                "Freshness check is not queued",
            )
        self.connection.commit()

    def begin_freshness_check(self, check_id: str) -> dict[str, Any]:
        now = _iso()
        row = self.connection.execute(
            """
            SELECT check_row.*, profile.platform, profile.route_key,
                   profile.generation AS current_route_generation,
                   profile.per_run_cap_usd
            FROM apify_actor_freshness_checks AS check_row
            JOIN apify_actor_route_profiles AS profile
              ON profile.workspace_id = check_row.workspace_id
             AND profile.route_id = check_row.route_id
            WHERE check_row.workspace_id = ? AND check_row.check_id = ?
            """,
            (self.workspace_id, str(check_id)),
        ).fetchone()
        if row is None:
            raise ActorResilienceError(
                "freshness_check_not_found",
                "Freshness check not found",
                status_code=404,
            )
        if int(row["route_generation"]) != int(row["current_route_generation"]):
            raise ActorResilienceError(
                "freshness_plan_changed",
                "Actor Route changed after the freshness plan was created",
            )
        cursor = self.connection.execute(
            """
            UPDATE apify_actor_freshness_checks
            SET status = 'running', started_at = COALESCE(started_at, ?),
                updated_at = ?
            WHERE workspace_id = ? AND check_id = ? AND status = 'queued'
            """,
            (now, now, self.workspace_id, str(check_id)),
        )
        if cursor.rowcount != 1:
            raise ActorResilienceError(
                "freshness_check_not_queued",
                "Freshness check is not queued",
            )
        self.connection.execute(
            """
            UPDATE apify_actor_route_profiles
            SET freshness_status = 'running', updated_at = ?
            WHERE workspace_id = ? AND route_id = ?
            """,
            (now, self.workspace_id, str(row["route_id"])),
        )
        self.connection.commit()
        return dict(row)

    def complete_freshness_check(
        self,
        check_id: str,
        *,
        samples: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Persist safe comparison results after one strictly serial round."""

        check = self.connection.execute(
            """
            SELECT check_row.*, profile.freshness_enabled,
                   profile.freshness_interval_hours
            FROM apify_actor_freshness_checks AS check_row
            JOIN apify_actor_route_profiles AS profile
              ON profile.workspace_id = check_row.workspace_id
             AND profile.route_id = check_row.route_id
            WHERE check_row.workspace_id = ? AND check_row.check_id = ?
            """,
            (self.workspace_id, str(check_id)),
        ).fetchone()
        if check is None or str(check["status"]) != "running":
            raise ActorResilienceError(
                "freshness_check_not_running",
                "Freshness check is not running",
            )
        if len(samples) != int(check["planned_count"]):
            raise ValueError("freshness samples must match the bounded plan")
        candidate_ids = [str(item.get("candidate_id") or "") for item in samples]
        if any(not value for value in candidate_ids) or len(set(candidate_ids)) != len(
            candidate_ids
        ):
            raise ValueError("freshness candidates must be unique")

        prepared: list[dict[str, Any]] = []
        for sample in samples:
            latest = _parse_time(sample.get("latest_published_at"))
            item_id = str(sample.get("latest_item_id") or "").strip()
            valid = bool(sample.get("successful")) and latest is not None and bool(
                item_id
            )
            item_hash = hashlib.sha256(item_id.encode()).hexdigest() if item_id else None
            fingerprint = (
                hashlib.sha256(
                    f"{_iso(latest)}:{item_hash}".encode()
                ).hexdigest()
                if valid
                else None
            )
            previous = self.connection.execute(
                """
                SELECT result.*
                FROM apify_actor_freshness_results AS result
                JOIN apify_actor_freshness_checks AS prior
                  ON prior.workspace_id = result.workspace_id
                 AND prior.check_id = result.check_id
                WHERE result.workspace_id = ?
                  AND result.candidate_id = ?
                  AND prior.route_id = ?
                  AND prior.created_at < ?
                ORDER BY prior.created_at DESC, result.updated_at DESC
                LIMIT 1
                """,
                (
                    self.workspace_id,
                    str(sample["candidate_id"]),
                    str(check["route_id"]),
                    str(check["created_at"]),
                ),
            ).fetchone()
            prepared.append(
                {
                    **sample,
                    "valid": valid,
                    "latest": latest,
                    "item_hash": item_hash,
                    "fingerprint": fingerprint,
                    "previous": previous,
                    "status": "failed",
                    "reason_code": _safe_code(
                        sample.get("reason_code"),
                        "freshness_nonempty_required",
                    ),
                }
            )

        valid_samples = [item for item in prepared if item["valid"]]
        if len(valid_samples) == 1:
            valid_samples[0]["status"] = "unverified_single"
            valid_samples[0]["reason_code"] = "cannot_cross_validate"
        elif len(valid_samples) >= 2:
            groups: dict[str, list[dict[str, Any]]] = {}
            for item in valid_samples:
                groups.setdefault(str(item["fingerprint"]), []).append(item)
            largest = max(groups.values(), key=len)
            if len(largest) == len(valid_samples):
                for item in valid_samples:
                    item["status"] = "fresh"
                    item["reason_code"] = "latest_fingerprint_matches"
            elif len(valid_samples) == 3 and len(largest) >= 2:
                majority_latest = max(item["latest"] for item in largest)
                for item in largest:
                    item["status"] = "fresh"
                    item["reason_code"] = "majority_latest_fingerprint"
                for item in valid_samples:
                    if item in largest:
                        continue
                    if item["latest"] < majority_latest:
                        item["status"] = "stale"
                        item["reason_code"] = "behind_majority_latest"
                    else:
                        item["status"] = "suspected_stale"
                        item["reason_code"] = "differs_from_majority"
            elif len(valid_samples) == 2:
                newest = max(item["latest"] for item in valid_samples)
                newest_items = [
                    item for item in valid_samples if item["latest"] == newest
                ]
                if len(newest_items) == 1:
                    newest_items[0]["status"] = "fresh"
                    newest_items[0]["reason_code"] = "newest_observed_result"
                    for item in valid_samples:
                        if item is newest_items[0]:
                            continue
                        item["status"] = "suspected_stale"
                        item["reason_code"] = "behind_peer_latest"
                else:
                    for item in valid_samples:
                        item["status"] = "suspected_stale"
                        item["reason_code"] = "ambiguous_peer_mismatch"
            else:
                for item in valid_samples:
                    item["status"] = "suspected_stale"
                    item["reason_code"] = "ambiguous_peer_mismatch"
        for item in valid_samples:
            if not bool(item.get("timely", True)):
                item["status"] = "stale"
                item["reason_code"] = "outside_reference_window"

        now_dt = _utc_now()
        now = _iso(now_dt)
        route_changed = False
        actual_cost = 0.0
        cost_observed = False
        cost_final = True
        terminal_successes = 0
        for ordinal, item in enumerate(prepared, start=1):
            previous = item["previous"]
            status = str(item["status"])
            prior_stale = int(previous["consecutive_stale_count"] or 0) if previous else 0
            prior_fresh = int(previous["consecutive_fresh_count"] or 0) if previous else 0
            if status == "suspected_stale":
                fresh_count = 0
                if item["reason_code"] in {
                    "behind_peer_latest",
                    "differs_from_majority",
                }:
                    stale_count = min(prior_stale + 1, 2)
                    if stale_count >= 2:
                        status = "stale"
                        item["reason_code"] = "repeated_latest_mismatch"
                else:
                    stale_count = 1
            elif status == "stale":
                stale_count = 2
                fresh_count = 0
            elif status in {"fresh", "unverified_single"}:
                stale_count = 0
                fresh_count = min(prior_fresh + 1, 2)
            else:
                stale_count = 0
                fresh_count = 0
            item["status"] = status
            raw_cost = item.get("actual_cost_usd")
            if isinstance(raw_cost, (int, float)) and not isinstance(raw_cost, bool):
                actual_cost += max(float(raw_cost), 0.0)
                cost_observed = True
            if not bool(item.get("cost_final")):
                cost_final = False
            if status != "failed":
                terminal_successes += 1
            self.connection.execute(
                """
                INSERT INTO apify_actor_freshness_results (
                    workspace_id, check_id, candidate_id, revision_id,
                    ordinal, status, semantic_outcome,
                    latest_published_at, latest_item_id_hash,
                    consecutive_fresh_count, consecutive_stale_count,
                    actual_cost_usd, cost_final, reason_code,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.workspace_id,
                    str(check_id),
                    str(item["candidate_id"]),
                    item.get("revision_id"),
                    ordinal,
                    status,
                    _safe_code(item.get("semantic_outcome"), "unknown"),
                    _iso(item["latest"]) if item["latest"] else None,
                    item["item_hash"],
                    fresh_count,
                    stale_count,
                    raw_cost if isinstance(raw_cost, (int, float)) else None,
                    int(bool(item.get("cost_final"))),
                    _safe_code(item.get("reason_code"), "unknown"),
                    now,
                    now,
                ),
            )
            candidate = self.connection.execute(
                """
                SELECT state, last_error_code FROM apify_actor_candidates
                WHERE workspace_id = ? AND id = ?
                """,
                (self.workspace_id, str(item["candidate_id"])),
            ).fetchone()
            if status == "stale":
                self.connection.execute(
                    """
                    UPDATE apify_actor_candidates
                    SET state = 'open', opened_at = COALESCE(opened_at, ?),
                        failure_count = failure_count + 1,
                        failure_level = failure_level + 1,
                        last_failure_at = ?, last_attempt_at = ?,
                        last_error_code = 'apify_actor_stale_content',
                        updated_at = ?
                    WHERE workspace_id = ? AND id = ?
                    """,
                    (
                        now,
                        now,
                        now,
                        now,
                        self.workspace_id,
                        str(item["candidate_id"]),
                    ),
                )
                self.connection.execute(
                    """
                    UPDATE apify_source_route_bindings
                    SET preference_suspended_at = COALESCE(
                            preference_suspended_at, ?
                        ),
                        preference_recovery_successes = 0,
                        updated_at = ?
                    WHERE workspace_id = ? AND route_id = ?
                      AND preferred_candidate_id = ?
                    """,
                    (
                        now,
                        now,
                        self.workspace_id,
                        str(check["route_id"]),
                        str(item["candidate_id"]),
                    ),
                )
                route_changed = route_changed or bool(
                    candidate is not None and str(candidate["state"]) != "open"
                )
            elif status in {"fresh", "unverified_single"} and fresh_count >= 2:
                if (
                    candidate is not None
                    and str(candidate["state"]) == "open"
                    and str(candidate["last_error_code"] or "")
                    in {
                        "apify_actor_stale_content",
                        "apify_actor_stale_regression",
                    }
                ):
                    self.connection.execute(
                        """
                        UPDATE apify_actor_candidates
                        SET state = 'closed', opened_at = NULL, retry_at = NULL,
                            recovery_successes = 0, last_error_code = NULL,
                            last_success_at = ?, last_attempt_at = ?, updated_at = ?
                        WHERE workspace_id = ? AND id = ?
                        """,
                        (
                            now,
                            now,
                            now,
                            self.workspace_id,
                            str(item["candidate_id"]),
                        ),
                    )
                    route_changed = True
                self.connection.execute(
                    """
                    UPDATE apify_source_route_bindings
                    SET preference_suspended_at = NULL,
                        preference_recovery_successes = 2, updated_at = ?
                    WHERE workspace_id = ? AND route_id = ?
                      AND preferred_candidate_id = ?
                    """,
                    (
                        now,
                        self.workspace_id,
                        str(check["route_id"]),
                        str(item["candidate_id"]),
                    ),
                )

        statuses = {str(item["status"]) for item in prepared}
        if terminal_successes == 0:
            check_status = "failed"
            route_status = "failed"
        elif "failed" in statuses:
            check_status = "partial"
            route_status = "partial"
        elif "stale" in statuses:
            check_status = "succeeded"
            route_status = "stale"
        elif "suspected_stale" in statuses:
            check_status = "succeeded"
            route_status = "suspected_stale"
        elif statuses == {"unverified_single"}:
            check_status = "succeeded"
            route_status = "unverified_single"
        else:
            check_status = "succeeded"
            route_status = "fresh"
        final_cost_value = (
            actual_cost if cost_observed and cost_final else None
        )
        self.connection.execute(
            """
            UPDATE apify_actor_freshness_checks
            SET status = ?, completed_count = ?, actual_cost_usd = ?,
                cost_final = ?, error_code = ?, completed_at = ?, updated_at = ?
            WHERE workspace_id = ? AND check_id = ? AND status = 'running'
            """,
            (
                check_status,
                len(prepared),
                final_cost_value,
                int(final_cost_value is not None),
                "freshness_all_failed" if check_status == "failed" else None,
                now,
                now,
                self.workspace_id,
                str(check_id),
            ),
        )
        next_check = (
            now_dt + timedelta(hours=int(check["freshness_interval_hours"]))
            if bool(check["freshness_enabled"])
            else None
        )
        self.connection.execute(
            """
            UPDATE apify_actor_route_profiles
            SET freshness_last_checked_at = ?, freshness_next_check_at = ?,
                freshness_status = ?, freshness_last_cost_usd = ?,
                generation = generation + ?, updated_at = ?
            WHERE workspace_id = ? AND route_id = ?
            """,
            (
                now,
                _iso(next_check) if next_check else None,
                route_status,
                final_cost_value,
                int(route_changed),
                now,
                self.workspace_id,
                str(check["route_id"]),
            ),
        )
        if route_changed:
            self.connection.execute(
                """
                UPDATE apify_actor_routes
                SET generation = generation + 1, updated_at = ?
                WHERE workspace_id = ? AND route_key = (
                    SELECT route_key FROM apify_actor_route_profiles
                    WHERE workspace_id = ? AND route_id = ?
                )
                """,
                (
                    now,
                    self.workspace_id,
                    self.workspace_id,
                    str(check["route_id"]),
                ),
            )
        self.connection.commit()
        for item in prepared:
            self.emit_event(
                route_id=str(check["route_id"]),
                candidate_id=str(item["candidate_id"]),
                actor_public_name=(
                    str(item.get("actor_public_name"))
                    if item.get("actor_public_name")
                    else None
                ),
                phase="freshness",
                outcome=("failed" if item["status"] in {"failed", "stale"} else "succeeded"),
                reason_code=str(item["reason_code"]),
                final_cost_usd=(
                    item.get("actual_cost_usd")
                    if bool(item.get("cost_final"))
                    else None
                ),
                job_id=check["job_id"],
                request_id=check["request_id"],
            )
        return self.get_freshness_check(str(check_id))

    def fail_freshness_check(self, check_id: str, *, reason_code: str) -> None:
        row = self.connection.execute(
            """
            SELECT check_row.route_id, profile.freshness_enabled,
                   profile.freshness_interval_hours
            FROM apify_actor_freshness_checks AS check_row
            JOIN apify_actor_route_profiles AS profile
              ON profile.workspace_id = check_row.workspace_id
             AND profile.route_id = check_row.route_id
            WHERE check_row.workspace_id = ? AND check_row.check_id = ?
              AND check_row.status IN ('queued', 'running')
            """,
            (self.workspace_id, str(check_id)),
        ).fetchone()
        if row is None:
            return
        now_dt = _utc_now()
        now = _iso(now_dt)
        next_check = (
            now_dt + timedelta(hours=int(row["freshness_interval_hours"]))
            if bool(row["freshness_enabled"])
            else None
        )
        code = _safe_code(reason_code, "freshness_failed")
        self.connection.execute(
            """
            UPDATE apify_actor_freshness_checks
            SET status = 'failed', error_code = ?, completed_at = ?, updated_at = ?
            WHERE workspace_id = ? AND check_id = ?
              AND status IN ('queued', 'running')
            """,
            (code, now, now, self.workspace_id, str(check_id)),
        )
        self.connection.execute(
            """
            UPDATE apify_actor_route_profiles
            SET freshness_status = 'failed', freshness_last_checked_at = ?,
                freshness_next_check_at = ?, updated_at = ?
            WHERE workspace_id = ? AND route_id = ?
            """,
            (
                now,
                _iso(next_check) if next_check else None,
                now,
                self.workspace_id,
                str(row["route_id"]),
            ),
        )
        self.connection.commit()
        self.emit_event(
            route_id=str(row["route_id"]),
            phase="freshness",
            outcome="failed",
            reason_code=code,
        )

    def get_freshness_check(self, check_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            """
            SELECT * FROM apify_actor_freshness_checks
            WHERE workspace_id = ? AND check_id = ?
            """,
            (self.workspace_id, str(check_id)),
        ).fetchone()
        if row is None:
            raise ActorResilienceError(
                "freshness_check_not_found",
                "Freshness check not found",
                status_code=404,
            )
        results = self.connection.execute(
            """
            SELECT result.candidate_id, result.revision_id, result.ordinal,
                   result.status, result.semantic_outcome,
                   result.latest_published_at,
                   result.consecutive_fresh_count,
                   result.consecutive_stale_count,
                   result.actual_cost_usd, result.cost_final,
                   result.reason_code, result.updated_at,
                   candidate.display_name AS actor_public_name
            FROM apify_actor_freshness_results AS result
            JOIN apify_actor_candidates AS candidate
              ON candidate.workspace_id = result.workspace_id
             AND candidate.id = result.candidate_id
            WHERE result.workspace_id = ? AND result.check_id = ?
            ORDER BY result.ordinal
            """,
            (self.workspace_id, str(check_id)),
        ).fetchall()
        return {
            "check_id": str(row["check_id"]),
            "route_id": str(row["route_id"]),
            "trigger_kind": str(row["trigger_kind"]),
            "status": str(row["status"]),
            "planned_count": int(row["planned_count"]),
            "completed_count": int(row["completed_count"]),
            "max_total_charge_usd": float(row["max_total_charge_usd"]),
            "actual_cost_usd": row["actual_cost_usd"],
            "cost_final": bool(row["cost_final"]),
            "job_id": row["job_id"],
            "error_code": row["error_code"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "results": [
                {
                    **{
                        key: result[key]
                        for key in (
                            "candidate_id",
                            "revision_id",
                            "ordinal",
                            "status",
                            "semantic_outcome",
                            "latest_published_at",
                            "consecutive_fresh_count",
                            "consecutive_stale_count",
                            "actual_cost_usd",
                            "reason_code",
                            "updated_at",
                            "actor_public_name",
                        )
                    },
                    "cost_final": bool(result["cost_final"]),
                }
                for result in results
            ],
        }

    def reconcile_terminal_freshness_costs(
        self,
        *,
        limit: int = 100,
    ) -> dict[str, int]:
        """Project finalized validation-Run charges onto freshness evidence.

        The key-pool reconciliation owns remote reads. This method is local,
        idempotent, and never starts or retries an Actor.
        """

        page_size = min(max(int(limit), 1), 300)
        connection = self.connection
        now = _iso()
        rows = connection.execute(
            """
            SELECT result.rowid AS result_rowid, result.check_id,
                   result.candidate_id, check_row.route_id,
                   check_row.request_id, check_row.job_id,
                   actor_run.charge_actual_usd
            FROM apify_actor_freshness_results AS result
            JOIN apify_actor_freshness_checks AS check_row
              ON check_row.workspace_id = result.workspace_id
             AND check_row.check_id = result.check_id
            JOIN apify_actor_runs AS actor_run
              ON actor_run.rowid = (
                  SELECT latest_run.rowid
                  FROM apify_actor_runs AS latest_run
                  WHERE latest_run.workspace_id = result.workspace_id
                    AND latest_run.purpose = 'validation'
                    AND latest_run.logical_run_id = (
                        'freshness:' || result.check_id || ':'
                        || result.candidate_id
                    )
                    AND latest_run.charge_final = 1
                    AND latest_run.charge_actual_usd IS NOT NULL
                  ORDER BY latest_run.updated_at DESC, latest_run.rowid DESC
                  LIMIT 1
              )
            WHERE result.workspace_id = ? AND result.cost_final = 0
            ORDER BY check_row.created_at, result.ordinal
            LIMIT ?
            """,
            (self.workspace_id, page_size),
        ).fetchall()
        updated_results = 0
        check_ids: set[str] = set()
        events: list[dict[str, Any]] = []
        for row in rows:
            actual = float(row["charge_actual_usd"])
            if not math.isfinite(actual) or actual < 0:
                continue
            cursor = connection.execute(
                """
                UPDATE apify_actor_freshness_results
                SET actual_cost_usd = ?, cost_final = 1, updated_at = ?
                WHERE rowid = ? AND workspace_id = ? AND cost_final = 0
                """,
                (
                    actual,
                    now,
                    int(row["result_rowid"]),
                    self.workspace_id,
                ),
            )
            if cursor.rowcount != 1:
                continue
            updated_results += 1
            check_ids.add(str(row["check_id"]))
            events.append(
                {
                    "route_id": str(row["route_id"]),
                    "candidate_id": str(row["candidate_id"]),
                    "final_cost_usd": actual,
                    "request_id": row["request_id"],
                    "job_id": row["job_id"],
                }
            )

        updated_checks = 0
        for check_id in check_ids:
            aggregate = connection.execute(
                """
                SELECT check_row.route_id, check_row.planned_count,
                       COUNT(result.candidate_id) AS result_count,
                       COALESCE(SUM(result.cost_final), 0) AS final_count,
                       COALESCE(SUM(CASE WHEN result.cost_final = 1
                           THEN result.actual_cost_usd ELSE 0 END), 0) AS cost
                FROM apify_actor_freshness_checks AS check_row
                LEFT JOIN apify_actor_freshness_results AS result
                  ON result.workspace_id = check_row.workspace_id
                 AND result.check_id = check_row.check_id
                WHERE check_row.workspace_id = ? AND check_row.check_id = ?
                GROUP BY check_row.check_id
                """,
                (self.workspace_id, check_id),
            ).fetchone()
            if (
                aggregate is None
                or int(aggregate["result_count"] or 0)
                != int(aggregate["planned_count"])
                or int(aggregate["final_count"] or 0)
                != int(aggregate["planned_count"])
            ):
                continue
            actual = float(aggregate["cost"] or 0.0)
            cursor = connection.execute(
                """
                UPDATE apify_actor_freshness_checks
                SET actual_cost_usd = ?, cost_final = 1, updated_at = ?
                WHERE workspace_id = ? AND check_id = ? AND cost_final = 0
                """,
                (actual, now, self.workspace_id, check_id),
            )
            updated_checks += int(cursor.rowcount)
            connection.execute(
                """
                UPDATE apify_actor_route_profiles
                SET freshness_last_cost_usd = ?, updated_at = ?
                WHERE workspace_id = ? AND route_id = ?
                  AND ? = (
                      SELECT latest.check_id
                      FROM apify_actor_freshness_checks AS latest
                      WHERE latest.workspace_id = ?
                        AND latest.route_id = ?
                        AND latest.status IN (
                            'succeeded', 'partial', 'failed', 'cancelled'
                        )
                      ORDER BY COALESCE(
                          latest.completed_at, latest.updated_at
                      ) DESC, latest.check_id DESC
                      LIMIT 1
                  )
                """,
                (
                    actual,
                    now,
                    self.workspace_id,
                    str(aggregate["route_id"]),
                    check_id,
                    self.workspace_id,
                    str(aggregate["route_id"]),
                ),
            )
        if updated_results or updated_checks:
            connection.commit()
        for event in events:
            self.emit_event(
                phase="cost_reconciliation",
                outcome="succeeded",
                reason_code="freshness_cost_finalized",
                **event,
            )
        return {"results": updated_results, "checks": updated_checks}

    def due_routes(self, *, now: datetime | None = None) -> list[str]:
        rows = self.connection.execute(
            """
            SELECT profile.route_id
            FROM apify_actor_route_profiles AS profile
            WHERE profile.workspace_id = ?
              AND profile.freshness_enabled = 1
              AND profile.freshness_next_check_at IS NOT NULL
              AND profile.freshness_next_check_at <= ?
              AND NOT EXISTS (
                  SELECT 1 FROM apify_actor_freshness_checks AS check_row
                  WHERE check_row.workspace_id = profile.workspace_id
                    AND check_row.route_id = profile.route_id
                    AND check_row.status IN ('queued', 'running')
              )
              AND NOT EXISTS (
                  SELECT 1 FROM apify_actor_runs AS actor_run
                  WHERE actor_run.workspace_id = profile.workspace_id
                    AND actor_run.purpose = 'validation'
                    AND actor_run.status IN (
                        'reserved', 'starting', 'running',
                        'start_outcome_unknown'
                    )
              )
            ORDER BY profile.freshness_next_check_at, profile.route_id
            """,
            (self.workspace_id, _iso(now)),
        ).fetchall()
        if not self.validation_key_state()["usable"]:
            changed = self.connection.execute(
                """
                SELECT route_id FROM apify_actor_route_profiles
                WHERE workspace_id = ? AND freshness_enabled = 1
                  AND freshness_status != 'blocked_no_validation_key'
                ORDER BY route_id
                """,
                (self.workspace_id,),
            ).fetchall()
            self.connection.execute(
                """
                UPDATE apify_actor_route_profiles
                SET freshness_status = 'blocked_no_validation_key',
                    updated_at = ?
                WHERE workspace_id = ? AND freshness_enabled = 1
                """,
                (_iso(now), self.workspace_id),
            )
            self.connection.commit()
            for row in changed:
                self.emit_event(
                    route_id=str(row["route_id"]),
                    phase="freshness_schedule",
                    outcome="blocked",
                    reason_code="validation_key_unavailable",
                )
            return []
        return [str(row["route_id"]) for row in rows]

    def set_source_preference(
        self,
        source_id: str,
        *,
        candidate_id: str | None,
        expected_generation: int,
    ) -> dict[str, Any]:
        binding = self.connection.execute(
            """
            SELECT * FROM apify_source_route_bindings
            WHERE workspace_id = ? AND source_id = ?
            """,
            (self.workspace_id, str(source_id)),
        ).fetchone()
        if binding is None:
            raise ActorResilienceError(
                "apify_source_binding_not_found",
                "Source does not have an Actor route binding",
                status_code=404,
            )
        if int(binding["generation"]) != int(expected_generation):
            raise ActorResilienceError(
                "apify_source_binding_generation_conflict",
                "Source route preference changed; reload and retry",
            )
        selected = str(candidate_id or "").strip() or None
        actor_name = None
        preference_suspended_at = None
        if selected is not None:
            candidate = self.connection.execute(
                """
                SELECT candidate.display_name, candidate.state
                FROM apify_actor_candidates AS candidate
                JOIN apify_route_active_slots AS slot
                  ON slot.workspace_id = candidate.workspace_id
                 AND slot.candidate_id = candidate.id
                WHERE candidate.workspace_id = ? AND candidate.id = ?
                  AND slot.route_id = ?
                LIMIT 1
                """,
                (self.workspace_id, selected, str(binding["route_id"])),
            ).fetchone()
            if candidate is None:
                raise ActorResilienceError(
                    "apify_source_preference_invalid",
                    "Preferred Actor is not active for this source route",
                    status_code=400,
                )
            if str(candidate["state"]) == "disabled":
                raise ActorResilienceError(
                    "apify_source_preference_invalid",
                    "Disabled Actor cannot be preferred",
                    status_code=400,
                )
            actor_name = str(candidate["display_name"])
            if (
                str(candidate["state"]) not in {"closed", "probationary"}
                or (
                    str(binding["preferred_candidate_id"] or "") == selected
                    and binding["preference_suspended_at"] is not None
                )
            ):
                preference_suspended_at = _iso()
        cursor = self.connection.execute(
            """
            UPDATE apify_source_route_bindings
            SET preferred_candidate_id = ?, preference_suspended_at = ?,
                preference_recovery_successes = 0,
                generation = generation + 1, updated_at = ?
            WHERE workspace_id = ? AND source_id = ? AND generation = ?
            """,
            (
                selected,
                preference_suspended_at,
                _iso(),
                self.workspace_id,
                str(source_id),
                int(expected_generation),
            ),
        )
        if cursor.rowcount != 1:
            raise ActorResilienceError(
                "apify_source_binding_generation_conflict",
                "Source route preference changed; reload and retry",
            )
        self.connection.commit()
        self.emit_event(
            route_id=str(binding["route_id"]),
            source_id=source_id,
            candidate_id=selected,
            actor_public_name=actor_name,
            phase="source_preference",
            outcome="succeeded",
            reason_code="manual_preference" if selected else "automatic",
        )
        return self.source_preference(source_id)

    def source_preference(self, source_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            """
            SELECT binding.source_id, binding.route_id, binding.generation,
                   binding.preferred_candidate_id,
                   binding.active_candidate_id,
                   binding.preference_suspended_at,
                   binding.preference_recovery_successes,
                   preferred.display_name AS preferred_name,
                   active.display_name AS active_name
            FROM apify_source_route_bindings AS binding
            LEFT JOIN apify_actor_candidates AS preferred
              ON preferred.id = binding.preferred_candidate_id
            LEFT JOIN apify_actor_candidates AS active
              ON active.id = binding.active_candidate_id
            WHERE binding.workspace_id = ? AND binding.source_id = ?
            """,
            (self.workspace_id, str(source_id)),
        ).fetchone()
        if row is None:
            raise ActorResilienceError(
                "apify_source_binding_not_found",
                "Source does not have an Actor route binding",
                status_code=404,
            )
        return {
            "source_id": str(row["source_id"]),
            "route_id": str(row["route_id"]),
            "generation": int(row["generation"]),
            "mode": "manual" if row["preferred_candidate_id"] else "automatic",
            "preferred_candidate_id": row["preferred_candidate_id"],
            "preferred_actor_name": row["preferred_name"],
            "active_candidate_id": row["active_candidate_id"],
            "active_actor_name": row["active_name"],
            "preference_suspended": bool(row["preference_suspended_at"]),
            "preference_recovery_successes": int(
                row["preference_recovery_successes"] or 0
            ),
        }

    def classify_source_result(
        self,
        source_id: str,
        *,
        candidate_id: str,
        latest_published_at: str | None,
        latest_item_id: str | None,
        semantic_outcome: str,
        defer_publication: bool = False,
    ) -> str:
        """Classify only post-filter output against the source watermark."""

        binding = self.connection.execute(
            """
            SELECT * FROM apify_source_route_bindings
            WHERE workspace_id = ? AND source_id = ?
            """,
            (self.workspace_id, str(source_id)),
        ).fetchone()
        if binding is None:
            return semantic_outcome
        latest = _parse_time(latest_published_at)
        watermark = _parse_time(binding["watermark_latest_published_at"])
        latest_item_hash = (
            hashlib.sha256(str(latest_item_id).encode()).hexdigest()
            if latest_item_id
            else None
        )
        if semantic_outcome not in {
            "valid_nonempty",
            "valid_empty",
            "advanced",
            "no_advance",
        }:
            return semantic_outcome
        if latest is not None and watermark is not None and latest < watermark:
            outcome = "stale_regression"
            self.connection.execute(
                """
                UPDATE apify_source_route_bindings
                SET active_candidate_id = ?,
                    preference_suspended_at = CASE
                        WHEN preferred_candidate_id = ? THEN ?
                        ELSE preference_suspended_at END,
                    preference_recovery_successes = 0,
                    updated_at = ?
                WHERE workspace_id = ? AND source_id = ?
                """,
                (
                    str(candidate_id),
                    str(candidate_id),
                    _iso(),
                    _iso(),
                    self.workspace_id,
                    str(source_id),
                ),
            )
        elif (
            latest is not None
            and watermark is not None
            and latest == watermark
            and (
                latest_item_hash is None
                or latest_item_hash == binding["watermark_item_id_hash"]
            )
        ):
            outcome = "no_advance"
            self.connection.execute(
                """
                UPDATE apify_source_route_bindings
                SET active_candidate_id = ?, updated_at = ?
                WHERE workspace_id = ? AND source_id = ?
                """,
                (str(candidate_id), _iso(), self.workspace_id, str(source_id)),
            )
        elif semantic_outcome == "valid_empty":
            outcome = "valid_empty"
            self.connection.execute(
                """
                UPDATE apify_source_route_bindings
                SET active_candidate_id = ?, updated_at = ?
                WHERE workspace_id = ? AND source_id = ?
                """,
                (str(candidate_id), _iso(), self.workspace_id, str(source_id)),
            )
        elif latest is None or semantic_outcome == "no_advance":
            outcome = "no_advance"
            self.connection.execute(
                """
                UPDATE apify_source_route_bindings
                SET active_candidate_id = ?, updated_at = ?
                WHERE workspace_id = ? AND source_id = ?
                """,
                (str(candidate_id), _iso(), self.workspace_id, str(source_id)),
            )
        elif defer_publication:
            outcome = "advanced"
        else:
            outcome = "advanced"
            recovery = (
                min(int(binding["preference_recovery_successes"] or 0) + 1, 2)
                if binding["preferred_candidate_id"] == candidate_id
                else int(binding["preference_recovery_successes"] or 0)
            )
            self.connection.execute(
                """
                UPDATE apify_source_route_bindings
                SET active_candidate_id = ?,
                    watermark_latest_published_at = ?,
                    watermark_item_id_hash = ?,
                    watermark_last_advanced_at = ?,
                    preference_recovery_successes = ?,
                    preference_suspended_at = CASE
                        WHEN preferred_candidate_id = ? AND ? >= 2 THEN NULL
                        ELSE preference_suspended_at END,
                    updated_at = ?
                WHERE workspace_id = ? AND source_id = ?
                """,
                (
                    str(candidate_id),
                    _iso(latest),
                    latest_item_hash,
                    _iso(),
                    recovery,
                    str(candidate_id),
                    recovery,
                    _iso(),
                    self.workspace_id,
                    str(source_id),
                ),
            )
        self.connection.commit()
        self.emit_event(
            route_id=str(binding["route_id"]),
            source_id=source_id,
            candidate_id=candidate_id,
            phase="runtime_freshness",
            outcome="failed" if outcome == "stale_regression" else "succeeded",
            reason_code=outcome,
        )
        return outcome

    def publish_source_advance(
        self,
        source_id: str,
        *,
        candidate_id: str,
        latest_published_at: str,
        latest_item_id_hash: str,
        connection: sqlite3.Connection | None = None,
    ) -> bool:
        """Advance one source watermark inside the caller's publication txn."""

        latest = _parse_time(latest_published_at)
        item_hash = str(latest_item_id_hash or "").strip().casefold()
        if latest is None or not re.fullmatch(r"[a-f0-9]{64}", item_hash):
            raise ActorResilienceError(
                "apify_actor_publication_proof_invalid",
                "Actor publication proof is invalid",
                status_code=422,
            )
        active = connection or self.connection
        owns_transaction = not active.in_transaction
        try:
            if owns_transaction:
                active.execute("BEGIN IMMEDIATE")
            binding = active.execute(
                """
                SELECT * FROM apify_source_route_bindings
                WHERE workspace_id = ? AND source_id = ?
                """,
                (self.workspace_id, str(source_id)),
            ).fetchone()
            if binding is None:
                raise ActorResilienceError(
                    "apify_source_binding_not_found",
                    "Source does not have an Actor route binding",
                    status_code=404,
                )
            active_candidate = active.execute(
                """
                SELECT 1
                FROM apify_route_active_slots AS slot
                JOIN apify_actor_candidates AS candidate
                  ON candidate.workspace_id = slot.workspace_id
                 AND candidate.id = slot.candidate_id
                WHERE slot.workspace_id = ? AND slot.route_id = ?
                  AND slot.candidate_id = ?
                  AND candidate.state IN ('closed', 'half_open', 'probationary')
                LIMIT 1
                """,
                (
                    self.workspace_id,
                    str(binding["route_id"]),
                    str(candidate_id),
                ),
            ).fetchone()
            if active_candidate is None:
                raise ActorResilienceError(
                    "apify_actor_publication_fence_failed",
                    "Actor route changed before source publication",
                )
            watermark = _parse_time(binding["watermark_latest_published_at"])
            if watermark is not None and latest < watermark:
                raise ActorResilienceError(
                    "apify_actor_watermark_advanced",
                    "Source watermark advanced before publication",
                )
            changed = bool(
                watermark is None
                or latest > watermark
                or item_hash != str(binding["watermark_item_id_hash"] or "")
            )
            recovery = int(binding["preference_recovery_successes"] or 0)
            if changed and str(binding["preferred_candidate_id"] or "") == str(
                candidate_id
            ):
                recovery = min(recovery + 1, 2)
            active.execute(
                """
                UPDATE apify_source_route_bindings
                SET active_candidate_id = ?,
                    watermark_latest_published_at = CASE
                        WHEN ? THEN ? ELSE watermark_latest_published_at END,
                    watermark_item_id_hash = CASE
                        WHEN ? THEN ? ELSE watermark_item_id_hash END,
                    watermark_last_advanced_at = CASE
                        WHEN ? THEN ? ELSE watermark_last_advanced_at END,
                    preference_recovery_successes = ?,
                    preference_suspended_at = CASE
                        WHEN preferred_candidate_id = ? AND ? >= 2 THEN NULL
                        ELSE preference_suspended_at END,
                    updated_at = ?
                WHERE workspace_id = ? AND source_id = ?
                """,
                (
                    str(candidate_id),
                    int(changed),
                    _iso(latest),
                    int(changed),
                    item_hash,
                    int(changed),
                    _iso(),
                    recovery,
                    str(candidate_id),
                    recovery,
                    _iso(),
                    self.workspace_id,
                    str(source_id),
                ),
            )
            if owns_transaction:
                active.commit()
            return changed
        except Exception:
            if owns_transaction and active.in_transaction:
                active.rollback()
            raise

    def record_evaluation(
        self,
        *,
        route_id: str,
        candidate_id: str,
        revision_id: str | None,
        evidence_fingerprint: str,
        policy_mode: Literal["standard", "compatibility"],
        stage: str,
        outcome: Literal["passed", "failed", "skipped"],
        reason_code: str,
        deterministic: bool,
    ) -> dict[str, Any]:
        fingerprint = str(evidence_fingerprint).strip().casefold()
        if len(fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in fingerprint
        ):
            raise ValueError("evidence_fingerprint must be sha256")
        now = _iso()
        existing = self.connection.execute(
            """
            SELECT * FROM apify_actor_evaluation_history
            WHERE workspace_id = ? AND route_id = ? AND candidate_id = ?
              AND evidence_fingerprint = ? AND policy_mode = ? AND stage = ?
            """,
            (
                self.workspace_id,
                str(route_id),
                str(candidate_id),
                fingerprint,
                policy_mode,
                _safe_code(stage, "unknown"),
            ),
        ).fetchone()
        if existing is None:
            evaluation_id = f"evaluation_{uuid.uuid4().hex}"
            self.connection.execute(
                """
                INSERT INTO apify_actor_evaluation_history (
                    evaluation_id, workspace_id, route_id, candidate_id,
                    revision_id, evidence_fingerprint, policy_mode, stage,
                    outcome, reason_code, deterministic, attempt_count,
                    first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    evaluation_id,
                    self.workspace_id,
                    str(route_id),
                    str(candidate_id),
                    revision_id,
                    fingerprint,
                    policy_mode,
                    _safe_code(stage, "unknown"),
                    outcome,
                    _safe_code(reason_code, "evaluation_failed"),
                    int(deterministic),
                    now,
                    now,
                ),
            )
        else:
            evaluation_id = str(existing["evaluation_id"])
            self.connection.execute(
                """
                UPDATE apify_actor_evaluation_history
                SET revision_id = COALESCE(?, revision_id), outcome = ?,
                    reason_code = ?, deterministic = ?,
                    attempt_count = attempt_count + 1,
                    retry_requested_at = NULL,
                    retry_requested_by_user_id = NULL,
                    last_seen_at = ?
                WHERE evaluation_id = ?
                """,
                (
                    revision_id,
                    outcome,
                    _safe_code(reason_code, "evaluation_failed"),
                    int(deterministic),
                    now,
                    evaluation_id,
                ),
            )
        self.connection.commit()
        row = self.connection.execute(
            "SELECT * FROM apify_actor_evaluation_history WHERE evaluation_id = ?",
            (evaluation_id,),
        ).fetchone()
        return dict(row) if row is not None else {}

    def deterministic_failure(
        self,
        *,
        route_id: str,
        candidate_id: str,
        evidence_fingerprint: str,
        policy_mode: str,
        stage: str,
    ) -> dict[str, Any] | None:
        row = self.connection.execute(
            """
            SELECT * FROM apify_actor_evaluation_history
            WHERE workspace_id = ? AND route_id = ? AND candidate_id = ?
              AND evidence_fingerprint = ? AND policy_mode = ? AND stage = ?
              AND outcome = 'failed' AND deterministic = 1
              AND retry_requested_at IS NULL
            """,
            (
                self.workspace_id,
                str(route_id),
                str(candidate_id),
                str(evidence_fingerprint),
                str(policy_mode),
                _safe_code(stage, "unknown"),
            ),
        ).fetchone()
        return dict(row) if row is not None else None

    def retry_evaluation_once(
        self,
        evaluation_id: str,
        *,
        actor_user_id: str,
    ) -> dict[str, Any]:
        cursor = self.connection.execute(
            """
            UPDATE apify_actor_evaluation_history
            SET retry_requested_at = ?, retry_requested_by_user_id = ?
            WHERE workspace_id = ? AND evaluation_id = ?
              AND outcome = 'failed' AND retry_requested_at IS NULL
              AND attempt_count = 1
            """,
            (_iso(), str(actor_user_id), self.workspace_id, str(evaluation_id)),
        )
        if cursor.rowcount != 1:
            raise ActorResilienceError(
                "evaluation_retry_unavailable",
                "This evaluation cannot be retried again",
                status_code=412,
            )
        self.connection.commit()
        row = self.connection.execute(
            "SELECT * FROM apify_actor_evaluation_history WHERE evaluation_id = ?",
            (str(evaluation_id),),
        ).fetchone()
        result = dict(row) if row is not None else {}
        if result:
            self.emit_event(
                route_id=str(result["route_id"]),
                candidate_id=str(result["candidate_id"]),
                phase="evaluation_retry",
                outcome="succeeded",
                reason_code="manual_retry_once",
            )
        return result

    def emit_event(
        self,
        *,
        phase: str,
        outcome: str,
        reason_code: str | None = None,
        route_id: str | None = None,
        source_id: str | None = None,
        candidate_id: str | None = None,
        actor_public_name: str | None = None,
        occurrence_count: int = 1,
        final_cost_usd: float | None = None,
        request_id: str | None = None,
        job_id: str | None = None,
    ) -> bool:
        safe_phase = _safe_code(phase, "unknown")
        safe_outcome = _safe_code(outcome, "unknown")
        safe_reason = _safe_code(reason_code, "unknown") if reason_code else None
        event_id = f"actor_event_{uuid.uuid4().hex}"
        public_actor_name = (
            str(actor_public_name).strip()[:120]
            if actor_public_name and str(actor_public_name).strip()
            else None
        )
        if candidate_id:
            candidate = self.connection.execute(
                """
                SELECT display_name FROM apify_actor_candidates
                WHERE workspace_id = ? AND id = ?
                """,
                (self.workspace_id, str(candidate_id)),
            ).fetchone()
            if candidate is not None:
                public_actor_name = (
                    str(candidate["display_name"] or "").strip()[:120] or None
                )
        owns_transaction = not self.connection.in_transaction
        try:
            self.connection.execute(
                """
                INSERT INTO apify_actor_diagnostic_events (
                    event_id, workspace_id, route_id, source_id,
                    candidate_id, actor_public_name, phase, outcome,
                    reason_code, occurrence_count, final_cost_usd,
                    request_id, job_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    self.workspace_id,
                    route_id,
                    source_id,
                    candidate_id,
                    public_actor_name,
                    safe_phase,
                    safe_outcome,
                    safe_reason,
                    max(int(occurrence_count), 1),
                    (
                        max(float(final_cost_usd), 0.0)
                        if final_cost_usd is not None
                        and math.isfinite(float(final_cost_usd))
                        else None
                    ),
                    request_id,
                    job_id,
                    _iso(),
                ),
            )
            cutoff = _iso(_utc_now() - timedelta(days=DIAGNOSTIC_RETENTION_DAYS))
            self.connection.execute(
                """
                DELETE FROM apify_actor_diagnostic_events
                WHERE rowid IN (
                    SELECT rowid FROM apify_actor_diagnostic_events
                    WHERE workspace_id = ? AND created_at < ?
                    ORDER BY created_at, event_id
                    LIMIT 500
                )
                """,
                (self.workspace_id, cutoff),
            )
            if owns_transaction:
                self.connection.commit()
        except Exception:
            if owns_transaction and self.connection.in_transaction:
                self.connection.rollback()
            return False
        operation_outcome = (
            safe_outcome
            if safe_outcome
            in {
                "ok",
                "queued",
                "running",
                "succeeded",
                "partial",
                "failed",
                "cancelled",
                "retried",
                "skipped",
                "unavailable",
            }
            else "ok"
        )
        safe_emit_operation_event(
            category="acquisition",
            action="actor_ops_event",
            outcome=operation_outcome,
            level="error" if operation_outcome == "failed" else "info",
            workspace_id=self.workspace_id,
            request_id=request_id,
            job_id=job_id,
            source_id=source_id,
            stage=safe_phase,
            error_code=(safe_reason if operation_outcome == "failed" else None),
            counts={"occurrences": max(int(occurrence_count), 1)},
        )
        return True

    def list_events(
        self,
        *,
        route_id: str | None = None,
        source_id: str | None = None,
        candidate_id: str | None = None,
        phase: str | None = None,
        outcome: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        page_size = min(max(int(limit), 1), 100)
        now = _utc_now()
        lower = _parse_time(since) if since is not None else now - timedelta(hours=24)
        upper = _parse_time(until) if until is not None else now
        if lower is None or upper is None:
            raise ActorResilienceError(
                "invalid_time_range",
                "Diagnostic time range must use valid ISO timestamps",
                status_code=400,
            )
        if lower > upper:
            raise ActorResilienceError(
                "invalid_time_range",
                "Diagnostic start time must not exceed end time",
                status_code=400,
            )
        retention_cutoff = now - timedelta(days=DIAGNOSTIC_RETENTION_DAYS)
        if lower < retention_cutoff:
            if lower >= retention_cutoff - timedelta(minutes=1):
                # A browser-calculated 30-day boundary ages slightly while
                # the request is in flight; clamp that harmless clock skew.
                lower = retention_cutoff
            else:
                raise ActorResilienceError(
                    "diagnostic_range_too_old",
                    "ActorOps diagnostics are retained for 30 days",
                    status_code=400,
                )
        clauses = [
            "event.workspace_id = ?",
            "event.created_at >= ?",
            "event.created_at <= ?",
        ]
        parameters: list[Any] = [self.workspace_id, _iso(lower), _iso(upper)]
        for column, value in (
            ("route_id", route_id),
            ("source_id", source_id),
            ("candidate_id", candidate_id),
            ("phase", phase),
            ("outcome", outcome),
        ):
            if value:
                clauses.append(f"event.{column} = ?")
                parameters.append(str(value))
        if cursor:
            cursor_time, cursor_id = _decode_cursor(cursor)
            clauses.append(
                "(event.created_at < ? OR "
                "(event.created_at = ? AND event.event_id < ?))"
            )
            parameters.extend((cursor_time, cursor_time, cursor_id))
        rows = self.connection.execute(
            f"""
            SELECT event.event_id, event.route_id, event.source_id,
                   event.candidate_id, event.actor_public_name,
                   event.phase, event.outcome, event.reason_code,
                   event.occurrence_count, event.final_cost_usd,
                   event.request_id, event.job_id, event.created_at
            FROM apify_actor_diagnostic_events AS event
            WHERE {' AND '.join(clauses)}
            ORDER BY event.created_at DESC, event.event_id DESC
            LIMIT ?
            """,
            (*parameters, page_size + 1),
        ).fetchall()
        has_more = len(rows) > page_size
        page = rows[:page_size]
        next_cursor = None
        if has_more and page:
            next_cursor = _encode_cursor(
                str(page[-1]["created_at"]), str(page[-1]["event_id"])
            )
        return {
            "schema_version": 1,
            "events": [dict(row) for row in page],
            "next_cursor": next_cursor,
            "retention_days": DIAGNOSTIC_RETENTION_DAYS,
        }


__all__ = [
    "ActorResilienceError",
    "ApifyActorResilienceService",
    "DIAGNOSTIC_RETENTION_DAYS",
    "FRESHNESS_DEFAULT_HOURS",
    "FRESHNESS_MAX_HOURS",
    "FRESHNESS_MIN_HOURS",
    "FRESHNESS_PER_ACTOR_CAP_USD",
]
