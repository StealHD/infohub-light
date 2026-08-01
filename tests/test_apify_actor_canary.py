import asyncio
import hashlib
from types import SimpleNamespace

import pytest

from src.services.apify_actor_canary import (
    ApifyActorCanaryRunner,
    next_reference_fingerprint,
)
from src.services.apify_actor_ops import (
    ActorOpsError,
    ApifyActorOpsService,
    PAID_CANARY_CONFIRMATION,
    source_target_fingerprint,
)
from src.services.job_queue import JobQueue
from src.storage.service_store import ServiceStore


def _manifest():
    return {
        "version": 1,
        "actor_id": "publisher/reference-actor",
        "build_number": "1.0.1",
        "input": {
            "url": {"$ref": "target.canonical_url"},
            "maxItems": {"$ref": "runtime.max_items"},
        },
        "output": {
            "native_id": {"pointers": ["/id"]},
            "url": {
                "pointers": ["/url"],
                "transforms": ["normalize_url"],
            },
            "published_at": {
                "pointers": ["/publishedAt"],
                "transforms": ["parse_datetime"],
            },
            "title": {"pointers": ["/title"]},
            "author_handle": {"pointers": ["/handle"]},
        },
        "semantics": {
            "identity": {
                "output_field": "author_handle",
                "target_ref": "target.handle",
                "match": "handle",
            },
            "url_host_allowlist": ["x.com"],
        },
    }


class _Client:
    def __init__(self):
        self.calls = []

    async def run_actor_detailed(self, actor_id, actor_input, **kwargs):
        self.calls.append((actor_id, dict(actor_input), dict(kwargs)))
        assert actor_id == "publisher/reference-actor"
        assert kwargs["build_number"] == "1.0.1"
        assert kwargs["max_paid_dataset_items"] == 1
        return SimpleNamespace(
            items=[
                {
                    "id": "post-1",
                    "url": "https://x.com/openai/status/1",
                    "publishedAt": "2020-01-01T00:00:00Z",
                    "title": "Reference post",
                    "handle": "openai",
                }
            ],
            actual_charge_usd=0.01,
        )


def test_paid_canary_uses_exact_revision_and_persists_only_semantic_evidence(
    tmp_path,
):
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store)
    route = next(
        route for route in ops.list_routes() if route["route_key"] == "x/profile"
    )
    candidate_id = ops.ensure_candidate(
        route["route_id"],
        actor_id="publisher/reference-actor",
    )
    revision_id = ops.create_adapter_revision(
        candidate_id=candidate_id,
        actor_id="publisher/reference-actor",
        publisher="publisher",
        build_id="build-id",
        build_number="1.0.1",
        manifest=_manifest(),
        input_schema_hash=hashlib.sha256(b"input").hexdigest(),
        output_schema_hash=hashlib.sha256(b"output").hexdigest(),
        lifecycle="static_valid",
    )
    validation = ops.approve_revision_canary(
        route["route_id"],
        revision_id,
        expected_generation=route["generation"],
        approval_id="approval-route-canary",
        confirmation=PAID_CANARY_CONFIRMATION,
        max_cost_usd=0.02,
        reference_fingerprint=next_reference_fingerprint(
            store,
            workspace_id=ops.workspace_id,
            platform="x",
            route_id=str(route["route_id"]),
            revision_id=revision_id,
        ),
    )
    owner = store.create_user(
        workspace_id=ops.workspace_id,
        username="canary-admin",
        password="safe-test-password",
        role="admin",
    )
    job = JobQueue(store).create_job(
        workspace_id=ops.workspace_id,
        user_id=owner["id"],
        job_type="apify_actor_validation",
        payload={"validation_id": validation["validation_id"]},
        priority=100,
        max_attempts=1,
    )

    actor_client = _Client()
    result = asyncio.run(
        ApifyActorCanaryRunner(store, ops, actor_client).run(
            validation["validation_id"],
            job_id=job["id"],
        )
    )

    assert result.status == "succeeded"
    assert result.semantic_outcome == "valid_nonempty"
    row = store.connect().execute(
        """
        SELECT status, semantic_outcome, cost_usd, attempt_id
        FROM apify_actor_validations
        WHERE validation_id = ?
        """,
        (validation["validation_id"],),
    ).fetchone()
    assert tuple(row) == (
        "succeeded",
        "valid_nonempty",
        0.01,
        row["attempt_id"],
    )
    assert row["attempt_id"]
    columns = {
        str(column[1])
        for column in store.connect().execute(
            "PRAGMA table_info(apify_actor_validations)"
        ).fetchall()
    }
    assert "dataset_json" not in columns
    assert "actor_input_json" not in columns
    assert len(actor_client.calls) == 1
    kwargs = actor_client.calls[0][2]
    assert kwargs["max_remote_starts"] == 1
    assert kwargs["max_total_charge_usd"] == 0.02
    assert kwargs["expected_pool_generation"] == store.connect().execute(
        """
        SELECT generation FROM apify_key_pool_state
        WHERE workspace_id = ?
        """,
        (ops.workspace_id,),
    ).fetchone()["generation"]


