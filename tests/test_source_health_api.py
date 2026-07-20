from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from src.api.server import create_app
from src.services.job_queue import JobQueue
from src.services.runtime_status import RuntimeStatusService
from src.services.source_health import SourceHealthService
from src.storage.service_store import ServiceStore


ITEM_KEYS = {
    "subscription_id",
    "source_id",
    "source_display_name",
    "source_type",
    "status",
    "last_attempt_at",
    "last_success_at",
    "last_failure_at",
    "consecutive_failures",
    "last_fetched_count",
    "last_issue",
    "last_job_id",
}
SUMMARY_KEYS = {"total", "unknown", "healthy", "degraded", "failing"}
EMPTY_SUMMARY = {
    "total": 0,
    "unknown": 0,
    "healthy": 0,
    "degraded": 0,
    "failing": 0,
}


def _store(tmp_path, monkeypatch) -> tuple[ServiceStore, dict, dict]:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    assert owner is not None
    return store, workspace, owner


def _client(tmp_path, monkeypatch) -> tuple[TestClient, ServiceStore, dict, dict]:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "test-session-secret")
    data_dir = tmp_path / "data"
    static_dir = tmp_path / "static"
    (data_dir / "site").mkdir(parents=True)
    static_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    client = TestClient(create_app(data_dir=data_dir, static_dir=static_dir))
    store = ServiceStore(data_dir)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    assert owner is not None
    return client, store, workspace, owner


def _login(client: TestClient, username: str, password: str) -> None:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200


def _source_subscription(
    store: ServiceStore,
    *,
    workspace: dict,
    user: dict,
    label: str,
    priority: int = 0,
    subscription_enabled: bool = True,
    source_enabled: bool = True,
) -> tuple[str, dict]:
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=user["id"],
        source_type="rss",
        display_name=f"{label} Display",
        config={
            "url": f"https://example.com/{label}.xml?payload=private",
            "payload": "private-payload",
            "claim_token": "private-claim",
        },
        source_key=f"rss:https://example.com/{label}.xml",
        secret_env=f"{label.upper()}_SECRET_ENV",
        enabled=source_enabled,
    )
    subscription = store.create_subscription(
        user_id=user["id"],
        source_id=source_id,
        enabled=subscription_enabled,
        priority=priority,
    )
    return source_id, subscription


