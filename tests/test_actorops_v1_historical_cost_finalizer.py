"""Evidence-bound convergence coverage for terminal v1 aggregate costs."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from src.services.actorops.legacy_aggregate_costs import (
    HistoricalCostFinalizationError,
    apply_evidence,
    build_evidence,
    scan_historical_costs,
)
from scripts.finalize_actorops_v1_historical_costs import (
    apply as apply_cli,
    scan as scan_cli,
    snapshot as snapshot_cli,
    verify as verify_cli,
)


STAMP = "2026-08-23T00:00:00+00:00"


def _connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE apify_actor_attempts (
            id TEXT PRIMARY KEY, status TEXT NOT NULL, reserved_usd REAL NOT NULL,
            actual_cost_usd REAL, cost_final INTEGER NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE apify_actor_runs (
            id TEXT PRIMARY KEY, logical_run_id TEXT NOT NULL, remote_run_id TEXT,
            dataset_id TEXT, status TEXT NOT NULL, charge_reserved_usd REAL NOT NULL,
            charge_actual_usd REAL, charge_final INTEGER NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE apify_actor_validations (
            validation_id TEXT PRIMARY KEY, attempt_id TEXT, status TEXT NOT NULL,
            cost_usd REAL, cost_final INTEGER NOT NULL, created_at TEXT NOT NULL,
            completed_at TEXT
        );
        CREATE TABLE apify_actor_canary_batches (
            batch_id TEXT PRIMARY KEY, status TEXT NOT NULL, planned_count INTEGER NOT NULL, actual_cost_usd REAL,
            cost_final INTEGER NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE apify_actor_canary_batch_items (
            batch_id TEXT NOT NULL, ordinal INTEGER NOT NULL, validation_id TEXT NOT NULL,
            status TEXT NOT NULL, actual_cost_usd REAL, cost_final INTEGER NOT NULL,
            updated_at TEXT NOT NULL, PRIMARY KEY(batch_id, ordinal)
        );
        CREATE TABLE apify_actor_freshness_checks (
            check_id TEXT PRIMARY KEY, status TEXT NOT NULL, cost_final INTEGER NOT NULL
        );
        CREATE TABLE apify_actor_freshness_results (
            check_id TEXT NOT NULL, candidate_id TEXT NOT NULL, ordinal INTEGER NOT NULL, status TEXT NOT NULL,
            cost_final INTEGER NOT NULL, PRIMARY KEY(check_id, ordinal)
        );
        """
    )
    return connection


