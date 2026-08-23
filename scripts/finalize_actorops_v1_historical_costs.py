#!/usr/bin/env python3
"""Offline, evidence-bound finalization of terminal ActorOps v1 aggregates."""

from __future__ import annotations

import argparse
import hashlib
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


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.actorops_migration_safety import active_workers_fail_closed
from src.services.actorops.legacy_aggregate_costs import (
    EVIDENCE_SCHEMA,
    HistoricalCostFinalizationError,
    apply_evidence,
    build_evidence,
    scan_historical_costs,
    validate_evidence,
)


RECEIPT_SCHEMA = "actorops_v1_historical_aggregate_snapshot_v1"


class HistoricalCostCliError(RuntimeError):
    """Stable, value-safe error at the offline CLI boundary."""


def status(data_dir: Path) -> dict[str, object]:
    connection = _connect(_database(data_dir), read_only=True)
    try:
        report = scan_historical_costs(connection, salt="status")
    finally:
        connection.close()
    return _summary(report)


def scan(data_dir: Path, *, evidence_path: Path) -> dict[str, object]:
    if evidence_path.exists() or evidence_path.is_symlink():
        raise HistoricalCostCliError("evidence path already exists")
    connection = _connect(_database(data_dir), read_only=True)
    try:
        evidence = build_evidence(scan_historical_costs(connection, salt=secrets.token_hex(16)))
    finally:
        connection.close()
    _write_private_json(evidence_path, evidence, replace=False)
    return {**_public_evidence(evidence), "status": "ready" if not evidence["blocker_count"] else "blocked"}


def snapshot(
    data_dir: Path,
    *,
    evidence_path: Path,
    receipt_path: Path,
    backup_dir: Path | None,
    services_stopped: bool,
    heartbeat_window_seconds: float = 35.0,
) -> dict[str, object]:
    database = _database(data_dir)
    evidence = _read_evidence(evidence_path)
    _quiet_guard(database, services_stopped=services_stopped, heartbeat_window_seconds=heartbeat_window_seconds)
    _assert_current_evidence(database, evidence)
    backup = _backup(database, backup_dir or data_dir / "backups")
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "code_sha": _code_sha(),
        "evidence_hash": evidence["evidence_hash"],
        "database_sha256": _sha256(database),
        "backup_sha256": _sha256(backup),
        "backup": {"path": str(backup), "mode": "0o600"},
        "schema_shape": _schema_shape(database),
    }
    _write_private_json(receipt_path, receipt, replace=False)
    return {
        "status": "snapshotted", "backup_mode": "0o600",
        "evidence_hash": evidence["evidence_hash"], "receipt_path": str(receipt_path),
    }


def apply(
    data_dir: Path,
    *,
    evidence_path: Path,
    receipt_path: Path,
    expected_hash: str,
    services_stopped: bool,
    heartbeat_window_seconds: float = 35.0,
) -> dict[str, object]:
    database = _database(data_dir)
    evidence = _read_evidence(evidence_path)
    receipt = _read_receipt(receipt_path, evidence_hash=expected_hash)
    if expected_hash != evidence.get("evidence_hash"):
        raise HistoricalCostCliError("evidence hash does not match the supplied proof")
    _quiet_guard(database, services_stopped=services_stopped, heartbeat_window_seconds=heartbeat_window_seconds)
    after = receipt.get("post_apply_database_sha256")
    if after is not None:
        if after != _sha256(database):
            raise HistoricalCostCliError("database hash no longer matches the finalization receipt")
        return {"status": "already_finalized", "applied": False, "evidence_hash": expected_hash}
    if receipt.get("database_sha256") != _sha256(database):
        raise HistoricalCostCliError("database hash no longer matches the snapshot receipt")
    connection = _connect(database, read_only=False)
    try:
        result = apply_evidence(connection, evidence, expected_hash=expected_hash)
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity.casefold() != "ok" or foreign_keys:
            raise HistoricalCostCliError("post-finalization database verification failed")
    finally:
        connection.close()
    receipt["applied_at"] = datetime.now(timezone.utc).isoformat()
    receipt["post_apply_database_sha256"] = _sha256(database)
    _write_private_json(receipt_path, receipt, replace=True)
    return {"status": "applied", "applied": True, "evidence_hash": expected_hash, "result": result}


