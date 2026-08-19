from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from src.services.apify_actor_ops import (
    FIRST_ACTIVATION_CONFIRMATION,
    PAID_CANARY_CONFIRMATION,
    ApifyActorOpsService,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _manifest(actor_id: str, build_number: str) -> dict:
    return {
        "version": 1,
        "actor_id": actor_id,
        "build_number": build_number,
        "input": {"startUrls": [{"url": {"$ref": "target.canonical_url"}}]},
        "output": {
            "native_id": {"pointers": ["/id"], "transforms": ["to_string"]},
            "url": {"pointers": ["/url"], "transforms": ["normalize_url"]},
            "published_at": {"pointers": ["/createdAt"], "transforms": ["parse_datetime"]},
            "title": {"pointers": ["/text"], "transforms": ["to_string"]},
            "author_handle": {"pointers": ["/author"], "transforms": ["to_string"]},
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


def test_ready_source_runs_healthy_slot_when_target_backup_is_paused(tmp_path) -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: now)
    route = next(row for row in ops.list_routes() if row["route_key"] == "x/profile")
    route_id = str(route["route_id"])
    revisions: list[tuple[str, str]] = []
    for number, publisher in enumerate(("publisher-a", "publisher-b"), start=1):
        actor_id = f"{publisher}/profile-{number}"
        candidate_id = ops.ensure_candidate(route_id, actor_id=actor_id)
        revision_id = ops.create_adapter_revision(
            candidate_id=candidate_id,
            actor_id=actor_id,
            publisher=publisher,
            build_id=f"build-{number}",
            build_number=f"1.0.{number}",
            manifest=_manifest(actor_id, f"1.0.{number}"),
            lifecycle="static_valid",
        )
        store.connect().execute(
            "UPDATE apify_actor_candidates SET state = 'closed' WHERE id = ?",
            (candidate_id,),
        )
        store.connect().execute(
            "UPDATE apify_actor_adapter_revisions SET lifecycle = 'certified' WHERE revision_id = ?",
            (revision_id,),
        )
        revisions.append((revision_id, candidate_id))
    store.connect().commit()
    active = ops.replace_active_pool(
        route_id,
        slots={"primary": revisions[0][0], "backup_1": revisions[1][0], "backup_2": None},
        expected_generation=int(route["generation"]),
    )
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="Source-bound X",
        config={"platform": "x", "kind": "profile", "target": "source-bound"},
    )
    binding = ops.bind_source(
        source_id=source_id,
        route_id=route_id,
        target_fingerprint=hashlib.sha256(b"source-bound").hexdigest(),
        mode="primary",
    )
    for revision_id, _candidate_id in revisions:
        validation = ops.approve_source_canary(
            source_id,
            revision_id,
            expected_generation=int(binding["generation"]),
            approval_id=f"source-runtime-{revision_id}",
            confirmation=PAID_CANARY_CONFIRMATION,
            max_cost_usd=0.01,
        )
        ops.record_validation(
            str(validation["validation_id"]),
            status="succeeded",
            semantic_outcome="valid_nonempty",
            cost_usd=0.001,
        )
    ready = ops.activate_binding(
        source_id,
        expected_generation=int(binding["generation"]),
        confirmation=FIRST_ACTIVATION_CONFIRMATION,
    )
    assert ready["validation_status"] == "ready_2of2"
    store.connect().execute(
        """
        INSERT INTO apify_actor_target_health (
            workspace_id, route_key, candidate_id, source_id,
            paused_until, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            DEFAULT_WORKSPACE_ID,
            "x/profile",
            revisions[1][1],
            source_id,
            (now + timedelta(hours=1)).isoformat(),
            now.isoformat(),
        ),
    )
    store.connect().commit()

    snapshot = ops.freeze_execution(str(active["route_id"]), source_id=source_id)

    assert [slot.revision_id for slot in snapshot.slots] == [revisions[0][0]]
