"""Safe, summary-only backfill from the active ActorOps v1 schema."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone


LEGACY_BACKFILL_TABLES = (
    "apify_actor_route_profiles",
    "apify_actor_candidates",
    "apify_actor_adapter_revisions",
    "apify_route_active_slots",
    "apify_source_route_bindings",
    "apify_actor_attempts",
)


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _policy_id(workspace_id: str, route_id: str | None) -> str:
    digest = hashlib.sha256(
        f"{workspace_id}:{route_id or 'workspace'}".encode("utf-8")
    ).hexdigest()[:24]
    return f"actorops-v2-policy-{digest}"


def legacy_fingerprints(connection: sqlite3.Connection) -> dict[str, str]:
    fingerprints: dict[str, str] = {}
    for table in LEGACY_BACKFILL_TABLES:
        digest = hashlib.sha256()
        schema = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        digest.update(str(schema[0] if schema else "").encode("utf-8"))
        for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid"):
            digest.update(repr(tuple(row)).encode("utf-8"))
        fingerprints[table] = digest.hexdigest()
    return fingerprints


def _mapped_lifecycle(value: object) -> str:
    raw = str(value or "").strip()
    if raw == "legacy_builtin":
        return "mapping_pending"
    if raw in {
        "proposed", "static_valid", "probationary", "certified",
        "quarantined", "superseded", "rejected",
    }:
        return "discovered" if raw == "proposed" else raw
    return "rejected"


def _attempt_evidence(
    connection: sqlite3.Connection,
) -> tuple[dict[str, dict[str, object]], dict[tuple[str, str], dict[str, object]]]:
    by_revision: dict[str, dict[str, object]] = {}
    by_source_revision: dict[tuple[str, str], dict[str, object]] = {}
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(apify_actor_attempts)")
    }
    if not {"adapter_revision_id", "target_fingerprint"} <= columns:
        return by_revision, by_source_revision
    rows = connection.execute(
        """SELECT adapter_revision_id, source_id, status, terminal_at,
                  last_error_code, target_fingerprint
           FROM apify_actor_attempts
           WHERE adapter_revision_id IS NOT NULL
             AND status IN ('succeeded','failed','cancelled')
           ORDER BY COALESCE(terminal_at, updated_at), id"""
    ).fetchall()
    for row in rows:
        revision_id = str(row["adapter_revision_id"])
        stamp = row["terminal_at"]
        item = by_revision.setdefault(revision_id, {})
        if str(row["status"]) == "succeeded":
            item["last_success_at"] = stamp
        elif str(row["status"]) == "failed":
            item["last_failure_at"] = stamp
            item["last_error_code"] = row["last_error_code"]
        if row["source_id"] is not None and str(row["status"]) == "succeeded":
            by_source_revision[(str(row["source_id"]), revision_id)] = {
                "last_success_at": stamp,
                "target_fingerprint": row["target_fingerprint"],
            }
    return by_revision, by_source_revision


def _backfill_routes(connection: sqlite3.Connection, stamp: str) -> int:
    cursor = connection.execute(
        """INSERT INTO actor_routes_v2 (
               route_id, workspace_id, platform, target_type, capability,
               runtime_mode, per_run_cap_usd, generation,
               source_v1_generation, created_at, updated_at
           ) SELECT route_id, workspace_id, platform, target_type, capability,
                    'disabled', per_run_cap_usd, 1, generation, ?, ?
             FROM apify_actor_route_profiles""",
        (stamp, stamp),
    )
    return int(cursor.rowcount)


def _candidate_rows(connection: sqlite3.Connection):
    return connection.execute(
        """SELECT revision.*, candidate.route_key, profile.route_id,
                  slot.slot_name
           FROM apify_actor_adapter_revisions AS revision
           JOIN apify_actor_candidates AS candidate
             ON candidate.workspace_id = revision.workspace_id
            AND candidate.id = revision.candidate_id
           JOIN apify_actor_route_profiles AS profile
             ON profile.workspace_id = candidate.workspace_id
            AND profile.route_key = candidate.route_key
           LEFT JOIN apify_route_active_slots AS slot
             ON slot.workspace_id = profile.workspace_id
            AND slot.route_id = profile.route_id
            AND slot.revision_id = revision.revision_id
           ORDER BY revision.workspace_id, revision.revision_id"""
    ).fetchall()


def _backfill_candidates(
    connection: sqlite3.Connection,
    stamp: str,
    evidence: dict[str, dict[str, object]],
) -> tuple[int, dict[tuple[str, str], str]]:
    assigned: dict[tuple[str, str], str] = {}
    count = 0
    for row in _candidate_rows(connection):
        lifecycle = _mapped_lifecycle(row["lifecycle"])
        runnable = bool(
            lifecycle in {"probationary", "certified"}
            and row["build_id"]
            and row["manifest_hash"]
        )
        slot = str(row["slot_name"] or "") if runnable else ""
        role = "active" if slot == "primary" else "standby" if slot else "inactive"
        priority = 0 if slot == "primary" else 1 if slot == "backup_1" else 2 if slot == "backup_2" else None
        item = evidence.get(str(row["revision_id"]), {})
        connection.execute(
            """INSERT INTO actor_candidates_v2 (
                   candidate_id, workspace_id, route_id, actor_id, publisher,
                   build_id, build_number, manifest_json, manifest_hash,
                   input_schema_hash, output_schema_hash, lifecycle,
                   assignment_role, priority, generation, last_success_at,
                   last_failure_at, last_error_class, last_error_code,
                   created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1,
                         ?, ?, ?, ?, ?, ?)""",
            (
                row["revision_id"], row["workspace_id"], row["route_id"],
                row["actor_id"], row["publisher"], row["build_id"],
                row["build_number"], row["manifest_json"], row["manifest_hash"],
                row["input_schema_hash"], row["output_schema_hash"], lifecycle,
                role, priority, item.get("last_success_at"),
                item.get("last_failure_at"),
                "candidate" if item.get("last_error_code") else None,
                item.get("last_error_code"), row["created_at"] or stamp, stamp,
            ),
        )
        if role != "inactive":
            assigned[(str(row["route_id"]), str(row["candidate_id"]))] = str(
                row["revision_id"]
            )
        count += 1
    return count, assigned


def _backfill_bindings(
    connection: sqlite3.Connection,
    stamp: str,
    assigned: dict[tuple[str, str], str],
    source_evidence: dict[tuple[str, str], dict[str, object]],
) -> int:
    count = 0
    for row in connection.execute(
        "SELECT * FROM apify_source_route_bindings ORDER BY workspace_id, binding_id"
    ):
        preferred = assigned.get((str(row["route_id"]), str(row["preferred_candidate_id"] or "")))
        active = assigned.get((str(row["route_id"]), str(row["active_candidate_id"] or "")))
        proof = source_evidence.get((str(row["source_id"]), str(active or "")))
        if not proof or str(proof.get("target_fingerprint") or "") != str(row["target_fingerprint"]):
            active = None
            proof = None
        preferred_proof = source_evidence.get(
            (str(row["source_id"]), str(preferred or ""))
        )
        if not preferred_proof or str(
            preferred_proof.get("target_fingerprint") or ""
        ) != str(row["target_fingerprint"]):
            preferred = None
        validation = str(row["validation_status"] or "")
        status = "ready" if validation.startswith("ready_") and active else "pending"
        connection.execute(
            """INSERT INTO actor_source_bindings_v2 (
                   binding_id, workspace_id, source_id, route_id,
                   target_fingerprint, status, binding_version,
                   source_v1_generation, preferred_candidate_id,
                   last_known_good_candidate_id, last_success_at,
                   watermark_latest_published_at, watermark_item_id_hash,
                   watermark_last_advanced_at, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["binding_id"], row["workspace_id"], row["source_id"],
                row["route_id"], row["target_fingerprint"], status,
                row["generation"], preferred, active,
                proof.get("last_success_at") if proof else None,
                row["watermark_latest_published_at"], row["watermark_item_id_hash"],
                row["watermark_last_advanced_at"], row["created_at"] or stamp, stamp,
            ),
        )
        count += 1
    return count


