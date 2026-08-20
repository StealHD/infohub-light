#!/usr/bin/env python3
"""Offline audit and quarantine controls for legacy ActorOps cost records."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sqlite3
import stat
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.actorops_migration_safety import active_workers_fail_closed
from scripts.migrate_actorops_v2 import migration_blockers, quarantine_summary
from scripts.migrate_apify_actor_ops_v15 import _backup_database
from src.services.actorops.legacy_cost_audit import (
    LegacyCostAuditError,
    LegacyRunCostReader,
    RemoteCostObservation,
    apply_evidence,
    build_evidence,
    scan_legacy_costs,
    validate_evidence_against_current,
)
from src.services.actorops.legacy_cost_evidence import (
    LegacyEvidenceError,
    merge_evidence,
    opaque_fact_id,
    public_fact,
    validate_evidence,
)
from src.services.apify_key_pool import ApifyKeyPoolService
from src.services.secret_store import SecretStore
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


class LegacyCostCliError(RuntimeError):
    pass


def _database(data_dir: Path) -> Path:
    database = data_dir / "service.db"
    if not database.is_file():
        raise LegacyCostCliError("service database does not exist")
    return database


def _connect(database: Path, *, read_only: bool) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"file:{database}?mode=ro" if read_only else database, uri=read_only
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


class ApifyLegacyRunReader(LegacyRunCostReader):
    """The only audit boundary permitted to hold the stored credential token."""

    def __init__(
        self, data_dir: Path, *, workspace_id: str = DEFAULT_WORKSPACE_ID,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.store = ServiceStore(data_dir)
        self.workspace_id = workspace_id
        self.transport = transport

    def read(self, remote_run_id: str) -> RemoteCostObservation:
        row = self.store.connect().execute(
            """SELECT id FROM apify_actor_runs
               WHERE workspace_id=? AND remote_run_id=? ORDER BY id""",
            (self.workspace_id, remote_run_id),
        ).fetchone()
        if row is None:
            return RemoteCostObservation("unavailable")
        try:
            coordinator = ApifyKeyPoolService(
                self.store, secret_store=SecretStore(self.store.data_dir),
                workspace_id=self.workspace_id,
            )
            lease = coordinator.lease_for_run(str(row["id"]))
            with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0), transport=self.transport, trust_env=False) as client:
                response = client.get(
                    f"https://api.apify.com/v2/actor-runs/{quote(remote_run_id, safe='')}",
                    headers={"Authorization": f"Bearer {lease.token}", "Accept": "application/json"},
                )
        except httpx.HTTPError:
            return RemoteCostObservation("unavailable")
        except Exception:
            return RemoteCostObservation("unavailable")
        if response.status_code == 404:
            return RemoteCostObservation.not_found()
        if response.status_code in {401, 403}:
            return RemoteCostObservation("unauthorized")
        if response.status_code == 429:
            return RemoteCostObservation("rate_limited")
        if response.status_code < 200 or response.status_code >= 300:
            return RemoteCostObservation("unavailable")
        try:
            payload = response.json()
            if isinstance(payload, dict):
                payload = payload.get("data", payload)
            cost = payload.get("usageTotalUsd")
        except (AttributeError, TypeError, ValueError):
            return RemoteCostObservation("unavailable")
        if isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost < 0:
            return RemoteCostObservation("unavailable")
        return RemoteCostObservation.found(float(cost))


def status(data_dir: Path) -> dict[str, Any]:
    connection = _connect(_database(data_dir), read_only=True)
    try:
        blockers = migration_blockers(connection)
        summary = quarantine_summary(connection)
    finally:
        connection.close()
    return {
        "status": "blocked" if any(blockers.values()) else "ready",
        "blocker_counts": {name: count for name, count in blockers.items() if count},
        "quarantine": summary,
        "global_25_ignored": True,
    }


def scan(
    data_dir: Path, *, reader: LegacyRunCostReader | None = None, limit: int = 20,
    salt: str | None = None, existing_evidence: dict[str, object] | None = None,
    retry_blocked: bool = False,
) -> dict[str, object]:
    prior = validate_evidence(existing_evidence) if existing_evidence is not None else None
    session_salt = str(prior["salt"]) if prior is not None else (salt or secrets.token_hex(16))
    known_fact_ids = (
        {str(item["fact_id"]) for item in prior["facts"] if isinstance(item, dict)}
        if prior is not None else set()
    )
    retry_fact_ids = (
        {
            str(item["fact_id"])
            for item in prior["facts"]
            if isinstance(item, dict) and item.get("action") == "remote_blocked"
        }
        if prior is not None and retry_blocked else set()
    )
    connection = _connect(_database(data_dir), read_only=True)
    try:
        report = scan_legacy_costs(
            connection, reader or ApifyLegacyRunReader(data_dir), limit=limit,
            salt=session_salt, known_remote_fact_ids=known_fact_ids,
            retry_remote_fact_ids=retry_fact_ids,
        )
    finally:
        connection.close()
    if prior is None:
        return build_evidence(report)
    page_facts = [
        public_fact(
            salt=session_salt, identity=fact.identity, action=fact.action,
            status=fact.status, updated_at=fact.updated_at, amount_usd=fact.amount_usd,
        )
        for fact in report.facts
    ]
    refreshed = [opaque_fact_id(session_salt, identity) for identity in report.scanned_remote_identities]
    return merge_evidence(
        prior, facts=page_facts, refreshed_remote_fact_ids=refreshed,
        remaining_remote_runs=report.remaining_remote_runs,
        increment_page=bool(report.scanned_remote_identities),
    )


def _read_private_json(path: Path) -> dict[str, object]:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise LegacyCostCliError("evidence file must be a regular file")
    if metadata.st_mode & 0o777 != 0o600:
        raise LegacyCostCliError("evidence file must have mode 0600")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
    except Exception:
        raise
    if not isinstance(loaded, dict):
        raise LegacyCostCliError("evidence file must contain an object")
    return loaded


def _write_private_json(path: Path, payload: dict[str, object], *, replace: bool) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if not replace:
            raise LegacyCostCliError("evidence path already exists; use --resume")
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise LegacyCostCliError("evidence path must be a regular file")
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
            temporary.unlink()
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _receipt_path(evidence_path: Path) -> Path:
    return evidence_path.with_name(f"{evidence_path.name}.snapshot.json")


def _validate_receipt(receipt: dict[str, object], *, evidence_hash: str) -> dict[str, object]:
    backup = receipt.get("backup")
    if (
        receipt.get("schema") != "actorops_v2_legacy_cost_snapshot_v1"
        or receipt.get("evidence_hash") != evidence_hash
        or not isinstance(backup, dict)
        or not isinstance(backup.get("path"), str)
        or backup.get("mode") != "0o600"
    ):
        raise LegacyCostCliError("snapshot receipt does not match the evidence")
    backup_path = Path(str(backup["path"]))
    metadata = backup_path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode) or metadata.st_mode & 0o777 != 0o600:
        raise LegacyCostCliError("snapshot backup is unavailable or has unsafe permissions")
    return receipt


def snapshot(
    data_dir: Path, *, evidence_path: Path, backup_dir: Path | None = None,
    receipt_path: Path | None = None, services_stopped: bool = False,
    heartbeat_window_seconds: float = 30.0,
) -> dict[str, object]:
    database = _database(data_dir)
    if not services_stopped:
        raise LegacyCostCliError("snapshot requires explicit services-stopped confirmation")
    evidence = _read_private_json(evidence_path)
    try:
        validate_evidence(evidence)
    except LegacyEvidenceError as error:
        raise LegacyCostCliError(str(error)) from error
    if active_workers_fail_closed(database):
        raise LegacyCostCliError("API and Worker must be stopped before snapshot")
    if heartbeat_window_seconds > 0:
        time.sleep(heartbeat_window_seconds)
    if active_workers_fail_closed(database):
        raise LegacyCostCliError("Worker heartbeat appeared during snapshot guard")
    connection = _connect(database, read_only=True)
    try:
        validate_evidence_against_current(connection, evidence, require_complete=True)
    finally:
        connection.close()
    backup = _backup_database(database, backup_dir or data_dir / "backups")
    os.chmod(backup, 0o600)
    receipt = {
        "schema": "actorops_v2_legacy_cost_snapshot_v1",
        "evidence_hash": evidence["evidence_hash"],
        "backup": {"path": str(backup), "mode": "0o600"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    target_receipt = receipt_path or _receipt_path(evidence_path)
    _write_private_json(target_receipt, receipt, replace=False)
    return {
        "status": "snapshotted", "backup_mode": oct(backup.stat().st_mode & 0o777),
        "evidence_hash": evidence["evidence_hash"],
        "upper_bound_usd": evidence["upper_bound_usd"],
        "receipt_path": str(target_receipt),
    }


def quarantine(
    data_dir: Path, *, evidence: dict[str, object], expected_hash: str,
    confirmed_upper_bound_usd: float, apply: bool,
    heartbeat_window_seconds: float = 30.0, services_stopped: bool = False,
    receipt: dict[str, object] | None = None,
) -> dict[str, object]:
    if not apply:
        if expected_hash != evidence.get("evidence_hash"):
            raise LegacyCostCliError("evidence hash does not match the supplied proof")
        return {"status": "dry_run", "evidence_hash": expected_hash, "upper_bound_usd": evidence.get("upper_bound_usd")}
    database = _database(data_dir)
    if not services_stopped:
        raise LegacyCostCliError("quarantine requires explicit services-stopped confirmation")
    if active_workers_fail_closed(database):
        raise LegacyCostCliError("API and Worker must be stopped before quarantine")
    if heartbeat_window_seconds > 0:
        time.sleep(heartbeat_window_seconds)
    if active_workers_fail_closed(database):
        raise LegacyCostCliError("Worker heartbeat appeared during quarantine guard")
    if receipt is None:
        raise LegacyCostCliError("quarantine requires a snapshot receipt")
    _validate_receipt(receipt, evidence_hash=expected_hash)
    connection = _connect(database, read_only=False)
    try:
        connection.execute("BEGIN IMMEDIATE")
        validate_evidence_against_current(connection, evidence, require_complete=True)
        result = apply_evidence(connection, evidence, expected_hash=expected_hash, confirmed_upper_bound_usd=confirmed_upper_bound_usd)
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()
    return {
        "status": "applied", "evidence_hash": expected_hash, "result": result,
        "backup_mode": "0o600",
    }


def _public_evidence(evidence: dict[str, object]) -> dict[str, object]:
    return {
        "status": "scanned", "counts": evidence["counts"],
        "upper_bound_usd": evidence["upper_bound_usd"],
        "remaining_remote_runs": evidence["remaining_remote_runs"],
        "scan_pages": evidence["scan_pages"],
        "evidence_hash": evidence["evidence_hash"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("status", "scan", "snapshot", "quarantine"))
    parser.add_argument("--data-dir", type=Path, default=REPOSITORY_ROOT / "data")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-blocked", action="store_true")
    parser.add_argument("--services-stopped", action="store_true")
    parser.add_argument("--expected-evidence-hash")
    parser.add_argument("--confirm-upper-bound-usd", type=float)
    args = parser.parse_args()
    try:
        if args.command == "status":
            result = status(args.data_dir)
        elif args.command == "scan":
            if args.evidence is None:
                raise LegacyCostCliError("scan requires --evidence")
            if args.retry_blocked and not args.resume:
                raise LegacyCostCliError("--retry-blocked requires --resume")
            existing = _read_private_json(args.evidence) if args.resume else None
            evidence = scan(
                args.data_dir, limit=args.limit, existing_evidence=existing,
                retry_blocked=bool(args.retry_blocked),
            )
            _write_private_json(args.evidence, evidence, replace=bool(args.resume))
            result = _public_evidence(evidence)
        elif args.command == "snapshot":
            if args.evidence is None:
                raise LegacyCostCliError("snapshot requires --evidence")
            result = snapshot(
                args.data_dir, evidence_path=args.evidence, backup_dir=args.backup_dir,
                services_stopped=bool(args.services_stopped),
            )
        else:
            if args.evidence is None or not args.expected_evidence_hash or args.confirm_upper_bound_usd is None:
                raise LegacyCostCliError("quarantine requires evidence hash and confirmed upper-bound")
            evidence = _read_private_json(args.evidence)
            receipt = _read_private_json(_receipt_path(args.evidence))
            result = quarantine(
                args.data_dir, evidence=evidence, expected_hash=args.expected_evidence_hash,
                confirmed_upper_bound_usd=args.confirm_upper_bound_usd, apply=args.apply,
                services_stopped=bool(args.services_stopped), receipt=receipt,
            )
    except (LegacyCostAuditError, LegacyCostCliError, LegacyEvidenceError, ValueError, OSError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