def _insert_health(
    store: ServiceStore,
    *,
    workspace_id: str,
    user_id: str,
    source_id: str,
    subscription_id: str,
    status: str,
    last_attempt_at: str = "2026-07-11T02:00:00+00:00",
    last_success_at: str | None = None,
    last_failure_at: str | None = None,
    consecutive_failures: int = 0,
    last_fetched_count: int = 0,
    issue_stage: str | None = None,
    issue_code: str | None = None,
    issue_message: str | None = None,
    issue_retryable: bool | None = None,
    last_job_id: str | None = None,
) -> None:
    created_at = "2026-07-11T02:01:00+00:00"
    store.connect().execute(
        """
        INSERT INTO user_source_health (
            subscription_id, workspace_id, user_id, source_id, status,
            last_attempt_at, last_success_at, last_failure_at,
            consecutive_failures, last_fetched_count,
            last_issue_stage, last_issue_code, last_issue_message,
            last_issue_retryable, last_job_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            subscription_id,
            workspace_id,
            user_id,
            source_id,
            status,
            last_attempt_at,
            last_success_at,
            last_failure_at,
            consecutive_failures,
            last_fetched_count,
            issue_stage,
            issue_code,
            issue_message,
            None if issue_retryable is None else int(issue_retryable),
            last_job_id,
            created_at,
            created_at,
        ),
    )
    store.connect().commit()


def _add_health_subscription(
    store: ServiceStore,
    *,
    workspace: dict,
    user: dict,
    label: str,
    status: str | None,
    failure_at: str | None = None,
    issue_code: str | None = None,
    issue_message: str | None = None,
) -> dict:
    source_id, subscription = _source_subscription(
        store,
        workspace=workspace,
        user=user,
        label=label,
    )
    if status is not None:
        _insert_health(
            store,
            workspace_id=workspace["id"],
            user_id=user["id"],
            source_id=source_id,
            subscription_id=subscription["id"],
            status=status,
            last_success_at=(
                "2026-07-11T01:00:00+00:00" if status == "healthy" else None
            ),
            last_failure_at=failure_at,
            consecutive_failures=2 if status == "failing" else int(status == "degraded"),
            issue_stage="fetch" if issue_code is not None else None,
            issue_code=issue_code,
            issue_message=issue_message,
            issue_retryable=True if issue_code is not None else None,
        )
    return subscription


def test_user_projection_without_subscriptions_has_exact_empty_shape(tmp_path, monkeypatch):
    store, workspace, owner = _store(tmp_path, monkeypatch)

    projection = SourceHealthService(store).user_projection(
        workspace_id=workspace["id"],
        user_id=owner["id"],
    )

    assert projection == {
        "schema_version": 1,
        "scope": "user",
        "summary": EMPTY_SUMMARY,
        "items": [],
    }


def test_user_projection_mixes_unknown_and_persisted_health_without_leaking_internal_fields(
    tmp_path,
    monkeypatch,
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    unknown_source, unknown = _source_subscription(
        store,
        workspace=workspace,
        user=owner,
        label="unknown",
        priority=40,
    )
    healthy_source, healthy = _source_subscription(
        store,
        workspace=workspace,
        user=owner,
        label="healthy",
        priority=30,
    )
    degraded_source, degraded = _source_subscription(
        store,
        workspace=workspace,
        user=owner,
        label="degraded",
        priority=20,
        subscription_enabled=False,
    )
    failing_source, failing = _source_subscription(
        store,
        workspace=workspace,
        user=owner,
        label="failing",
        priority=10,
        source_enabled=False,
    )
    job = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="source_fetch",
        source_id=healthy_source,
        subscription_id=healthy["id"],
        payload={"payload": "never-return", "claim_token": "never-return"},
    )
    _insert_health(
        store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=healthy_source,
        subscription_id=healthy["id"],
        status="healthy",
        last_success_at="2026-07-11T02:00:00+00:00",
        last_fetched_count=0,
        last_job_id=job["id"],
    )
    _insert_health(
        store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=degraded_source,
        subscription_id=degraded["id"],
        status="degraded",
        last_failure_at="2026-07-11T02:00:00+00:00",
        consecutive_failures=1,
        issue_stage="fetch",
        issue_code="TimeoutError",
        issue_message="safe timeout diagnostic",
        issue_retryable=False,
    )
    _insert_health(
        store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=failing_source,
        subscription_id=failing["id"],
        status="failing",
        last_failure_at="2026-07-11T02:00:00+00:00",
        consecutive_failures=2,
        issue_stage="fetch",
        issue_code="HTTPError",
        issue_message="safe http diagnostic",
        issue_retryable=True,
    )

    projection = SourceHealthService(store).user_projection(
        workspace_id=workspace["id"],
        user_id=owner["id"],
    )

    assert projection["summary"] == {
        "total": 4,
        "unknown": 1,
        "healthy": 1,
        "degraded": 1,
        "failing": 1,
    }
    assert [item["subscription_id"] for item in projection["items"]] == [
        unknown["id"],
        healthy["id"],
        degraded["id"],
        failing["id"],
    ]
    assert all(set(item) == ITEM_KEYS for item in projection["items"])
    assert projection["items"][0] == {
        "subscription_id": unknown["id"],
        "source_id": unknown_source,
        "source_display_name": "unknown Display",
        "source_type": "rss",
        "status": "unknown",
        "last_attempt_at": None,
        "last_success_at": None,
        "last_failure_at": None,
        "consecutive_failures": 0,
        "last_fetched_count": 0,
        "last_issue": None,
        "last_job_id": None,
    }
    assert projection["items"][1]["status"] == "healthy"
    assert projection["items"][1]["last_fetched_count"] == 0
    assert projection["items"][1]["last_job_id"] == job["id"]
    assert projection["items"][2]["last_issue"] == {
        "stage": "fetch",
        "code": "TimeoutError",
        "message": "safe timeout diagnostic",
        "retryable": False,
    }
    assert projection["items"][3]["last_issue"]["retryable"] is True
    assert store.connect().execute(
        "SELECT COUNT(*) FROM user_source_health WHERE subscription_id = ?",
        (unknown["id"],),
    ).fetchone()[0] == 0
    serialized = json.dumps(projection)
    for forbidden in (
        "source_key",
        "secret_env",
        "config",
        "private-payload",
        "private-claim",
        "claim_token",
        "last_issue_code",
        "last_issue_message",
    ):
        assert forbidden not in serialized


def test_user_projection_isolates_two_users_subscribed_to_the_same_public_source(
    tmp_path,
    monkeypatch,
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    member = store.create_user(
        workspace_id=workspace["id"],
        username="member",
        password="member-password",
    )
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Shared Public Feed",
        config={"url": "https://example.com/shared.xml"},
    )
    owner_subscription = store.create_subscription(user_id=owner["id"], source_id=source_id)
    member_subscription = store.create_subscription(user_id=member["id"], source_id=source_id)
    _insert_health(
        store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=owner_subscription["id"],
        status="healthy",
        last_success_at="2026-07-11T02:00:00+00:00",
    )
    _insert_health(
        store,
        workspace_id=workspace["id"],
        user_id=member["id"],
        source_id=source_id,
        subscription_id=member_subscription["id"],
        status="failing",
        last_failure_at="2026-07-11T02:00:00+00:00",
        consecutive_failures=2,
        issue_stage="fetch",
        issue_code="MemberOnlyError",
        issue_message="member only message",
        issue_retryable=True,
    )

    owner_projection = SourceHealthService(store).user_projection(
        workspace_id=workspace["id"],
        user_id=owner["id"],
    )
    member_projection = SourceHealthService(store).user_projection(
        workspace_id=workspace["id"],
        user_id=member["id"],
    )

    assert [item["subscription_id"] for item in owner_projection["items"]] == [
        owner_subscription["id"]
    ]
    assert owner_projection["items"][0]["status"] == "healthy"
    assert [item["subscription_id"] for item in member_projection["items"]] == [
        member_subscription["id"]
    ]
    assert member_projection["items"][0]["status"] == "failing"
    assert "member only message" not in json.dumps(owner_projection)


def test_source_health_api_all_roles_read_only_their_own_projection_and_admin_cannot_proxy(
    tmp_path,
    monkeypatch,
):
    client, store, workspace, owner = _client(tmp_path, monkeypatch)
    anonymous = client.get("/api/me/source-health")
    assert anonymous.status_code == 401
    assert anonymous.json()["error"]["code"] == "unauthorized"

    users = {"owner": owner}
    for username, role in (("admin", "admin"), ("member", "member"), ("viewer", "viewer")):
        users[username] = store.create_user(
            workspace_id=workspace["id"],
            username=username,
            password=f"{username}-password",
            role=role,
        )
    subscriptions = {}
    for index, (username, user) in enumerate(users.items()):
        source_id, subscription = _source_subscription(
            store,
            workspace=workspace,
            user=user,
            label=f"api-{username}",
            priority=index,
        )
        subscriptions[username] = subscription
        _insert_health(
            store,
            workspace_id=workspace["id"],
            user_id=user["id"],
            source_id=source_id,
            subscription_id=subscription["id"],
            status="healthy",
            last_success_at="2026-07-11T02:00:00+00:00",
        )

    for username in ("owner", "admin", "member", "viewer"):
        password = "secret-password" if username == "owner" else f"{username}-password"
        _login(client, username, password)
        response = client.get("/api/me/source-health")
        assert response.status_code == 200
        assert response.json()["ok"] is True
        data = response.json()["data"]
        assert set(data) == {"schema_version", "scope", "summary", "items"}
        assert set(data["summary"]) == SUMMARY_KEYS
        assert [item["subscription_id"] for item in data["items"]] == [
            subscriptions[username]["id"]
        ]
        assert all(set(item) == ITEM_KEYS for item in data["items"])
        client.post("/api/auth/logout")

    _login(client, "admin", "admin-password")
    proxied = client.get(
        "/api/me/source-health",
        params={"user_id": users["member"]["id"]},
    )
    assert proxied.status_code == 200
    assert [item["subscription_id"] for item in proxied.json()["data"]["items"]] == [
        subscriptions["admin"]["id"]
    ]
    assert subscriptions["member"]["id"] not in json.dumps(proxied.json())


def test_runtime_source_health_counts_respect_workspace_and_user_filters_and_unknowns(
    tmp_path,
    monkeypatch,
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    member = store.create_user(
        workspace_id=workspace["id"],
        username="runtime-member",
        password="member-password",
    )
    other_workspace = {
        "id": "workspace-other",
        "name": "Other Workspace",
    }
    store.connect().execute(
        "INSERT INTO workspaces (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (
            other_workspace["id"],
            other_workspace["name"],
            "2026-07-11T00:00:00+00:00",
            "2026-07-11T00:00:00+00:00",
        ),
    )
    store.connect().commit()
    outsider = store.create_user(
        workspace_id=other_workspace["id"],
        username="runtime-outsider",
        password="outsider-password",
    )
    _add_health_subscription(
        store,
        workspace=workspace,
        user=owner,
        label="runtime-unknown",
        status=None,
    )
    _add_health_subscription(
        store,
        workspace=workspace,
        user=member,
        label="runtime-healthy",
        status="healthy",
    )
    _add_health_subscription(
        store,
        workspace=workspace,
        user=member,
        label="runtime-failing",
        status="failing",
    )
    _add_health_subscription(
        store,
        workspace=other_workspace,
        user=outsider,
        label="runtime-other-degraded",
        status="degraded",
    )

    runtime = RuntimeStatusService(store)
    default_summary = runtime.summary(workspace_id=workspace["id"])
    owner_summary = runtime.summary(workspace_id=workspace["id"], user_id=owner["id"])
    other_summary = runtime.summary(workspace_id=other_workspace["id"])

    assert default_summary["source_health_counts"] == {
        "total": 3,
        "unknown": 1,
        "healthy": 1,
        "degraded": 0,
        "failing": 1,
    }
    assert owner_summary["source_health_counts"] == {
        "total": 1,
        "unknown": 1,
        "healthy": 0,
        "degraded": 0,
        "failing": 0,
    }
    assert other_summary["source_health_counts"] == {
        "total": 1,
        "unknown": 0,
        "healthy": 0,
        "degraded": 1,
        "failing": 0,
    }


def test_runtime_recent_failure_codes_use_deterministic_24_hour_window_and_grouping(
    tmp_path,
    monkeypatch,
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    member = store.create_user(
        workspace_id=workspace["id"],
        username="failure-member",
        password="member-password",
    )
    now = datetime(2026, 7, 11, 12, 0, 0, 123456, tzinfo=timezone.utc)
    at_boundary = (now - timedelta(hours=24)).isoformat()
    within_window = (now - timedelta(hours=1)).isoformat()
    too_old = (now - timedelta(hours=24, microseconds=1)).isoformat()
    in_future = (now + timedelta(microseconds=1)).isoformat()
    for label, failure_at, code in (
        ("failure-boundary", at_boundary, "TimeoutError"),
        ("failure-within", within_window, "TimeoutError"),
        ("failure-old", too_old, "TooOldError"),
        ("failure-future", in_future, "FutureError"),
        ("failure-empty", within_window, "   "),
        ("failure-none", within_window, None),
    ):
        _add_health_subscription(
            store,
            workspace=workspace,
            user=owner,
            label=label,
            status="failing",
            failure_at=failure_at,
            issue_code=code,
            issue_message=f"private message for {label}",
        )
    _add_health_subscription(
        store,
        workspace=workspace,
        user=member,
        label="failure-member-only",
        status="degraded",
        failure_at=within_window,
        issue_code="MemberError",
        issue_message="member private diagnostic",
    )

    runtime = RuntimeStatusService(store)
    workspace_summary = runtime.summary(workspace_id=workspace["id"], now=now)
    owner_summary = runtime.summary(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        now=now,
    )

    assert workspace_summary["source_health_failure_window_hours"] == 24
    assert workspace_summary["recent_source_failure_code_counts"] == {
        "MemberError": 1,
        "TimeoutError": 2,
    }
    assert owner_summary["recent_source_failure_code_counts"] == {"TimeoutError": 2}
    assert "private message" not in json.dumps(
        {
            "source_health_counts": workspace_summary["source_health_counts"],
            "recent_source_failure_code_counts": workspace_summary[
                "recent_source_failure_code_counts"
            ],
            "source_health_failure_window_hours": workspace_summary[
                "source_health_failure_window_hours"
            ],
        }
    )


def test_runtime_normalizes_unsafe_failure_code_keys_without_changing_user_projection(
    tmp_path,
    monkeypatch,
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    now = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
    subscriptions = []
    unsafe_codes = (
        "Alice api_key=sk-super-secret-value",
        "sk-abcdefghijklmno",
        "claim_token=private-claim",
        "X" * 65,
    )
    for index, code in enumerate(unsafe_codes):
        subscriptions.append(
            _add_health_subscription(
                store,
                workspace=workspace,
                user=owner,
                label=f"unsafe-code-{index}",
                status="failing",
                failure_at=(now - timedelta(minutes=index + 1)).isoformat(),
                issue_code=code,
                issue_message="private issue detail",
            )
        )
    _add_health_subscription(
        store,
        workspace=workspace,
        user=owner,
        label="safe-code",
        status="degraded",
        failure_at=(now - timedelta(minutes=10)).isoformat(),
        issue_code="TimeoutError",
        issue_message="safe grouped issue",
    )

    runtime = RuntimeStatusService(store).summary(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        now=now,
    )
    projection = SourceHealthService(store).user_projection(
        workspace_id=workspace["id"],
        user_id=owner["id"],
    )

    assert runtime["recent_source_failure_code_counts"] == {
        "Other": 4,
        "TimeoutError": 1,
    }
    projected_by_subscription = {
        item["subscription_id"]: item for item in projection["items"]
    }
    assert projected_by_subscription[subscriptions[0]["id"]]["last_issue"]["code"] == (
        unsafe_codes[0]
    )


def test_ops_runtime_exposes_only_source_health_aggregates_and_remains_admin_only(
    tmp_path,
    monkeypatch,
):
    client, store, workspace, owner = _client(tmp_path, monkeypatch)
    users = {}
    for username, role in (("admin", "admin"), ("member", "member"), ("viewer", "viewer")):
        users[username] = store.create_user(
            workspace_id=workspace["id"],
            username=username,
            password=f"{username}-password",
            role=role,
        )
    failure_at = datetime.now(timezone.utc).isoformat()
    _add_health_subscription(
        store,
        workspace=workspace,
        user=owner,
        label="ops-owner-secret-name",
        status="failing",
        failure_at=failure_at,
        issue_code="SafeGroupedCode",
        issue_message="ops secret issue message",
    )
    _add_health_subscription(
        store,
        workspace=workspace,
        user=users["member"],
        label="ops-member-unknown",
        status=None,
    )

    for username in ("owner", "admin"):
        password = "secret-password" if username == "owner" else "admin-password"
        _login(client, username, password)
        response = client.get("/api/ops/runtime")
        assert response.status_code == 200
        data = response.json()["data"]
        aggregates = {
            "source_health_counts": data["source_health_counts"],
            "recent_source_failure_code_counts": data[
                "recent_source_failure_code_counts"
            ],
            "source_health_failure_window_hours": data[
                "source_health_failure_window_hours"
            ],
        }
        assert aggregates == {
            "source_health_counts": {
                "total": 2,
                "unknown": 1,
                "healthy": 0,
                "degraded": 0,
                "failing": 1,
            },
            "recent_source_failure_code_counts": {"SafeGroupedCode": 1},
            "source_health_failure_window_hours": 24,
        }
        serialized = json.dumps(aggregates)
        for forbidden in (
            owner["id"],
            users["member"]["id"],
            "ops-owner-secret-name",
            "ops-member-unknown",
            "ops secret issue message",
            "subscription_id",
            "source_id",
            "user_id",
        ):
            assert forbidden not in serialized
        client.post("/api/auth/logout")

    for username in ("member", "viewer"):
        _login(client, username, f"{username}-password")
        forbidden = client.get("/api/ops/runtime")
        assert forbidden.status_code == 403
        assert forbidden.json()["error"]["code"] == "forbidden"
        client.post("/api/auth/logout")