def test_paid_canary_records_remote_charge_when_output_mapping_fails(tmp_path):
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store)
    route = next(
        route for route in ops.list_routes() if route["route_key"] == "x/profile"
    )
    candidate_id = ops.ensure_candidate(
        route["route_id"],
        actor_id="publisher/reference-actor",
    )
    revision_id = ops.create_adapter_revision(
        candidate_id=candidate_id,
        actor_id="publisher/reference-actor",
        publisher="publisher",
        build_id="build-cost-evidence",
        build_number="1.0.1",
        manifest=_manifest(),
        lifecycle="static_valid",
    )
    validation = ops.approve_revision_canary(
        route["route_id"],
        revision_id,
        expected_generation=route["generation"],
        approval_id="approval-cost-evidence",
        confirmation=PAID_CANARY_CONFIRMATION,
        max_cost_usd=0.02,
        reference_fingerprint=next_reference_fingerprint(
            store,
            workspace_id=ops.workspace_id,
            platform="x",
            route_id=str(route["route_id"]),
            revision_id=revision_id,
        ),
    )
    owner = store.create_user(
        workspace_id=ops.workspace_id,
        username="canary-cost-admin",
        password="safe-test-password",
        role="admin",
    )
    job = JobQueue(store).create_job(
        workspace_id=ops.workspace_id,
        user_id=owner["id"],
        job_type="apify_actor_validation",
        payload={"validation_id": validation["validation_id"]},
        priority=100,
        max_attempts=1,
    )

    class InvalidClient:
        async def run_actor_detailed(self, *_args, **_kwargs):
            return SimpleNamespace(
                items=[{"unexpected": "contract drift"}],
                actual_charge_usd=0.013,
            )

    with pytest.raises(ActorOpsError):
        asyncio.run(
            ApifyActorCanaryRunner(store, ops, InvalidClient()).run(
                validation["validation_id"],
                job_id=job["id"],
            )
        )

    row = store.connect().execute(
        """
        SELECT validation.status, validation.cost_usd,
               attempt.actual_cost_usd
        FROM apify_actor_validations AS validation
        JOIN apify_actor_attempts AS attempt
          ON attempt.id = validation.attempt_id
        WHERE validation.validation_id = ?
        """,
        (validation["validation_id"],),
    ).fetchone()
    assert dict(row) == {
        "status": "failed",
        "cost_usd": 0.013,
        "actual_cost_usd": 0.013,
    }


def test_route_canary_generation_change_cancels_same_timestamp_approval(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store)
    route = next(
        route for route in ops.list_routes() if route["route_key"] == "x/profile"
    )
    candidate_id = ops.ensure_candidate(
        route["route_id"],
        actor_id="publisher/reference-actor",
    )
    revision_id = ops.create_adapter_revision(
        candidate_id=candidate_id,
        actor_id="publisher/reference-actor",
        publisher="publisher",
        build_id="build-stale-route",
        build_number="1.0.1",
        manifest=_manifest(),
        lifecycle="static_valid",
    )
    validation = ops.approve_revision_canary(
        route["route_id"],
        revision_id,
        expected_generation=route["generation"],
        approval_id="approval-stale-route-generation",
        confirmation=PAID_CANARY_CONFIRMATION,
        max_cost_usd=0.02,
        reference_fingerprint=next_reference_fingerprint(
            store,
            workspace_id=ops.workspace_id,
            platform="x",
            route_id=str(route["route_id"]),
            revision_id=revision_id,
        ),
    )
    created_at = store.connect().execute(
        """
        SELECT created_at FROM apify_actor_validations
        WHERE validation_id = ?
        """,
        (validation["validation_id"],),
    ).fetchone()["created_at"]
    store.connect().execute(
        """
        UPDATE apify_actor_route_profiles
        SET generation = generation + 1, updated_at = ?
        WHERE route_id = ?
        """,
        (created_at, route["route_id"]),
    )
    store.connect().commit()
    actor_client = _Client()

    with pytest.raises(ActorOpsError) as caught:
        asyncio.run(
            ApifyActorCanaryRunner(store, ops, actor_client).run(
                validation["validation_id"],
                job_id="job-stale-route-generation",
            )
        )

    assert caught.value.code == "apify_actor_canary_approval_stale"
    assert actor_client.calls == []
    persisted = store.connect().execute(
        """
        SELECT status, semantic_outcome FROM apify_actor_validations
        WHERE validation_id = ?
        """,
        (validation["validation_id"],),
    ).fetchone()
    assert tuple(persisted) == ("cancelled", "approval_stale")