def _seed_finalizable_chain(connection: sqlite3.Connection) -> None:
    connection.executemany(
        """INSERT INTO apify_actor_attempts VALUES (?, 'actor_failed', 0.02, NULL, 0, ?)""",
        (("zero-attempt", STAMP), ("paid-attempt", STAMP)),
    )
    connection.executemany(
        """INSERT INTO apify_actor_runs VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
        (
            ("zero-run", "zero-attempt", None, None, "start_rejected", 0.0, 0.0, STAMP),
            ("paid-run", "paid-attempt", "opaque-remote-run", "opaque-dataset", "succeeded", 0.002, 0.002, STAMP),
        ),
    )
    connection.executemany(
        """INSERT INTO apify_actor_validations VALUES (?, ?, ?, NULL, 0, ?, ?)""",
        (
            ("zero-validation", "zero-attempt", "failed", STAMP, STAMP),
            ("paid-validation", "paid-attempt", "succeeded", STAMP, STAMP),
            ("unstarted-validation", None, "cancelled", STAMP, STAMP),
        ),
    )
    connection.executemany(
        """INSERT INTO apify_actor_canary_batch_items VALUES (?, ?, ?, ?, NULL, 0, ?)""",
        (
            ("zero-batch", 1, "zero-validation", "failed", STAMP),
            ("paid-batch", 1, "paid-validation", "succeeded", STAMP),
        ),
    )
    connection.executemany(
        """INSERT INTO apify_actor_canary_batches VALUES (?, 'partial', 1, ?, 0, ?)""",
        (("zero-batch", 0.0, STAMP), ("paid-batch", 0.002, STAMP)),
    )
    connection.commit()


def test_finalizer_derives_only_settled_ledger_costs_and_preserves_amounts(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path / "service.db")
    _seed_finalizable_chain(connection)

    report = scan_historical_costs(connection, salt="test-salt")
    evidence = build_evidence(report)

    assert report.blocker_count == 0
    assert report.finalizable_count == 9
    encoded = json.dumps(evidence, sort_keys=True)
    assert "zero-attempt" not in encoded
    assert "opaque-remote-run" not in encoded
    assert evidence["counts"] == {
        "apify_actor_attempts": 2,
        "apify_actor_canary_batches": 2,
        "apify_actor_canary_batch_items": 2,
        "apify_actor_validations": 3,
    }

    result = apply_evidence(
        connection, evidence, expected_hash=str(evidence["evidence_hash"]), stamp=STAMP,
    )

    assert result == evidence["counts"]
    assert tuple(connection.execute(
        "SELECT actual_cost_usd, cost_final FROM apify_actor_attempts WHERE id='zero-attempt'"
    ).fetchone()) == (0.0, 1)
    assert tuple(connection.execute(
        "SELECT actual_cost_usd, cost_final FROM apify_actor_attempts WHERE id='paid-attempt'"
    ).fetchone()) == (0.002, 1)
    assert tuple(connection.execute(
        "SELECT cost_usd, cost_final FROM apify_actor_validations WHERE validation_id='unstarted-validation'"
    ).fetchone()) == (0.0, 1)
    assert tuple(connection.execute(
        "SELECT actual_cost_usd, cost_final FROM apify_actor_canary_batches WHERE batch_id='paid-batch'"
    ).fetchone()) == (0.002, 1)
    assert tuple(connection.execute(
        "SELECT charge_actual_usd, charge_final FROM apify_actor_runs WHERE id='paid-run'"
    ).fetchone()) == (0.002, 1)
    connection.close()


def test_finalizer_rejects_ambiguous_or_inconsistent_historical_costs(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path / "service.db")
    _seed_finalizable_chain(connection)
    connection.execute(
        "UPDATE apify_actor_canary_batches SET actual_cost_usd=0.01 WHERE batch_id='paid-batch'"
    )
    connection.execute(
        """INSERT INTO apify_actor_runs VALUES (
               'second-paid-run', 'paid-attempt', 'opaque-remote-run-2', NULL,
               'succeeded', 0.002, 0.002, 1, ?)""",
        (STAMP,),
    )
    connection.commit()

    report = scan_historical_costs(connection, salt="test-salt")
    evidence = build_evidence(report)

    assert report.blocker_count >= 2
    with pytest.raises(HistoricalCostFinalizationError, match="blockers"):
        apply_evidence(
            connection, evidence, expected_hash=str(evidence["evidence_hash"]), stamp=STAMP,
        )
    assert connection.execute(
        "SELECT COUNT(*) FROM apify_actor_attempts WHERE cost_final=1"
    ).fetchone()[0] == 0
    connection.close()


def test_finalizer_preserves_a_known_terminal_aggregate_above_settled_children(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path / "service.db")
    _seed_finalizable_chain(connection)
    connection.execute(
        "UPDATE apify_actor_runs SET charge_actual_usd=0.001 WHERE id='paid-run'"
    )
    connection.execute(
        "UPDATE apify_actor_attempts SET actual_cost_usd=0.001, cost_final=1 WHERE id='paid-attempt'"
    )
    connection.execute(
        "UPDATE apify_actor_validations SET cost_usd=0.001, cost_final=1 WHERE validation_id='paid-validation'"
    )
    connection.execute(
        "UPDATE apify_actor_canary_batch_items SET actual_cost_usd=0.001, cost_final=1 WHERE batch_id='paid-batch'"
    )
    connection.commit()

    evidence = build_evidence(scan_historical_costs(connection, salt="test-salt"))
    apply_evidence(connection, evidence, expected_hash=str(evidence["evidence_hash"]), stamp=STAMP)

    assert tuple(connection.execute(
        "SELECT actual_cost_usd, cost_final FROM apify_actor_canary_batches WHERE batch_id='paid-batch'"
    ).fetchone()) == (0.002, 1)
    connection.close()


def test_finalizer_refuses_new_or_unrelated_unsettled_historical_facts(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path / "service.db")
    _seed_finalizable_chain(connection)
    report = scan_historical_costs(connection, salt="test-salt")
    evidence = build_evidence(report)
    connection.execute(
        "INSERT INTO apify_actor_freshness_checks VALUES ('unsettled', 'cancelled', 0)"
    )
    connection.commit()

    with pytest.raises(HistoricalCostFinalizationError, match="changed after scan"):
        apply_evidence(
            connection, evidence, expected_hash=str(evidence["evidence_hash"]), stamp=STAMP,
        )
    connection.close()


def test_cli_requires_a_private_snapshot_and_is_idempotent(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    connection = _connection(data_dir / "service.db")
    _seed_finalizable_chain(connection)
    connection.close()
    evidence_path = tmp_path / "evidence.json"
    receipt_path = tmp_path / "receipt.json"

    scanned = scan_cli(data_dir, evidence_path=evidence_path)
    snapshotted = snapshot_cli(
        data_dir,
        evidence_path=evidence_path,
        receipt_path=receipt_path,
        backup_dir=tmp_path / "backups",
        services_stopped=True,
        heartbeat_window_seconds=0,
    )
    applied = apply_cli(
        data_dir,
        evidence_path=evidence_path,
        receipt_path=receipt_path,
        expected_hash=str(scanned["evidence_hash"]),
        services_stopped=True,
        heartbeat_window_seconds=0,
    )

    assert scanned["status"] == "ready"
    assert snapshotted["backup_mode"] == "0o600"
    assert applied["applied"] is True
    assert os.stat(evidence_path).st_mode & 0o777 == 0o600
    assert os.stat(receipt_path).st_mode & 0o777 == 0o600
    assert verify_cli(data_dir, evidence_path=evidence_path, receipt_path=receipt_path)["status"] == "verified"
    assert apply_cli(
        data_dir,
        evidence_path=evidence_path,
        receipt_path=receipt_path,
        expected_hash=str(scanned["evidence_hash"]),
        services_stopped=True,
        heartbeat_window_seconds=0,
    )["status"] == "already_finalized"
