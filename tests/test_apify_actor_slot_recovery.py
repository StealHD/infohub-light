from datetime import timedelta

from test_apify_actor_pool_staging_v18 import FIXED_NOW, _ready_source, _two_actor_pool

from src.services.apify_actor_ops import ApifyActorOpsService
from src.services.apify_actor_slot_recovery import recover_source_proven_slots
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
