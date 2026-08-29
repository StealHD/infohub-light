from __future__ import annotations

from src.apify_actor_identity import source_target_fingerprint
from src.services.actorops.repository import ActorOpsRepository
from src.services.worker_actorops_v2_repair import run_actorops_v2_repair
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def test_blocked_repair_job_is_not_reported_as_successful(tmp_path) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    connection = store.connect()
    route_id = str(connection.execute(
        "SELECT route_id FROM actor_routes_v2 WHERE platform='x'"
    ).fetchone()[0])
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID, scope="workspace",
        owner_user_id=None, source_type="apify_social",
        display_name="repair source", config={"target": "openai"},
    )
    fingerprint = source_target_fingerprint(
        DEFAULT_WORKSPACE_ID, route_id, "openai", platform="x"
    )
    repository = ActorOpsRepository(connection, DEFAULT_WORKSPACE_ID)
    with repository.transaction():
        connection.execute(
            """INSERT INTO actor_source_bindings_v2 (
                   binding_id, workspace_id, source_id, route_id,
                   target_fingerprint, status, binding_version,
                   created_at, updated_at
               ) VALUES ('repair-binding',?,?,?,?, 'ready',1,?,?)""",
            (
                DEFAULT_WORKSPACE_ID, source_id, route_id, fingerprint,
                "2026-08-20T00:00:00+00:00", "2026-08-20T00:00:00+00:00",
            ),
        )
    repair = repository.resilience.ensure_repair(
        route_id=route_id, source_id=source_id, origin_job_id="origin-job",
        trigger_code="actorops_route_exhausted",
    )
    result = run_actorops_v2_repair(
        {
            "id": "repair-job", "workspace_id": DEFAULT_WORKSPACE_ID,
            "payload_json": {"repair_id": str(repair["repair_id"])},
        },
        data_dir=str(store.data_dir), store=store,
    )
    assert result["status"] == "blocked"
    assert result["ok"] is False
    assert result["error_code"] == "actorops_repair_not_authorized"
    store.close()
