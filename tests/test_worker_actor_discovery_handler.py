from __future__ import annotations

from src.services.secret_store import SecretStore
from src.services.worker_actor_discovery_handler import (
    _DiscoveryContext,
    _metadata_token,
    _reconcile_x_candidate_eligibility,
)


def test_discovery_metadata_token_reads_runtime_secret_store(tmp_path) -> None:
    SecretStore(tmp_path).set("TEST_ACTOR_DISCOVERY_TOKEN", "runtime-secret")

    assert (
        _metadata_token(str(tmp_path), "TEST_ACTOR_DISCOVERY_TOKEN")
        == "runtime-secret"
    )


class _EligibilityOps:
    def __init__(self, candidates=None, stage="candidate_shortfall") -> None:
        self.store = type("Store", (), {"connect": lambda _: object()})()
        self.updated: dict[str, object] | None = None
        self.candidates = candidates or [
            {
                "revision_id": "revision-rejected",
                "selectable": False,
                "unavailable_reason": "apify_actor_target_identity_mismatch",
            }
        ]
        self.stage = stage

    def _project_compatibility_candidates(self, _connection, _route):
        return {"candidates": self.candidates}

    def get_discovery_run(self, _run_id: str):
        return {"stage": self.stage, "error_code": "candidate_shortfall"}

    def update_discovery_run(self, _run_id: str, **kwargs):
        self.updated = kwargs
        return {"stage": kwargs["stage"]}


class _Outcome:
    def __init__(self, run_id, route_id, stage, revision_ids, rejected) -> None:
        self.run_id = run_id
        self.route_id = route_id
        self.stage = stage
        self.revision_ids = revision_ids
        self.rejected = rejected


def test_x_discovery_count_excludes_terminal_canary_revisions() -> None:
    ops = _EligibilityOps()
    context = _DiscoveryContext(
        ops=ops,
        run_id="discovery-1",
        run={},
        prefer_existing=False,
        expanded_compatibility=True,
        global_ai=None,
        apify_env="",
        apify_token="",
        output_limit=0,
        ai_client=None,
        route={"platform": "x"},
    )
    outcome = _Outcome(
        "discovery-1",
        "route-1",
        "candidate_shortfall",
        ("revision-rejected",),
        (),
    )

    reconciled = _reconcile_x_candidate_eligibility(context, outcome)

    assert reconciled.revision_ids == ()
    assert reconciled.stage == "candidate_shortfall"
    assert ops.updated is not None
    assert ops.updated["candidate_count"] == 0
    assert ops.updated["rejections"] == (
        {
            "actor_id": "candidate-pool",
            "reason": "apify_actor_target_identity_mismatch",
        },
    )


def test_x_discovery_keeps_a_selectable_revision_count() -> None:
    ops = _EligibilityOps(
        candidates=[
            {
                "revision_id": "revision-ready",
                "selectable": True,
                "unavailable_reason": None,
                "publisher": "trusted-publisher",
            }
        ],
        stage="awaiting_canary_approval",
    )
    context = _DiscoveryContext(
        ops=ops,
        run_id="discovery-2",
        run={},
        prefer_existing=False,
        expanded_compatibility=True,
        global_ai=None,
        apify_env="",
        apify_token="",
        output_limit=0,
        ai_client=None,
        route={"platform": "x", "min_runtime_healthy": 1, "min_publishers": 1},
    )
    outcome = _Outcome(
        "discovery-2",
        "route-1",
        "awaiting_canary_approval",
        ("revision-ready",),
        (),
    )

    assert _reconcile_x_candidate_eligibility(context, outcome) is outcome
    assert ops.updated is None


def test_x_discovery_does_not_count_an_actor_already_in_the_active_pool() -> None:
    ops = _EligibilityOps(
        candidates=[
            {
                "revision_id": "revision-active",
                "selectable": True,
                "active_in_route": True,
                "publisher": "active-publisher",
            }
        ]
    )
    context = _DiscoveryContext(
        ops=ops,
        run_id="discovery-3",
        run={},
        prefer_existing=False,
        expanded_compatibility=True,
        global_ai=None,
        apify_env="",
        apify_token="",
        output_limit=0,
        ai_client=None,
        route={"platform": "x"},
    )
    outcome = _Outcome(
        "discovery-3",
        "route-1",
        "candidate_shortfall",
        ("revision-active",),
        (),
    )

    reconciled = _reconcile_x_candidate_eligibility(context, outcome)

    assert reconciled.revision_ids == ()
    assert ops.updated is not None
    assert ops.updated["candidate_count"] == 0