def verify(data_dir: Path, *, evidence_path: Path, receipt_path: Path) -> dict[str, object]:
    database = _database(data_dir)
    evidence = _read_evidence(evidence_path)
    receipt = _read_receipt(receipt_path, evidence_hash=str(evidence["evidence_hash"]))
    expected = receipt.get("post_apply_database_sha256")
    if not isinstance(expected, str) or expected != _sha256(database):
        raise HistoricalCostCliError("database hash does not match the finalization receipt")
    if _schema_shape(database) != receipt.get("schema_shape"):
        raise HistoricalCostCliError("schema shape does not match the finalization receipt")
    connection = _connect(database, read_only=True)
    try:
        report = scan_historical_costs(connection, salt=str(evidence["salt"]))
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        connection.close()
    if report.finalizable_count or report.blocker_count or integrity.casefold() != "ok" or foreign_keys:
        raise HistoricalCostCliError("historical cost finalization verification failed")
    return {"status": "verified", "evidence_hash": evidence["evidence_hash"]}


def _database(data_dir: Path) -> Path:
    database = data_dir / "service.db"
    if not database.is_file():
        raise HistoricalCostCliError("service database does not exist")
    return database


def _connect(database: Path, *, read_only: bool) -> sqlite3.Connection:
    target: str | Path = f"file:{database.resolve()}?mode=ro" if read_only else database
    connection = sqlite3.connect(target, uri=read_only)
    connection.row_factory = sqlite3.Row
    if read_only:
        connection.execute("PRAGMA query_only=ON")
    return connection


def _quiet_guard(database: Path, *, services_stopped: bool, heartbeat_window_seconds: float) -> None:
    if not services_stopped:
        raise HistoricalCostCliError("explicit --services-stopped confirmation is required")
    if heartbeat_window_seconds < 0 or heartbeat_window_seconds > 60:
        raise HistoricalCostCliError("heartbeat window must be between 0 and 60 seconds")
    if active_workers_fail_closed(database):
        raise HistoricalCostCliError("worker heartbeat safety window has not elapsed")
    if heartbeat_window_seconds:
        time.sleep(heartbeat_window_seconds)
    if active_workers_fail_closed(database):
        raise HistoricalCostCliError("worker heartbeat appeared during safety window")


def _assert_current_evidence(database: Path, evidence: dict[str, object]) -> None:
    if int(evidence["blocker_count"]):
        raise HistoricalCostCliError("historical cost evidence contains blockers")
    connection = _connect(database, read_only=True)
    try:
        current = build_evidence(scan_historical_costs(connection, salt=str(evidence["salt"])))
    finally:
        connection.close()
    if current != evidence:
        raise HistoricalCostCliError("historical cost facts changed after scan")


def _read_evidence(path: Path) -> dict[str, object]:
    evidence = _read_private_json(path)
    try:
        return validate_evidence(evidence)
    except HistoricalCostFinalizationError as error:
        raise HistoricalCostCliError(str(error)) from error


def _read_receipt(path: Path, *, evidence_hash: str) -> dict[str, object]:
    receipt = _read_private_json(path)
    backup = receipt.get("backup")
    if (
        receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("evidence_hash") != evidence_hash
        or not isinstance(backup, dict) or backup.get("mode") != "0o600"
        or not isinstance(backup.get("path"), str)
    ):
        raise HistoricalCostCliError("finalization receipt does not match the evidence")
    backup_path = Path(str(backup["path"]))
    if not backup_path.is_file() or backup_path.is_symlink() or stat.S_IMODE(backup_path.stat().st_mode) != 0o600:
        raise HistoricalCostCliError("finalization backup is unavailable or has unsafe permissions")
    return receipt


