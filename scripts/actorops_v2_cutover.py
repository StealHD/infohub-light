#!/usr/bin/env python3
"""Offline, fail-closed route cutover controls for ActorOps v2."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.actorops_migration_safety import active_workers_fail_closed
from scripts.migrate_apify_actor_ops_v15 import _backup_database
from src.services.actorops.domain import RuntimeMode
from src.services.actorops.repository import ActorOpsRepository
from src.services.actorops.repository_cutover import route_mode_transition_allowed
from src.storage.actorops_v2_schema import migration_marker_exists, schema_shapes_valid
from src.storage.service_store import DEFAULT_WORKSPACE_ID


class CutoverError(RuntimeError):
    pass


def _database(data_dir: Path) -> Path:
    database = data_dir / "service.db"
    if not database.is_file():
        raise CutoverError("service database does not exist")
    return database


def _connect(database: Path, *, read_only: bool) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"file:{database}?mode=ro" if read_only else database,
        uri=read_only,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _route_row(
    connection: sqlite3.Connection, workspace_id: str, platform: str
) -> sqlite3.Row:
    rows = connection.execute(
        """SELECT * FROM actor_routes_v2
           WHERE workspace_id=? AND platform=?
           ORDER BY target_type, capability, route_id""",
        (workspace_id, platform.strip().casefold()),
    ).fetchall()
    if len(rows) != 1:
        raise CutoverError("cutover requires exactly one Route for this platform")
    return rows[0]


def _scalar(connection: sqlite3.Connection, query: str, values: tuple[Any, ...]) -> float:
    return float(connection.execute(query, values).fetchone()[0] or 0)


def _legacy_summary(
    connection: sqlite3.Connection, workspace_id: str, route: sqlite3.Row
) -> dict[str, Any]:
    route_id = str(route["route_id"])
    profile = connection.execute(
        """SELECT generation FROM apify_actor_route_profiles
           WHERE workspace_id=? AND route_id=?""",
        (workspace_id, route_id),
    ).fetchone()
    slots = connection.execute(
        """SELECT slot_name, revision_id FROM apify_route_active_slots
           WHERE workspace_id=? AND route_id=? AND revision_id IS NOT NULL
           ORDER BY slot_name""",
        (workspace_id, route_id),
    ).fetchall()
    roles = connection.execute(
        """SELECT assignment_role, candidate_id FROM actor_candidates_v2
           WHERE workspace_id=? AND route_id=?
             AND assignment_role IN ('active','standby')
           ORDER BY assignment_role, priority""",
        (workspace_id, route_id),
    ).fetchall()
    expected = {
        "primary" if row["slot_name"] == "primary" else str(row["slot_name"]): str(row["revision_id"])
        for row in slots
    }
    actual: dict[str, str] = {}
    standby = 0
    for row in roles:
        if str(row["assignment_role"]) == "active":
            actual["primary"] = str(row["candidate_id"])
        else:
            standby += 1
            actual[f"backup_{standby}"] = str(row["candidate_id"])
    legacy_bindings = connection.execute(
        """SELECT binding_id, target_fingerprint, generation
           FROM apify_source_route_bindings
           WHERE workspace_id=? AND route_id=? ORDER BY binding_id""",
        (workspace_id, route_id),
    ).fetchall()
    v2_bindings = {
        str(row["binding_id"]): row
        for row in connection.execute(
            """SELECT binding_id, target_fingerprint, source_v1_generation
               FROM actor_source_bindings_v2
               WHERE workspace_id=? AND route_id=?""",
            (workspace_id, route_id),
        ).fetchall()
    }
    slot_mismatches = sum(actual.get(name) != revision for name, revision in expected.items())
    slot_mismatches += sum(name not in expected for name in actual)
    binding_mismatches = sum(
        binding_id not in v2_bindings
        or str(v2_bindings[binding_id]["target_fingerprint"]) != str(row["target_fingerprint"])
        or int(v2_bindings[binding_id]["source_v1_generation"]) != int(row["generation"])
        for row in legacy_bindings
        for binding_id in (str(row["binding_id"]),)
    )
    binding_mismatches += sum(
        binding_id not in {str(row["binding_id"]) for row in legacy_bindings}
        for binding_id in v2_bindings
    )
    route_matches = bool(profile) and int(route["source_v1_generation"]) == int(profile["generation"])
    return {
        "route_generation_matches": route_matches,
        "slot_count": len(expected),
        "slot_mismatches": slot_mismatches,
        "binding_count": len(legacy_bindings),
        "binding_mismatches": binding_mismatches,
        "compatible": route_matches and not slot_mismatches and not binding_mismatches,
    }


def _schema_report(connection: sqlite3.Connection) -> dict[str, bool]:
    return {"marker_valid": migration_marker_exists(connection), "shape_valid": schema_shapes_valid(connection)}


def status(
    data_dir: Path,
    *,
    platform: str,
    workspace_id: str = DEFAULT_WORKSPACE_ID,
) -> dict[str, Any]:
    """Read safe cutover state without exposing targets, secrets, or manifests."""

    connection = _connect(_database(data_dir), read_only=True)
    try:
        schema = _schema_report(connection)
        if not all(schema.values()):
            return {
                "status": "blocked",
                "schema": schema,
                "error": "actorops_v2_schema_not_ready",
                "global_25_ignored": True,
            }
        route = _route_row(connection, workspace_id, platform)
        repository = ActorOpsRepository(connection, workspace_id)
        route_id = str(route["route_id"])
        candidate_rows = connection.execute(
            """SELECT candidate_id, assignment_role, priority, lifecycle, build_id, manifest_hash
               FROM actor_candidates_v2 WHERE workspace_id=? AND route_id=?
               ORDER BY CASE assignment_role WHEN 'active' THEN 0 WHEN 'standby' THEN 1 ELSE 2 END,
                        priority, candidate_id""",
            (workspace_id, route_id),
        ).fetchall()
        runnable = [
            row for row in candidate_rows
            if str(row["assignment_role"]) in {"active", "standby"}
            and str(row["lifecycle"]) in {"probationary", "certified"}
            and row["build_id"] and row["manifest_hash"]
        ]
        bindings = connection.execute(
            """SELECT status, COUNT(*) AS count FROM actor_source_bindings_v2
               WHERE workspace_id=? AND route_id=? GROUP BY status""",
            (workspace_id, route_id),
        ).fetchall()
        binding_counts = {str(row["status"]): int(row["count"]) for row in bindings}
        legacy = _legacy_summary(connection, workspace_id, route)
        blockers = repository.cutover_blockers(route_id)
        ready_bindings = binding_counts.get("ready", 0)
        total_bindings = sum(binding_counts.values())
        ready = bool(runnable and total_bindings) and total_bindings == ready_bindings and legacy["compatible"]
        return {
            "status": "ready" if ready and not any(blockers.values()) else "blocked",
            "schema": schema,
            "route": {
                "route_id": route_id,
                "runtime_mode": str(route["runtime_mode"]),
                "generation": int(route["generation"]),
                "per_run_cap_usd": float(route["per_run_cap_usd"]),
            },
            "health": repository.route_health(route_id).value,
            "candidate_order": [
                {"candidate_id": str(row["candidate_id"]), "assignment": str(row["assignment_role"]), "priority": row["priority"]}
                for row in runnable
            ],
            "runnable_candidate_count": len(runnable),
            "binding_counts": {"total": total_bindings, "ready": ready_bindings, **binding_counts},
            "blocker_counts": blockers,
            "costs": {
                "reserved_unsettled_usd": _scalar(
                    connection,
                    """SELECT COALESCE(SUM(reserved_usd), 0) FROM actor_attempts_v2
                       WHERE workspace_id=? AND route_id=? AND cost_final=0""",
                    (workspace_id, route_id),
                ),
                "actual_usd": _scalar(
                    connection,
                    """SELECT COALESCE(SUM(actual_cost_usd), 0) FROM actor_attempts_v2
                       WHERE workspace_id=? AND route_id=?""",
                    (workspace_id, route_id),
                ),
            },
            "legacy_v1_v2": legacy,
            "global_25_ignored": True,
        }
    finally:
        connection.close()


def snapshot(
    data_dir: Path,
    *,
    platform: str,
    workspace_id: str = DEFAULT_WORKSPACE_ID,
    backup_dir: Path | None = None,
) -> dict[str, Any]:
    """Create a private SQLite backup and a safe route summary for an operator."""

    database = _database(data_dir)
    if active_workers_fail_closed(database):
        raise CutoverError("stop API and Worker before creating a cutover snapshot")
    report = status(data_dir, platform=platform, workspace_id=workspace_id)
    if not report["schema"]["marker_valid"] or not report["schema"]["shape_valid"]:
        raise CutoverError("ActorOps v2 schema is not valid")
    raw_backup = _backup_database(database, backup_dir or data_dir / "backups")
    backup = raw_backup.with_name(raw_backup.name.replace("v15", "v2-cutover", 1))
    raw_backup.replace(backup)
    os.chmod(backup, 0o600)
    digest = hashlib.sha256(json.dumps(report, sort_keys=True).encode("utf-8")).hexdigest()
    evidence = backup.with_suffix(".json")
    evidence.write_text(json.dumps({"report": report, "sha256": digest}, sort_keys=True) + "\n")
    os.chmod(evidence, 0o600)
    return {"status": "snapshotted", "backup": str(backup), "evidence": str(evidence), "mode": "0600"}


def transition(
    data_dir: Path,
    *,
    platform: str,
    current: RuntimeMode,
    target: RuntimeMode,
    expected_generation: int,
    apply: bool,
    workspace_id: str = DEFAULT_WORKSPACE_ID,
) -> dict[str, Any]:
    """Propose or atomically apply a route-local, one-step mode change."""

    report = status(data_dir, platform=platform, workspace_id=workspace_id)
    route = report.get("route")
    if not route or not route_mode_transition_allowed(current, target):
        raise CutoverError("route mode transition is invalid")
    if route["runtime_mode"] != current.value or int(route["generation"]) != expected_generation:
        raise CutoverError("route mode or generation changed before transition")
    forward = (current, target) in {
        (RuntimeMode.DISABLED, RuntimeMode.SHADOW),
        (RuntimeMode.SHADOW, RuntimeMode.ACTIVE),
    }
    workers = active_workers_fail_closed(_database(data_dir))
    if workers:
        raise CutoverError("stop API and Worker before changing route mode")
    if forward and (
        report["status"] != "ready" or any(report["blocker_counts"].values())
    ):
        raise CutoverError("route is not ready for a forward cutover")
    proposal = {
        "status": "applied" if apply else "dry_run",
        "route_id": route["route_id"],
        "current": current.value,
        "target": target.value,
        "expected_generation": expected_generation,
        "authorization_cap_usd": round(
            20 * int(report["runnable_candidate_count"]) * float(route["per_run_cap_usd"]), 2
        ),
    }
    if not apply:
        return proposal
    connection = _connect(_database(data_dir), read_only=False)
    try:
        repository = ActorOpsRepository(connection, workspace_id)
        with repository.transaction():
            changed = repository.transition_route_mode(
                str(route["route_id"]),
                current=current,
                target=target,
                expected_generation=expected_generation,
            )
        proposal["generation"] = changed.generation
        return proposal
    finally:
        connection.close()


def verify(
    data_dir: Path,
    *,
    platform: str,
    expected_mode: RuntimeMode,
    required_successes: int,
    workspace_id: str = DEFAULT_WORKSPACE_ID,
) -> dict[str, Any]:
    """Verify only persisted safe facts; it never calls a provider or publishes."""

    report = status(data_dir, platform=platform, workspace_id=workspace_id)
    route = report.get("route")
    if not route or route["runtime_mode"] != expected_mode.value:
        return {"status": "blocked", "error": "route_mode_mismatch", "report": report}
    connection = _connect(_database(data_dir), read_only=True)
    try:
        count = int(connection.execute(
            """SELECT COUNT(DISTINCT attempt_group_id) FROM actor_attempts_v2
               WHERE workspace_id=? AND route_id=? AND kind='fetch'
                 AND status='succeeded'
                 AND semantic_outcome IN ('valid_nonempty','valid_empty','advanced','no_advance')""",
            (workspace_id, route["route_id"]),
        ).fetchone()[0])
    finally:
        connection.close()
    expected_zero_attempts = expected_mode is RuntimeMode.SHADOW
    passed = (
        not any(report["blocker_counts"].values())
        and (count == 0 if expected_zero_attempts else count >= required_successes)
    )
    return {
        "status": "verified" if passed else "blocked",
        "successful_fetches": count,
        "required_successes": 0 if expected_zero_attempts else required_successes,
        "authorization_cap_usd": round(
            20 * int(report["runnable_candidate_count"]) * float(route["per_run_cap_usd"]), 2
        ),
        "report": report,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=REPOSITORY_ROOT / "data")
    parser.add_argument("--workspace-id", default=DEFAULT_WORKSPACE_ID)
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "snapshot", "verify-shadow", "verify-active"):
        command = subcommands.add_parser(name)
        command.add_argument("--platform", required=True, choices=("youtube", "instagram", "x"))
    change = subcommands.add_parser("transition")
    change.add_argument("--platform", required=True, choices=("youtube", "instagram", "x"))
    change.add_argument("--current", required=True, choices=[mode.value for mode in RuntimeMode])
    change.add_argument("--target", required=True, choices=[mode.value for mode in RuntimeMode])
    change.add_argument("--expected-generation", required=True, type=int)
    change.add_argument("--apply", action="store_true")
    snapshot_command = subcommands.choices["snapshot"]
    snapshot_command.add_argument("--backup-dir", type=Path)
    subcommands.choices["verify-active"].add_argument("--required-successes", type=int, default=20)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        kwargs = {"platform": args.platform, "workspace_id": args.workspace_id}
        if args.command == "status":
            result = status(args.data_dir, **kwargs)
        elif args.command == "snapshot":
            result = snapshot(args.data_dir, backup_dir=args.backup_dir, **kwargs)
        elif args.command == "transition":
            result = transition(
                args.data_dir,
                current=RuntimeMode(args.current), target=RuntimeMode(args.target),
                expected_generation=args.expected_generation, apply=bool(args.apply), **kwargs,
            )
        else:
            result = verify(
                args.data_dir,
                expected_mode=RuntimeMode.SHADOW if args.command == "verify-shadow" else RuntimeMode.ACTIVE,
                required_successes=getattr(args, "required_successes", 20), **kwargs,
            )
    except (CutoverError, sqlite3.Error) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
