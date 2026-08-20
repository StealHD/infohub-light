from __future__ import annotations

import json
import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.observability_context import begin_observability_context, reset_observability_context
from src.services.actorops.domain import CandidateLifecycle, RuntimeMode
from src.services.actorops.identity import stable_actor_item_id
from src.services.actorops.repository import ActorOpsConflict, ActorOpsRepository
from src.services.actorops.service import ActorOpsCompatibilityService
from src.services.apify_native_fallback import YouTubeNativeActorFallbackScraper
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _repository(tmp_path: Path) -> tuple[ServiceStore, ActorOpsRepository, str]:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    connection = store.connect()
    route_id = str(
        connection.execute(
            "SELECT route_id FROM actor_routes_v2 WHERE platform='youtube'"
        ).fetchone()[0]
    )
    return store, ActorOpsRepository(connection, DEFAULT_WORKSPACE_ID), route_id


def test_route_mode_cas_only_allows_adjacent_transitions(tmp_path: Path) -> None:
    store, repository, route_id = _repository(tmp_path)
    route = repository.get_route(route_id)

    with pytest.raises(ActorOpsConflict):
        with repository.transaction():
            repository.transition_route_mode(
                route_id,
                current=RuntimeMode.DISABLED,
                target=RuntimeMode.ACTIVE,
                expected_generation=route.generation,
            )

    with repository.transaction():
        shadow = repository.transition_route_mode(
            route_id,
            current=RuntimeMode.DISABLED,
            target=RuntimeMode.SHADOW,
            expected_generation=route.generation,
        )
    assert shadow.runtime_mode is RuntimeMode.SHADOW
    assert shadow.generation == route.generation + 1

    with pytest.raises(ActorOpsConflict):
        with repository.transaction():
            repository.transition_route_mode(
                route_id,
                current=RuntimeMode.SHADOW,
                target=RuntimeMode.ACTIVE,
                expected_generation=route.generation,
            )
    store.close()


def test_forward_mode_change_rejects_its_own_unsettled_attempt(tmp_path: Path) -> None:
    store, repository, route_id = _repository(tmp_path)
    route = repository.get_route(route_id)
    with repository.transaction():
        repository.create_candidate(
            candidate_id="cutover-candidate",
            route_id=route_id,
            actor_id="publisher/cutover",
            publisher="publisher",
            build_id="build",
            build_number="1",
            manifest_json="{}",
            manifest_hash="c" * 64,
            input_schema_hash="i" * 64,
            output_schema_hash="o" * 64,
            lifecycle=CandidateLifecycle.CERTIFIED,
        )
        repository.create_attempt(
            attempt_id="cutover-attempt",
            idempotency_key="cutover-attempt-key",
            route_id=route_id,
            candidate_id="cutover-candidate",
            kind="fetch",
            attempt_group_id="cutover-group",
            attempt_index=0,
            route_generation=route.generation,
            binding_version=None,
            target_fingerprint="a" * 64,
            reserved_usd=0.05,
        )
        with pytest.raises(ActorOpsConflict):
            repository.transition_route_mode(
                route_id,
                current=RuntimeMode.DISABLED,
                target=RuntimeMode.SHADOW,
                expected_generation=route.generation,
            )
    store.close()


def test_cutover_blockers_scope_to_one_route(tmp_path: Path) -> None:
    store, repository, route_id = _repository(tmp_path)
    connection = store.connect()
    other_route = str(
        connection.execute(
            "SELECT route_id FROM actor_routes_v2 WHERE route_id != ?", (route_id,)
        ).fetchone()[0]
    )
    candidate_id = str(
        connection.execute(
            "SELECT candidate_id FROM actor_candidates_v2 WHERE route_id=? LIMIT 1",
            (other_route,),
        ).fetchone()[0]
    )
    connection.execute(
        """INSERT INTO actor_attempts_v2(
               attempt_id, workspace_id, idempotency_key, route_id, candidate_id,
               kind, attempt_group_id, attempt_index, route_generation,
               target_fingerprint, status, reserved_usd, cost_final, generation,
               created_at, updated_at
           ) VALUES ('other-route-attempt', ?, 'other-route-key', ?, ?, 'fetch',
               'other-route-group', 1, 1, 'fingerprint', 'starting', 0.05, 0, 1,
               '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')""",
        (DEFAULT_WORKSPACE_ID, other_route, candidate_id),
    )
    connection.commit()
    assert repository.cutover_blockers(route_id) == {
        "active_attempts": 0,
        "unsettled_costs": 0,
    }
    store.close()


def test_shadow_selection_is_observed_without_v2_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, repository, route_id = _repository(tmp_path)
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="shadow source",
        config={"platform": "youtube", "kind": "channel", "target": "channel"},
    )
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        "src.services.actorops.service.safe_emit_operation_event",
        lambda **event: events.append(event) or True,
    )
    service = ActorOpsCompatibilityService(store, workspace_id=DEFAULT_WORKSPACE_ID)
    service.v1.freeze_execution = lambda *_args, **_kwargs: object()
    route = repository.get_route(route_id)
    with repository.transaction():
        repository.transition_route_mode(
            route_id,
            current=RuntimeMode.DISABLED,
            target=RuntimeMode.SHADOW,
            expected_generation=route.generation,
        )

    token = begin_observability_context(job_id="shadow-job", source_id=source_id)
    try:
        assert service.freeze_execution(route_id, source_id=source_id) is not None
    finally:
        reset_observability_context(token)
    assert events[-1]["action"] == "actorops_v2_shadow_selection"
    assert events[-1]["outcome"] == "unavailable"
    assert events[-1]["job_id"] == "shadow-job"
    assert events[-1]["route"] == "/actorops/v2/shadow"
    assert events[-1]["counts"] == {"candidates": 0, "shadow_mode": 1}
    assert store.connect().execute("SELECT COUNT(*) FROM actor_attempts_v2").fetchone()[0] == 0
    store.close()