def _read_private_json(path: Path) -> dict[str, object]:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise HistoricalCostCliError("private file must be a regular 0600 file")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise HistoricalCostCliError("private file is unreadable") from error
    if not isinstance(value, dict):
        raise HistoricalCostCliError("private file must contain an object")
    return value


def _write_private_json(path: Path, value: dict[str, object], *, replace: bool) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if not replace:
            raise HistoricalCostCliError("private file already exists")
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise HistoricalCostCliError("private file must be a regular file")
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _backup(database: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = backup_dir / f"service-actorops-v1-historical-cost-{stamp}.db"
    descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    os.close(descriptor)
    source = destination = None
    try:
        source = _connect(database, read_only=True)
        destination = sqlite3.connect(backup)
        source.backup(destination)
    except Exception:
        backup.unlink(missing_ok=True)
        raise
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()
    os.chmod(backup, 0o600)
    return backup


def _schema_shape(database: Path) -> dict[str, object]:
    connection = _connect(database, read_only=True)
    try:
        entries = [
            (str(row["type"]), str(row["name"]), str(row["sql"] or ""))
            for row in connection.execute(
                "SELECT type, name, sql FROM sqlite_master WHERE type IN ('table', 'index', 'trigger') ORDER BY type, name"
            )
        ]
    finally:
        connection.close()
    raw = json.dumps(entries, ensure_ascii=True, separators=(",", ":")).encode()
    return {"entry_count": len(entries), "sha256": hashlib.sha256(raw).hexdigest()}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _code_sha() -> str:
    try:
        import subprocess

        return subprocess.check_output(("git", "rev-parse", "HEAD"), cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _summary(report: Any) -> dict[str, object]:
    return {
        "status": "ready" if not report.blocker_count else "blocked",
        "counts": _counts(report.finalizable),
        "finalizable_count": report.finalizable_count,
        "blocker_count": report.blocker_count,
    }


def _public_evidence(evidence: dict[str, object]) -> dict[str, object]:
    return {
        "counts": evidence["counts"], "finalizable_count": evidence["finalizable_count"],
        "blocker_count": evidence["blocker_count"], "evidence_hash": evidence["evidence_hash"],
    }


def _counts(facts: tuple[Any, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for fact in facts:
        counts[fact.table] = counts.get(fact.table, 0) + 1
    return dict(sorted(counts.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline ActorOps v1 historical cost finalizer")
    parser.add_argument("command", choices=("status", "scan", "snapshot", "apply", "verify"))
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--services-stopped", action="store_true")
    parser.add_argument("--heartbeat-window-seconds", type=float, default=35.0)
    parser.add_argument("--expected-evidence-hash")
    args = parser.parse_args()
    try:
        if args.command == "status":
            result = status(args.data_dir)
        else:
            if args.evidence is None:
                raise HistoricalCostCliError(f"{args.command} requires --evidence")
            receipt = args.receipt or args.evidence.with_name(f"{args.evidence.name}.snapshot.json")
            if args.command == "scan":
                result = scan(args.data_dir, evidence_path=args.evidence)
            elif args.command == "snapshot":
                result = snapshot(args.data_dir, evidence_path=args.evidence, receipt_path=receipt, backup_dir=args.backup_dir, services_stopped=bool(args.services_stopped), heartbeat_window_seconds=args.heartbeat_window_seconds)
            elif args.command == "apply":
                if not args.expected_evidence_hash:
                    raise HistoricalCostCliError("apply requires --expected-evidence-hash")
                result = apply(args.data_dir, evidence_path=args.evidence, receipt_path=receipt, expected_hash=args.expected_evidence_hash, services_stopped=bool(args.services_stopped), heartbeat_window_seconds=args.heartbeat_window_seconds)
            else:
                result = verify(args.data_dir, evidence_path=args.evidence, receipt_path=receipt)
    except (HistoricalCostFinalizationError, HistoricalCostCliError, OSError, sqlite3.Error, ValueError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
