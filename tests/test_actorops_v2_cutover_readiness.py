from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

import scripts.repair_actorops_v2_binding_readiness as readiness_repair
from scripts.actorops_v2_cutover_legacy import legacy_summary
from src.services.apify_actor_ops import (
    FIRST_ACTIVATION_CONFIRMATION,
    PAID_CANARY_CONFIRMATION,
    ApifyActorOpsService,
)
from src.services.actorops.legacy_readiness import legacy_ready_binding_plans
from src.services.actorops.repository import ActorOpsConflict, ActorOpsRepository
from src.storage.actorops_v2_schema import V2_TABLES
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _manifest(actor_id: str, build_number: str) -> dict[str, object]:
    return {
        "version": 1,
        "actor_id": actor_id,
        "build_number": build_number,
        "input": {"startUrls": [{"url": {"$ref": "target.canonical_url"}}]},
        "output": {
            "native_id": {"pointers": ["/id"], "transforms": ["to_string"]},
            "url": {"pointers": ["/url"], "transforms": ["normalize_url"]},
            "published_at": {"pointers": ["/createdAt"], "transforms": ["parse_datetime"]},
            "title": {"pointers": ["/title"], "transforms": ["to_string"]},
            "source_native_id": {"pointers": ["/channelId"], "transforms": ["to_string"]},
        },
        "semantics": {
            "identity": {
                "output_field": "source_native_id",
                "target_ref": "target.native_id",
                "match": "exact",
            },
            "url_host_allowlist": ["youtube.com"],
        },
    }


def _drop_v2(store: ServiceStore) -> None:
    connection = store.connect()
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("BEGIN IMMEDIATE")
        for table in reversed(V2_TABLES):
            connection.execute(f"DROP TABLE IF EXISTS {table}")
        connection.execute("DELETE FROM schema_migrations WHERE version = 26")
        connection.commit()
    finally:
        connection.execute("PRAGMA foreign_keys = ON")


def _pending_binding_with_runnable_backup(data_dir: Path) -> tuple[ServiceStore, str]:
    store = ServiceStore(data_dir)
    store.initialize()
    ops = ApifyActorOpsService(store)
    route = next(item for item in ops.list_routes() if item["platform"] == "youtube")
    route_id = str(route["route_id"])
    revisions: list[str] = []
    for number in (1, 2):
        actor_id = f"publisher/youtube-readiness-{number}"
        candidate_id = ops.ensure_candidate(route_id, actor_id=actor_id)
        revision_id = ops.create_adapter_revision(
            candidate_id=candidate_id,
            actor_id=actor_id,
            publisher=f"publisher-{number}",
            build_id=f"build-{number}",
            build_number=f"1.0.{number}",
            manifest=_manifest(actor_id, f"1.0.{number}"),
            lifecycle="static_valid",
        )
        store.connect().execute(
            "UPDATE apify_actor_candidates SET state='closed' WHERE id=?", (candidate_id,)
        )
        store.connect().execute(
            "UPDATE apify_actor_adapter_revisions SET lifecycle='certified' WHERE revision_id=?",
            (revision_id,),
        )
        revisions.append(revision_id)
    store.connect().commit()
    active = ops.replace_active_pool(
        route_id,
        slots={"primary": revisions[0], "backup_1": revisions[1], "backup_2": None},
        expected_generation=int(route["generation"]),
    )
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="YouTube readiness source",
        config={"platform": "youtube", "kind": "channel", "target": "readiness-channel"},
    )
    binding = ops.bind_source(
        source_id=source_id,
        route_id=route_id,
        target_fingerprint=hashlib.sha256(b"readiness-channel").hexdigest(),
        mode="primary",
    )
    for revision_id in revisions:
        validation = ops.approve_source_canary(
            source_id,
            revision_id,
            expected_generation=int(binding["generation"]),
            approval_id=f"readiness-{revision_id}",
            confirmation=PAID_CANARY_CONFIRMATION,
            max_cost_usd=0.01,
        )
        ops.record_validation(
            str(validation["validation_id"]),
            status="succeeded",
            semantic_outcome="valid_nonempty",
            cost_usd=0.001,
        )
    ops.activate_binding(
        source_id,
        expected_generation=int(binding["generation"]),
        confirmation=FIRST_ACTIVATION_CONFIRMATION,
    )
    connection = store.connect()
    primary_candidate = connection.execute(
        "SELECT candidate_id FROM apify_route_active_slots WHERE route_id=? AND slot_name='primary'",
        (route_id,),
    ).fetchone()[0]
    connection.execute(
        "UPDATE apify_actor_adapter_revisions SET lifecycle='quarantined' WHERE revision_id=?",
        (revisions[0],),
    )
    connection.execute(
        "UPDATE apify_actor_candidates SET state='open' WHERE id=?", (primary_candidate,))
    connection.execute(
        "UPDATE apify_source_route_bindings SET validation_status='revalidation_pending' WHERE source_id=?",
        (source_id,),
    )
    connection.commit()
    _drop_v2(store)
    from scripts.migrate_actorops_v2 import migrate

    store.close()
    migrate(data_dir, apply=True, backup_dir=data_dir / "backups")
    return ServiceStore(data_dir), route_id


