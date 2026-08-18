from datetime import timedelta

from test_apify_actor_pool_staging_v18 import FIXED_NOW, _ready_source, _two_actor_pool

from src.api.actor_ops_detail_projection import public_actor_ops_detail
from src.services.apify_actor_ops import ApifyActorOpsService
from src.services.apify_actor_slot_recovery import recover_source_proven_slots
from src.services.apify_actor_source_proof import current_source_validation_ids
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def test_recovery_requires_current_source_proof_after_the_open_failure(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    route, revisions = _two_actor_pool(store, ops)
    _ready_source(store, ops, route, revisions, suffix="slot-recovery")
    rows = store.connect().execute(
        """SELECT slot.slot_name, slot.candidate_id
           FROM apify_route_active_slots AS slot
           WHERE slot.workspace_id = ? AND slot.route_id = ?""",
        (DEFAULT_WORKSPACE_ID, route["route_id"]),
    ).fetchall()
    candidates = {str(row["slot_name"]): str(row["candidate_id"]) for row in rows}
    store.connect().execute(
        """UPDATE apify_actor_candidates
           SET state = 'open', last_error_code = 'apify_actor_revision_not_executable',
               last_failure_at = ? WHERE id = ?""",
        ((FIXED_NOW - timedelta(seconds=1)).isoformat(), candidates["primary"]),
    )
    store.connect().execute(
        """UPDATE apify_actor_candidates
           SET state = 'open', last_error_code = 'apify_actor_revision_not_executable',
               last_failure_at = ? WHERE id = ?""",
        ((FIXED_NOW + timedelta(seconds=1)).isoformat(), candidates["backup_1"]),
    )
    store.connect().commit()

    assert recover_source_proven_slots(store, workspace_id=DEFAULT_WORKSPACE_ID) == 1
    states = {
        str(row["id"]): str(row["state"])
        for row in store.connect().execute(
            "SELECT id, state FROM apify_actor_candidates WHERE id IN (?, ?)",
            (candidates["primary"], candidates["backup_1"]),
        )
    }
    assert states[candidates["primary"]] == "closed"
    assert states[candidates["backup_1"]] == "open"


def test_source_canary_reopens_only_when_current_proof_is_missing(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    route, revisions = _two_actor_pool(store, ops)
    source_id, binding = _ready_source(store, ops, route, revisions, suffix="recanary")
    connection = store.connect()
    connection.execute(
        """UPDATE apify_actor_validations SET completed_at = ?
           WHERE workspace_id = ? AND source_id = ? AND kind = 'source_canary'""",
        ((FIXED_NOW - timedelta(seconds=2)).isoformat(), DEFAULT_WORKSPACE_ID, source_id),
    )
    connection.execute(
        """UPDATE apify_actor_candidates
           SET state = 'open', last_error_code = 'apify_actor_revision_not_executable',
               last_failure_at = ?
           WHERE id IN (SELECT candidate_id FROM apify_route_active_slots
                        WHERE workspace_id = ? AND route_id = ?)""",
        ((FIXED_NOW - timedelta(seconds=1)).isoformat(), DEFAULT_WORKSPACE_ID, route["route_id"]),
    )
    connection.commit()
    target_fingerprint = str(
        connection.execute(
            """SELECT target_fingerprint FROM apify_source_route_bindings
               WHERE workspace_id = ? AND source_id = ?""",
            (DEFAULT_WORKSPACE_ID, source_id),
        ).fetchone()["target_fingerprint"]
    )

    assert current_source_validation_ids(
        connection, workspace_id=DEFAULT_WORKSPACE_ID, route_id=route["route_id"],
        source_id=source_id, target_fingerprint=target_fingerprint,
    ) == set()
    detail = public_actor_ops_detail(store, ops, route["route_id"])
    assert detail["source_validations"][0]["binding_status"] == "revalidation_pending"
    assert detail["source_validations"][0]["slots"][0]["can_canary"] is True
    primary = ops.approve_source_canary(
        source_id, revisions[0], expected_generation=binding["generation"],
        approval_id="recanary-primary", confirmation="确认付费试跑", max_cost_usd=0.02,
    )
    ops.record_validation(str(primary["validation_id"]), status="succeeded", semantic_outcome="valid_nonempty", cost_usd=0.01, cost_final=True)
    backup = ops.approve_source_canary(
        source_id, revisions[1], expected_generation=binding["generation"],
        approval_id="recanary-backup-01", confirmation="确认付费试跑", max_cost_usd=0.02,
    )
    ops.record_validation(str(backup["validation_id"]), status="succeeded", semantic_outcome="valid_nonempty", cost_usd=0.01, cost_final=True)

    assert recover_source_proven_slots(store, workspace_id=DEFAULT_WORKSPACE_ID) == 2