def _backfill_policies(connection: sqlite3.Connection, stamp: str) -> int:
    count = 0
    for row in connection.execute("SELECT id FROM workspaces ORDER BY id"):
        workspace_id = str(row["id"])
        connection.execute(
            """INSERT INTO actor_maintenance_policies_v2 (
                   policy_id, workspace_id, route_id, enabled,
                   monthly_budget_usd, generation, created_at, updated_at
               ) VALUES (?, ?, NULL, 0, 3.0, 1, ?, ?)""",
            (_policy_id(workspace_id, None), workspace_id, stamp, stamp),
        )
        count += 1
    for row in connection.execute(
        "SELECT workspace_id, route_id FROM actor_routes_v2 ORDER BY workspace_id, route_id"
    ):
        workspace_id, route_id = str(row["workspace_id"]), str(row["route_id"])
        connection.execute(
            """INSERT INTO actor_maintenance_policies_v2 (
                   policy_id, workspace_id, route_id, enabled,
                   max_probe_usd, max_probes_per_utc_day,
                   auto_add_standby, auto_replace_non_last,
                   generation, created_at, updated_at
               ) VALUES (?, ?, ?, 0, 0.05, 5, 1, 1, 1, ?, ?)""",
            (_policy_id(workspace_id, route_id), workspace_id, route_id, stamp, stamp),
        )
        count += 1
    return count


def backfill_v1(connection: sqlite3.Connection) -> dict[str, int]:
    stamp = _stamp()
    evidence, source_evidence = _attempt_evidence(connection)
    routes = _backfill_routes(connection, stamp)
    candidates, assigned = _backfill_candidates(connection, stamp, evidence)
    bindings = _backfill_bindings(
        connection, stamp, assigned, source_evidence
    )
    policies = _backfill_policies(connection, stamp)
    return {
        "routes": routes,
        "candidates": candidates,
        "bindings": bindings,
        "policies": policies,
    }