def test_source_canary_generation_change_cancels_same_timestamp_approval(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store)
    route = next(
        route for route in ops.list_routes() if route["route_key"] == "x/profile"
    )
    revisions: list[str] = []
    actors = (
        ("publisher/reference-actor", "publisher"),
        ("publisher-b/reference-backup", "publisher-b"),
        ("publisher/reference-probationary", "publisher"),
    )
    for index, (actor_id, publisher) in enumerate(actors, start=1):
        manifest = _manifest()
        manifest["actor_id"] = actor_id
        manifest["build_number"] = f"1.0.{index}"
        candidate_id = ops.ensure_candidate(
            route["route_id"],
            actor_id=actor_id,
        )
        revision_id = ops.create_adapter_revision(
            candidate_id=candidate_id,
            actor_id=actor_id,
            publisher=publisher,
            build_id=f"build-source-{index}",
            build_number=f"1.0.{index}",
            manifest=manifest,
            lifecycle="static_valid",
        )
        store.connect().execute(
            """
            UPDATE apify_actor_adapter_revisions
            SET lifecycle = ?
            WHERE revision_id = ?
            """,
            (
                "certified" if index < 3 else "probationary",
                revision_id,
            ),
        )
        store.connect().commit()
        revisions.append(revision_id)
    active = ops.replace_active_pool(
        route["route_id"],
        slots={
            "primary": revisions[0],
            "backup_1": revisions[1],
            "backup_2": revisions[2],
        },
        expected_generation=route["generation"],
    )
    source_id = store.create_source(
        workspace_id=ops.workspace_id,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="Stale source Canary",
        config={"profile_id": route["route_id"], "target": "@openai"},
        enabled=False,
    )
    binding = ops.bind_source(
        source_id=source_id,
        route_id=route["route_id"],
        target_fingerprint=source_target_fingerprint(
            ops.workspace_id,
            route["route_id"],
            "@openai",
            platform="x",
        ),
        mode="primary",
    )
    validation = ops.approve_source_canary(
        source_id,
        revisions[0],
        expected_generation=binding["generation"],
        approval_id="approval-stale-source-generation",
        confirmation=PAID_CANARY_CONFIRMATION,
        max_cost_usd=0.02,
    )
    created_at = store.connect().execute(
        """
        SELECT created_at FROM apify_actor_validations
        WHERE validation_id = ?
        """,
        (validation["validation_id"],),
    ).fetchone()["created_at"]
    store.connect().execute(
        """
        UPDATE apify_source_route_bindings
        SET generation = generation + 1, updated_at = ?
        WHERE source_id = ?
        """,
        (created_at, source_id),
    )
    store.connect().commit()
    actor_client = _Client()

    with pytest.raises(ActorOpsError) as caught:
        asyncio.run(
            ApifyActorCanaryRunner(store, ops, actor_client).run(
                validation["validation_id"],
                job_id="job-stale-source-generation",
            )
        )

    assert active["generation"] == route["generation"] + 1
    assert caught.value.code == "apify_actor_canary_approval_stale"
    assert actor_client.calls == []
    persisted = store.connect().execute(
        """
        SELECT status, semantic_outcome FROM apify_actor_validations
        WHERE validation_id = ?
        """,
        (validation["validation_id"],),
    ).fetchone()
    assert tuple(persisted) == (
        "cancelled",
        "apify_actor_canary_approval_stale",
    )