def test_terminal_legacy_slot_is_excluded_from_cutover_order(tmp_path: Path) -> None:
    store, route_id = _pending_binding_with_runnable_backup(tmp_path / "data")
    connection = store.connect()
    route = connection.execute(
        "SELECT * FROM actor_routes_v2 WHERE route_id=?", (route_id,)
    ).fetchone()

    report = legacy_summary(connection, DEFAULT_WORKSPACE_ID, route)

    assert report["slot_count"] == 1
    assert report["slot_mismatches"] == 0
    assert report["compatible"] is True
    store.close()


def test_pending_binding_requires_current_exact_v1_source_evidence(tmp_path: Path) -> None:
    store, route_id = _pending_binding_with_runnable_backup(tmp_path / "data")
    connection = store.connect()

    plans, report = legacy_ready_binding_plans(
        connection, workspace_id=DEFAULT_WORKSPACE_ID, route_id=route_id
    )

    assert len(plans) == 1
    assert report.planned_ready == 1
    binding = connection.execute(
        "SELECT source_id, target_fingerprint FROM actor_source_bindings_v2 WHERE route_id=?",
        (route_id,),
    ).fetchone()
    connection.execute(
        "DELETE FROM apify_actor_validations WHERE source_id=? AND target_fingerprint=?",
        (binding["source_id"], binding["target_fingerprint"]),
    )
    connection.commit()
    plans, report = legacy_ready_binding_plans(
        connection, workspace_id=DEFAULT_WORKSPACE_ID, route_id=route_id
    )
    assert plans == ()
    assert report.missing_source_evidence == 1
    store.close()


def test_readiness_repair_is_cas_backed_and_idempotent(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    store, route_id = _pending_binding_with_runnable_backup(data_dir)
    database = data_dir / "service.db"
    before = database.read_bytes()
    store.close()

    preview = readiness_repair.repair(data_dir, platform="youtube", apply=False)

    assert preview["status"] == "ready_to_apply"
    assert preview["counts"]["planned_ready"] == 1
    assert database.read_bytes() == before
    applied = readiness_repair.repair(
        data_dir, platform="youtube", apply=True, backup_dir=tmp_path / "backups"
    )
    assert applied["status"] == "applied"
    assert applied["ready_bindings"] == 1
    assert applied["backup_mode"] == "0o600"
    reopened = ServiceStore(data_dir)
    binding = reopened.connect().execute(
        "SELECT status, binding_version FROM actor_source_bindings_v2 WHERE route_id=?",
        (route_id,),
    ).fetchone()
    assert tuple(binding) == ("ready", 1)
    repository = ActorOpsRepository(reopened.connect(), DEFAULT_WORKSPACE_ID)
    with repository.transaction(), pytest.raises(ActorOpsConflict):
        repository.mark_binding_ready(
            str(reopened.connect().execute(
                "SELECT source_id FROM actor_source_bindings_v2 WHERE route_id=?", (route_id,)
            ).fetchone()[0]),
            expected_binding_version=1,
            expected_target_fingerprint="stale-fingerprint",
        )
    reopened.close()
    assert readiness_repair.repair(data_dir, platform="youtube", apply=False)["status"] == "already_ready"


def test_readiness_repair_never_queries_global_25(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    store, _route_id = _pending_binding_with_runnable_backup(data_dir)
    store.close()
    statements: list[str] = []
    real_connect = sqlite3.connect

    def traced_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(readiness_repair.sqlite3, "connect", traced_connect)
    assert readiness_repair.repair(data_dir, platform="youtube", apply=False)["status"] == "ready_to_apply"
    joined = "\n".join(statements).casefold()
    assert "version = 25" not in joined
    assert "apify_actor_auto_pool_runs" not in joined
