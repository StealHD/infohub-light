from __future__ import annotations

import json

from fastapi.testclient import TestClient
import pytest

from src.api.server import create_app
from src.services.apify_actor_route import ApifyActorRouteService
from src.services.job_queue import JobQueue
from src.services.quota import QuotaService
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _client(tmp_path, monkeypatch) -> tuple[TestClient, ServiceStore]:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    data_dir = tmp_path / "data"
    static_dir = tmp_path / "static"
    data_dir.mkdir()
    static_dir.mkdir()
    (data_dir / "config.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "ai": {"enabled": False},
                "tags": [],
                "personal_tags": [],
                "sources": {
                    "rss": [],
                    "github": [],
                    "hackernews": {"enabled": False},
                },
                "filtering": {
                    "ai_score_threshold": 7.5,
                    "time_window_hours": 24,
                },
            }
        ),
        encoding="utf-8",
    )
    (static_dir / "index.html").write_text(
        "<!doctype html>",
        encoding="utf-8",
    )
    app = create_app(data_dir=data_dir, static_dir=static_dir)
    store = ServiceStore(data_dir)
    store.initialize()
    return TestClient(app), store


def _login(
    client: TestClient,
    username: str = "owner",
    password: str = "secret-password",
) -> None:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200


def test_actor_route_admin_lifecycle_and_safe_projection(tmp_path, monkeypatch):
    client, _store = _client(tmp_path, monkeypatch)
    assert client.get(
        "/api/admin/apify-actor-routes/x/profile"
    ).status_code == 401
    _login(client)

    initial_response = client.get(
        "/api/admin/apify-actor-routes/x/profile"
    )
    assert initial_response.status_code == 200
    assert initial_response.headers["cache-control"] == "no-store"
    initial = initial_response.json()["data"]
    assert initial["route"] == "x/profile"
    assert initial["status"] == "degraded"
    assert [
        candidate["actor_public_name"]
        for candidate in initial["candidates"]
    ] == [
        "scrape.badger/twitter-tweets-scraper",
        "dami_studio/tweet-scraper",
        "xquik/x-tweet-scraper",
    ]
    assert [candidate["state"] for candidate in initial["candidates"]] == [
        "closed",
        "disabled",
        "open",
    ]
    for forbidden in (
        "remote_run_id",
        "dataset_id",
        "source_id",
        "job_id",
        "raw_error",
        "target",
        "token",
    ):
        assert forbidden not in initial_response.text

    reversed_ids = [
        candidate["id"] for candidate in reversed(initial["candidates"])
    ]
    reordered = client.put(
        "/api/admin/apify-actor-routes/x/profile/order",
        json={
            "candidate_ids": reversed_ids,
            "expected_generation": initial["generation"],
        },
    )
    assert reordered.status_code == 200, reordered.text
    reordered_data = reordered.json()["data"]
    assert [
        candidate["id"] for candidate in reordered_data["candidates"]
    ] == reversed_ids

    conflict = client.put(
        "/api/admin/apify-actor-routes/x/profile/order",
        json={
            "candidate_ids": reversed_ids,
            "expected_generation": initial["generation"],
        },
    )
    assert conflict.status_code == 409
    assert (
        conflict.json()["error"]["code"]
        == "apify_actor_route_generation_conflict"
    )

    client.post(
        "/api/users",
        json={
            "username": "member",
            "password": "member-password",
            "role": "member",
        },
    )
    client.post("/api/auth/logout")
    _login(client, "member", "member-password")
    denied = client.get("/api/admin/apify-actor-routes/x/profile")
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "forbidden"


