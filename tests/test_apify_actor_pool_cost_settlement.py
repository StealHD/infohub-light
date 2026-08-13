"""Never-started validation cost settlement is intentionally narrow."""

from src.services.apify_actor_ops import ApifyActorOpsService
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore
from test_apify_actor_pool_staging_v18 import FIXED_NOW, _revision, _route


def _insert_validation(
    store: ServiceStore,
    *,
    validation_id: str,
    route_id: str,
    revision_id: str,
    outcome: str,
) -> None:
    store.connect().execute(
        """
        INSERT INTO apify_actor_validations (
            validation_id, workspace_id, route_id, revision_id, kind,
            target_fingerprint, status, semantic_outcome, cost_final,
            counts_toward_canary, created_at, completed_at
        ) VALUES (?, ?, ?, ?, 'route_reference', ?, 'failed', ?, 0, 0, ?, ?)
        """,
        (
            validation_id,
            DEFAULT_WORKSPACE_ID,
            route_id,
            revision_id,
            "a" * 64,
            outcome,
            FIXED_NOW.isoformat(),
            FIXED_NOW.isoformat(),
        ),
    )
    store.connect().commit()


def test_settlement_finalizes_only_proven_local_no_start_failures(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    route = _route(store, "x/profile")
    revision_id = _revision(
        ops,
        str(route["route_id"]),
        actor_id="pool-cost-settlement/x",
        publisher="pool-cost-settlement",
        build_number="1.0.0",
        host="x.com",
    )
    _insert_validation(
        store,
        validation_id="validation-prestart-revision",
        route_id=str(route["route_id"]),
        revision_id=revision_id,
        outcome="revision_not_executable",
    )
    _insert_validation(
        store,
        validation_id="validation-prestart-revoked",
        route_id=str(route["route_id"]),
        revision_id=revision_id,
        outcome="approval_revoked",
    )
    _insert_validation(
        store,
        validation_id="validation-not-proven",
        route_id=str(route["route_id"]),
        revision_id=revision_id,
        outcome="apify_run_status_unavailable",
    )

    settled = ops.reconcile_terminal_no_start_validation_costs()

    assert settled == {"validations": 2, "batch_items": 0, "batches": 0}
    rows = store.connect().execute(
        """SELECT validation_id, cost_usd, cost_final
           FROM apify_actor_validations
           ORDER BY validation_id"""
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("validation-not-proven", None, 0),
        ("validation-prestart-revision", 0.0, 1),
        ("validation-prestart-revoked", 0.0, 1),
    ]
    assert ops.reconcile_terminal_no_start_validation_costs()["validations"] == 0
