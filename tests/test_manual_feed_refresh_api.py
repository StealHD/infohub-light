import pytest

from src.services.job_queue import JobQueue
from src.storage.service_store import ServiceStore
from tests.api_service_test_support import (
    client,
    login,
    login_as,
    seed_manual_refresh_subscription,
)


def test_user_feed_refresh_rejects_empty_effective_scope_without_job_or_usage(
    tmp_path, monkeypatch
):
    api, data_dir = client(tmp_path, monkeypatch)
    login(api)

    response = api.post("/api/jobs/user-feed-refresh", json={})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_enabled_subscriptions"
    store = ServiceStore(data_dir)
    store.initialize()
    owner = store.get_user_by_username("owner")
    assert owner is not None
    assert store.connect().execute(
        "SELECT COUNT(*) FROM fetch_jobs WHERE user_id = ?", (owner["id"],)
    ).fetchone()[0] == 0
    assert store.connect().execute(
        "SELECT COUNT(*) FROM usage_events WHERE user_id = ?", (owner["id"],)
    ).fetchone()[0] == 0


@pytest.mark.parametrize(("role", "expected_scope"), [("member", "private"), ("admin", "all")])
def test_manual_refresh_scope_is_server_owned_by_current_role(
    role, expected_scope, tmp_path, monkeypatch
):
    api, data_dir = client(tmp_path, monkeypatch)
    login(api)
    api.post(
        "/api/users",
        json={"username": role, "password": f"{role}-password", "role": role},
    )
    seed_manual_refresh_subscription(data_dir, username=role, scope="private")
    store = ServiceStore(data_dir)
    store.initialize()
    workspace = store.get_default_workspace()
    actor = store.get_user_by_username(role)
    assert workspace is not None and actor is not None
    public_source = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=None,
        source_type="rss",
        display_name=f"{role} Public Refresh",
        config={"url": f"https://example.com/{role}-public-refresh.xml"},
    )
    store.create_subscription(user_id=actor["id"], source_id=public_source)
    api.post("/api/auth/logout")
    login_as(api, role, f"{role}-password")

    response = api.post(
        "/api/jobs/user-feed-refresh",
        json={"payload": {"reason": "forged", "refresh_scope": "all" if role == "member" else "private"}},
    )

    assert response.status_code == 200
    assert response.json()["data"]["payload_json"] == {
        "reason": "manual_service_refresh",
        "refresh_scope": expected_scope,
    }


def test_running_feed_refresh_cancel_is_persistent_idempotent_and_summary_visible(
    tmp_path, monkeypatch
):
    api, data_dir = client(tmp_path, monkeypatch)
    login(api)
    seed_manual_refresh_subscription(data_dir)
    created = api.post("/api/jobs/user-feed-refresh", json={}).json()["data"]
    queue = JobQueue(ServiceStore(data_dir))
    claimed = queue.claim_next_job(worker_id="safe-stop-worker")

    first = api.post(f"/api/jobs/{created['id']}/cancel")
    second = api.post(f"/api/jobs/{created['id']}/cancel")

    assert first.status_code == second.status_code == 200
    first_data = first.json()["data"]
    assert first_data["status"] == "running" and first_data["cancelled_at"]
    assert second.json()["data"]["cancelled_at"] == first_data["cancelled_at"]
    persisted = queue.get_job(created["id"])
    assert persisted is not None
    assert persisted["worker_id"] == "safe-stop-worker"
    assert persisted["claim_token"] == claimed["claim_token"]
    summaries = api.get(
        "/api/jobs?view=summary&scope=me&include_active=true&job_type=user_feed_refresh"
    ).json()["data"]["jobs"]
    assert summaries[0]["cancelled_at"] == first_data["cancelled_at"]


def test_other_running_jobs_remain_non_cancelable(tmp_path, monkeypatch):
    api, data_dir = client(tmp_path, monkeypatch)
    login(api)
    store = ServiceStore(data_dir)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    assert workspace is not None and owner is not None
    queue = JobQueue(store)
    job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="source_test",
        payload={"source_type": "rss"},
    )
    assert queue.claim_next_job(worker_id="source-test-worker")["id"] == job["id"]

    response = api.post(f"/api/jobs/{job['id']}/cancel")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "job_not_cancelable"
    assert queue.get_job(job["id"])["status"] == "running"