def test_paid_canary_requires_confirmation_and_only_queues_one_job(
    tmp_path,
    monkeypatch,
):
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    owner = store.get_user_by_username(
        "owner",
        workspace_id=DEFAULT_WORKSPACE_ID,
    )
    assert owner is not None
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=owner["id"],
        source_type="apify_social",
        display_name="OpenAI on X",
        config={
            "platform": "x",
            "kind": "profile",
            "target": "OpenAI",
            "fetch_limit": 1,
        },
        source_key="apify:x:profile:openai-canary",
    )
    route = client.get(
        "/api/admin/apify-actor-routes/x/profile"
    ).json()["data"]
    candidate_id = route["candidates"][0]["id"]
    endpoint = (
        "/api/admin/apify-actor-routes/x/profile/candidates/"
        f"{candidate_id}/canary"
    )

    bypass = client.post(
        "/api/jobs/source-test",
        json={
            "source_id": source_id,
            "priority": 100,
            "payload": {
                "reason": "apify_actor_canary",
                "apify_actor_candidate_id": candidate_id,
                "apify_actor_route_generation": route["generation"],
            },
        },
    )
    assert bypass.status_code == 409
    assert (
        bypass.json()["error"]["code"]
        == "apify_actor_canary_unavailable"
    )
    assert store.connect().execute(
        "SELECT COUNT(*) FROM fetch_jobs"
    ).fetchone()[0] == 0

    missing_confirmation = client.post(
        endpoint,
        json={
            "source_id": source_id,
            "expected_generation": route["generation"],
        },
    )
    assert missing_confirmation.status_code == 400
    assert missing_confirmation.json()["error"]["code"] == "invalid_request"

    before_attempts = store.connect().execute(
        "SELECT COUNT(*) FROM apify_actor_attempts"
    ).fetchone()[0]
    before_runs = store.connect().execute(
        "SELECT COUNT(*) FROM apify_actor_runs"
    ).fetchone()[0]
    queued = client.post(
        endpoint,
        json={
            "source_id": source_id,
            "expected_generation": route["generation"],
            "confirmation": "确认付费试跑",
        },
    )

    assert queued.status_code == 200, queued.text
    jobs = JobQueue(store).list_jobs(
        workspace_id=DEFAULT_WORKSPACE_ID,
        user_id=owner["id"],
        status="queued",
    )
    assert len(jobs) == 1
    assert jobs[0]["max_attempts"] == 1
    assert jobs[0]["payload_json"] == {
        "reason": "apify_actor_canary",
        "apify_actor_candidate_id": candidate_id,
        "apify_actor_route_generation": route["generation"],
    }
    assert store.connect().execute(
        "SELECT COUNT(*) FROM apify_actor_attempts"
    ).fetchone()[0] == before_attempts
    assert store.connect().execute(
        "SELECT COUNT(*) FROM apify_actor_runs"
    ).fetchone()[0] == before_runs

    duplicate = client.post(
        endpoint,
        json={
            "source_id": source_id,
            "expected_generation": route["generation"],
            "confirmation": "确认付费试跑",
        },
    )
    assert duplicate.status_code == 409
    assert (
        duplicate.json()["error"]["code"]
        == "apify_actor_canary_active"
    )
    assert store.connect().execute(
        "SELECT COUNT(*) FROM fetch_jobs"
    ).fetchone()[0] == 1

    queued_job_id = jobs[0]["id"]
    store.connect().execute(
        """
        UPDATE fetch_jobs
        SET status = 'failed', finished_at = updated_at
        WHERE id = ?
        """,
        (queued_job_id,),
    )
    store.connect().commit()
    retry = client.post(f"/api/jobs/{queued_job_id}/retry")
    assert retry.status_code == 409
    assert retry.json()["error"]["code"] == "job_not_retryable"
    assert JobQueue(store).get_job(queued_job_id)["status"] == "failed"

    job_count = store.connect().execute(
        "SELECT COUNT(*) FROM fetch_jobs"
    ).fetchone()[0]
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "false")
    routing_disabled = client.post(
        endpoint,
        json={
            "source_id": source_id,
            "expected_generation": route["generation"],
            "confirmation": "确认付费试跑",
        },
    )
    assert routing_disabled.status_code == 409
    assert (
        routing_disabled.json()["error"]["code"]
        == "apify_actor_routing_disabled"
    )
    assert store.connect().execute(
        "SELECT COUNT(*) FROM fetch_jobs"
    ).fetchone()[0] == job_count
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")

    def fail_usage(*_args, **_kwargs):
        raise RuntimeError("usage write failed")

    monkeypatch.setattr(QuotaService, "record_job_usage", fail_usage)
    failed = client.post(
        endpoint,
        json={
            "source_id": source_id,
            "expected_generation": route["generation"],
            "confirmation": "确认付费试跑",
        },
    )
    assert failed.status_code == 500
    assert failed.json()["error"]["code"] == "internal_error"
    assert failed.headers["X-Request-ID"].startswith("req_")
    assert "usage write failed" not in failed.text
    assert store.connect().execute(
        "SELECT COUNT(*) FROM fetch_jobs"
    ).fetchone()[0] == job_count


def test_paid_canary_is_rejected_while_candidate_has_natural_attempt(
    tmp_path,
    monkeypatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    owner = store.get_user_by_username(
        "owner",
        workspace_id=DEFAULT_WORKSPACE_ID,
    )
    assert owner is not None
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=owner["id"],
        source_type="apify_social",
        display_name="Natural X source",
        config={
            "platform": "x",
            "kind": "profile",
            "target": "OpenAI",
            "fetch_limit": 1,
        },
        source_key="apify:x:profile:natural-canary-mutex",
    )
    route = ApifyActorRouteService(store)
    state = route.public_state()
    candidate_id = str(state["active_candidate_id"])
    route._reserve_next(
        source_id=source_id,
        job_id=None,
        attempt_group_id="api-natural-canary-mutex",
        excluded_candidate_ids=set(),
    )

    response = client.post(
        (
            "/api/admin/apify-actor-routes/x/profile/candidates/"
            f"{candidate_id}/canary"
        ),
        json={
            "source_id": source_id,
            "expected_generation": state["generation"],
            "confirmation": "确认付费试跑",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "apify_actor_canary_active"
    assert store.connect().execute(
        "SELECT COUNT(*) FROM fetch_jobs"
    ).fetchone()[0] == 0