def test_stable_actor_identity_matches_v1_runtime_formula() -> None:
    assert stable_actor_item_id("x", "x:openai", "123") == (
        "actor:x:8f98772c776b5c732c1f94f6"
    )
    assert stable_actor_item_id("instagram", "ig:openai", "abc").startswith(
        "actor:instagram:"
    )


def test_cutover_cli_status_is_read_only(tmp_path: Path) -> None:
    from scripts.actorops_v2_cutover import status

    store, repository, route_id = _repository(tmp_path)
    database = tmp_path / "data" / "service.db"
    before = database.read_bytes()
    report = status(tmp_path / "data", platform="youtube")
    assert report["status"] == "blocked"
    assert report["route"]["route_id"] == route_id
    assert database.read_bytes() == before
    json.dumps(report, sort_keys=True)
    assert repository.get_route(route_id).route_id == route_id
    store.close()


def test_cutover_cli_never_queries_global_25(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.actorops_v2_cutover as cutover

    store, repository, route_id = _repository(tmp_path)
    statements: list[str] = []
    real_connect = sqlite3.connect

    def traced_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(cutover.sqlite3, "connect", traced_connect)
    cutover.status(tmp_path / "data", platform="youtube")
    joined = "\n".join(statements).casefold()
    assert "version = 25" not in joined
    assert "apify_actor_auto_pool_runs" not in joined
    assert repository.get_route(route_id).route_id == route_id
    store.close()


def test_cutover_cli_transition_dry_run_has_zero_writes_and_apply_is_cas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.actorops_v2_cutover as cutover

    store, repository, route_id = _repository(tmp_path)
    route = store.connect().execute(
        "SELECT generation FROM actor_routes_v2 WHERE route_id=?", (route_id,)
    ).fetchone()
    report = {
        "status": "ready",
        "route": {
            "route_id": route_id,
            "runtime_mode": "disabled",
            "generation": int(route[0]),
            "per_run_cap_usd": 0.05,
        },
        "runnable_candidate_count": 1,
        "blocker_counts": {"active_attempts": 0, "unsettled_costs": 0},
    }
    monkeypatch.setattr(cutover, "status", lambda *_args, **_kwargs: report)
    monkeypatch.setattr(cutover, "active_workers_fail_closed", lambda _database: [])
    database = tmp_path / "data" / "service.db"
    before = database.read_bytes()
    dry_run = cutover.transition(
        tmp_path / "data", platform="youtube", current=RuntimeMode.DISABLED,
        target=RuntimeMode.SHADOW, expected_generation=int(route[0]), apply=False,
    )
    assert dry_run["status"] == "dry_run"
    assert database.read_bytes() == before
    applied = cutover.transition(
        tmp_path / "data", platform="youtube", current=RuntimeMode.DISABLED,
        target=RuntimeMode.SHADOW, expected_generation=int(route[0]), apply=True,
    )
    assert applied["generation"] == int(route[0]) + 1
    assert store.connect().execute(
        "SELECT runtime_mode FROM actor_routes_v2 WHERE route_id=?", (route_id,)
    ).fetchone()[0] == "shadow"
    assert repository.get_route(route_id).generation == int(route[0]) + 1
    store.close()


def test_cutover_snapshot_uses_private_backup_and_safe_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.actorops_v2_cutover import snapshot

    store, repository, route_id = _repository(tmp_path)
    monkeypatch.setattr(
        "scripts.actorops_v2_cutover.active_workers_fail_closed", lambda _database: []
    )
    result = snapshot(tmp_path / "data", platform="youtube", backup_dir=tmp_path / "backups")
    backup = Path(result["backup"])
    evidence = Path(result["evidence"])
    assert backup.stat().st_mode & 0o777 == 0o600
    assert evidence.stat().st_mode & 0o777 == 0o600
    contents = evidence.read_text().casefold()
    assert "manifest_json" not in contents
    assert "target_fingerprint" not in contents
    assert "secret_ref" not in contents
    assert repository.get_route(route_id).route_id == route_id
    store.close()


def test_youtube_rss_wrapper_keeps_a_v2_handle_out_of_v1_runtime(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    result = [object()]
    monkeypatch.setattr(
        "src.services.actorops.youtube_rss_compat.fetch_v2_youtube_rss",
        lambda **_kwargs: _return(result),
    )
    source = SimpleNamespace(url="https://www.youtube.com/feeds/videos.xml?channel_id=UCabcdefghijklmnopqrstuv")
    scraper = object.__new__(YouTubeNativeActorFallbackScraper)
    scraper.source = source
    scraper.actor_ops = object()
    scraper.apify_coordinator = object()
    scraper.client = object()
    scraper.job_id = "job-1"
    scraper.publication_snapshots = []
    snapshot = SimpleNamespace(actorops_version=2)

    observed = asyncio.run(
        scraper._fetch_actor({"route_id": "route-youtube"}, snapshot, datetime.now())
    )

    assert observed is result
    assert scraper.publication_snapshots == [snapshot]


async def _return(value: object) -> object:
    return value
