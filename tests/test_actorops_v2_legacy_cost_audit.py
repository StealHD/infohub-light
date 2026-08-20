from __future__ import annotations

import json
import ast
import sqlite3
from pathlib import Path

import pytest

import scripts.migrate_actorops_v2 as migration_module
from src.services.actorops.legacy_cost_audit import (
    LegacyCostAuditError,
    RemoteCostObservation,
    apply_evidence,
    build_evidence,
    scan_legacy_costs,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


_STAMP = "2026-08-21T00:00:00+00:00"


def _store(tmp_path: Path) -> ServiceStore:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    return store


def _run(
    store: ServiceStore,
    *,
    run_id: str = "legacy-run",
    remote_run_id: str | None = "remote-run",
    status: str = "succeeded",
    reserved: float = 0.05,
) -> None:
    store.connect().execute(
        """INSERT INTO apify_actor_runs(
               id, workspace_id, purpose, secret_id, secret_version,
               pool_generation, logical_run_id, remote_run_id, status,
               created_at, terminal_at, updated_at,
               charge_reserved_usd, charge_actual_usd, charge_final
           ) VALUES (?, ?, 'acquisition', 'legacy-secret', 1, 1, ?, ?, ?,
                     ?, ?, ?, ?, NULL, 0)""",
        (run_id, DEFAULT_WORKSPACE_ID, run_id, remote_run_id, status,
         _STAMP, _STAMP, _STAMP, reserved),
    )
    store.connect().commit()


def _attempt(
    store: ServiceStore,
    *,
    attempt_id: str = "legacy-attempt",
    status: str = "succeeded",
    reserved: float = 0.05,
) -> None:
    connection = store.connect()
    route = connection.execute(
        "SELECT workspace_id, route_key, generation FROM apify_actor_routes LIMIT 1"
    ).fetchone()
    connection.execute(
        """INSERT INTO apify_actor_candidates(
               id, workspace_id, route_key, actor_id, adapter_key, display_name,
               position, state, created_at, updated_at
           ) VALUES ('legacy-audit-candidate', ?, ?, 'publisher/actor',
                     'legacy-audit', 'legacy audit', 99, 'closed', ?, ?)""",
        (str(route["workspace_id"]), str(route["route_key"]), _STAMP, _STAMP),
    )
    connection.execute(
        """INSERT INTO apify_actor_attempts(
               id, workspace_id, route_key, route_generation, candidate_id,
               attempt_group_id, attempt_index, status, reserved_usd,
               cost_final, created_at, terminal_at, updated_at
           ) VALUES (?, ?, ?, ?, 'legacy-audit-candidate', 'legacy-audit-group',
                     1, ?, ?, 0, ?, ?, ?)""",
        (attempt_id, str(route["workspace_id"]), str(route["route_key"]),
         int(route["generation"]), status, reserved, _STAMP, _STAMP, _STAMP),
    )
    connection.commit()


class _Reader:
    def __init__(self, observations: dict[str, RemoteCostObservation]) -> None:
        self.observations = observations
        self.calls: list[str] = []

    def read(self, remote_run_id: str) -> RemoteCostObservation:
        self.calls.append(remote_run_id)
        return self.observations[remote_run_id]


def test_scan_and_apply_settles_only_a_provider_exact_cost(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _run(store)
    reader = _Reader({"remote-run": RemoteCostObservation.found(0.0175)})
    report = scan_legacy_costs(store.connect(), reader, limit=20, salt="test-salt")
    evidence = build_evidence(report)

    assert report.counts == {"provider_cost": 1}
    assert report.upper_bound_usd == 0.0
    assert "remote-run" not in json.dumps(evidence, sort_keys=True)
    result = apply_evidence(
        store.connect(), evidence, expected_hash=str(evidence["evidence_hash"]),
        confirmed_upper_bound_usd=0.0,
    )
    assert result == {"quarantined_attempts": 0, "quarantined_runs": 0, "settled_runs": 1}
    row = store.connect().execute(
        "SELECT charge_actual_usd, charge_final, last_error_code FROM apify_actor_runs WHERE id='legacy-run'"
    ).fetchone()
    assert tuple(row) == (0.0175, 1, None)
    store.close()


def test_not_found_is_quarantined_without_falsifying_cost_final(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _run(store, reserved=0.08)
    report = scan_legacy_costs(
        store.connect(), _Reader({"remote-run": RemoteCostObservation.not_found()}),
        limit=20, salt="test-salt",
    )
    evidence = build_evidence(report)
    assert report.counts == {"quarantine_run": 1}
    assert report.upper_bound_usd == 0.08
    apply_evidence(
        store.connect(), evidence, expected_hash=str(evidence["evidence_hash"]),
        confirmed_upper_bound_usd=0.08,
    )
    row = store.connect().execute(
        "SELECT charge_reserved_usd, charge_actual_usd, charge_final, last_error_code FROM apify_actor_runs WHERE id='legacy-run'"
    ).fetchone()
    assert tuple(row) == (0.08, None, 0, "apify_historical_cost_quarantined")
    store.close()


@pytest.mark.parametrize("kind", ("unauthorized", "rate_limited", "unavailable"))
def test_remote_uncertainty_stays_a_migration_blocker(tmp_path: Path, kind: str) -> None:
    store = _store(tmp_path)
    _run(store)
    report = scan_legacy_costs(
        store.connect(), _Reader({"remote-run": RemoteCostObservation(kind)}),
        limit=20, salt="test-salt",
    )
    assert report.counts == {"remote_blocked": 1}
    evidence = build_evidence(report)
    with pytest.raises(LegacyCostAuditError, match="unresolved"):
        apply_evidence(
            store.connect(), evidence, expected_hash=str(evidence["evidence_hash"]),
            confirmed_upper_bound_usd=0.05,
        )
    assert migration_module.migration_blockers(store.connect())["run_costs"] == 1
    store.close()


def test_terminal_orphan_attempt_needs_explicit_upper_bound_acceptance(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _attempt(store, reserved=0.06)
    report = scan_legacy_costs(store.connect(), _Reader({}), limit=20, salt="test-salt")
    evidence = build_evidence(report)
    assert report.counts == {"quarantine_attempt": 1}
    assert report.upper_bound_usd == 0.06
    with pytest.raises(LegacyCostAuditError, match="upper-bound"):
        apply_evidence(
            store.connect(), evidence, expected_hash=str(evidence["evidence_hash"]),
            confirmed_upper_bound_usd=0.05,
        )
    apply_evidence(
        store.connect(), evidence, expected_hash=str(evidence["evidence_hash"]),
        confirmed_upper_bound_usd=0.06,
    )
    row = store.connect().execute(
        "SELECT cost_final, actual_cost_usd, last_error_code FROM apify_actor_attempts WHERE id='legacy-attempt'"
    ).fetchone()
    assert tuple(row) == (0, None, "apify_historical_attempt_ledger_missing")
    store.close()


def test_unknown_start_and_nonterminal_attempts_cannot_be_quarantined(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _run(store, status="start_outcome_unknown")
    _attempt(store, status="running")
    report = scan_legacy_costs(store.connect(), _Reader({}), limit=20, salt="test-salt")
    assert report.counts == {"nonterminal_attempt": 1, "nonterminal_run": 1}
    with pytest.raises(LegacyCostAuditError, match="unresolved"):
        apply_evidence(
            store.connect(), build_evidence(report), expected_hash=str(build_evidence(report)["evidence_hash"]),
            confirmed_upper_bound_usd=0.0,
        )
    store.close()


def test_only_audited_terminal_quarantines_are_excluded_from_migration_cost_blocks(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _run(store, run_id="quarantined", remote_run_id="gone")
    _run(store, run_id="unreviewed", remote_run_id="unknown")
    report = scan_legacy_costs(
        store.connect(), _Reader({"gone": RemoteCostObservation.not_found()}),
        limit=1, salt="test-salt",
    )
    evidence = build_evidence(report)
    apply_evidence(store.connect(), evidence, expected_hash=str(evidence["evidence_hash"]), confirmed_upper_bound_usd=0.05)
    assert migration_module.migration_blockers(store.connect())["run_costs"] == 1
    store.connect().execute("UPDATE apify_actor_runs SET last_error_code='not-a-safe-code' WHERE id='unreviewed'")
    store.connect().commit()
    assert migration_module.migration_blockers(store.connect())["run_costs"] == 1
    store.close()


def test_cli_scan_snapshot_and_dry_run_are_safe_and_redacted(tmp_path: Path) -> None:
    from scripts.audit_actorops_v2_legacy_costs import quarantine, scan, snapshot

    store = _store(tmp_path)
    _run(store, remote_run_id="remote-secret-looking-id")
    data_dir = tmp_path / "data"
    database = data_dir / "service.db"
    before = database.read_bytes()
    reader = _Reader({"remote-secret-looking-id": RemoteCostObservation.not_found()})
    evidence = scan(data_dir, reader=reader, salt="test-salt")
    assert database.read_bytes() == before
    assert "remote-secret-looking-id" not in json.dumps(evidence, sort_keys=True)
    dry_run = quarantine(
        data_dir, evidence=evidence, expected_hash=str(evidence["evidence_hash"]),
        confirmed_upper_bound_usd=0.05, apply=False,
    )
    assert dry_run["status"] == "dry_run"
    assert database.read_bytes() == before
    evidence_path = tmp_path / "evidence" / "legacy-costs.json"
    report = snapshot(
        data_dir, evidence_path=evidence_path, backup_dir=tmp_path / "backups",
        reader=reader, services_stopped=True,
    )
    assert report["status"] == "snapshotted"
    assert evidence_path.stat().st_mode & 0o777 == 0o600
    assert "remote-secret-looking-id" not in evidence_path.read_text(encoding="utf-8")
    assert {path.stat().st_mode & 0o777 for path in (tmp_path / "backups").glob("*.db")} == {0o600}
    store.close()


def test_cli_apply_requires_explicit_evidence_and_creates_a_private_backup(tmp_path: Path) -> None:
    from scripts.audit_actorops_v2_legacy_costs import quarantine, scan

    store = _store(tmp_path)
    _run(store)
    evidence = scan(
        tmp_path / "data", reader=_Reader({"remote-run": RemoteCostObservation.not_found()}),
        salt="test-salt",
    )
    with pytest.raises(RuntimeError, match="services-stopped"):
        quarantine(
            tmp_path / "data", evidence=evidence,
            expected_hash=str(evidence["evidence_hash"]),
            confirmed_upper_bound_usd=0.05, apply=True,
        )
    result = quarantine(
        tmp_path / "data", evidence=evidence, expected_hash=str(evidence["evidence_hash"]),
        confirmed_upper_bound_usd=0.05, apply=True, heartbeat_window_seconds=0,
        backup_dir=tmp_path / "backups", services_stopped=True,
    )
    assert result["status"] == "applied"
    assert result["backup_mode"] == "0o600"
    assert store.connect().execute(
        "SELECT last_error_code FROM apify_actor_runs WHERE id='legacy-run'"
    ).fetchone()[0] == "apify_historical_cost_quarantined"
    store.close()


def test_cli_remote_boundary_is_get_only_and_never_reads_global_25(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.audit_actorops_v2_legacy_costs as audit

    source = Path("scripts/audit_actorops_v2_legacy_costs.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = {
        node.attr for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in {"get", "post", "abort", "delete"}
    }
    assert calls == {"get"}
    assert "version = 25" not in source.casefold()
    assert "apify_actor_auto_pool_runs" not in source
    store = _store(tmp_path)
    statements: list[str] = []
    real_connect = sqlite3.connect

    def traced_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(audit.sqlite3, "connect", traced_connect)
    audit.status(tmp_path / "data")
    joined = "\n".join(statements).casefold()
    assert "version = 25" not in joined
    assert "apify_actor_auto_pool_runs" not in joined
    store.close()
