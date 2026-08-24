from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from scripts.remote_mcp_read_canary import (
    ALL_REMOTE_TOOLS,
    SAFE_READ_TOOLS,
    CanaryFailure,
    expect_unauthorized,
    verify_canary,
)
from src.api.server import create_app
from src.services.bilibili_user_search import BilibiliUserSearchService
from src.services.job_queue import JobQueue
from src.services.user_feed_store import UserFeedStore


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("HORIZON_REMOTE_MCP_ENABLED", "true")
    monkeypatch.setenv(
        "HORIZON_REMOTE_MCP_PUBLIC_URL", "http://127.0.0.1:8080/mcp"
    )
    monkeypatch.setenv(
        "HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED", "false"
    )
    monkeypatch.setattr(
        BilibiliUserSearchService,
        "search",
        lambda _self, *, query, limit=5: {
            "schema_version": 1,
            "query": query,
            "availability": "available",
            "match_status": "exact",
            "resolved_user": {
                "uid": "39627524",
                "name": "食贫道",
                "profile_url": "https://space.bilibili.com/39627524",
            },
            "candidates": [],
            "returned": 0,
            "truncated": False,
            "data_trust": "untrusted_public_metadata",
            "error_code": None,
        },
    )
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    static_dir.joinpath("index.html").write_text(
        "<!doctype html>", encoding="utf-8"
    )
    return create_app(data_dir=tmp_path / "data", static_dir=static_dir)


def _seed_canary(app):
    store = app.state.service_store
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    other = store.create_user(
        workspace_id=workspace["id"],
        username="secondary",
        password="secondary-password",
        role="viewer",
    )
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Private canary source",
        source_key="rss:private-canary",
        config={"url": "https://example.com/private-canary.xml"},
    )
    subscription = store.create_subscription(
        user_id=owner["id"], source_id=source_id
    )
    article_id = "private-canary-article"
    generated_at = datetime.now(timezone.utc).isoformat()
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=None,
        payload={
            "schema_version": 2,
            "generated_at": generated_at,
            "items": [
                {
                    "id": article_id,
                    "title": "Private canary title",
                    "source": "Private canary source",
                    "source_type": "rss",
                    "url": "https://example.com/private-canary-article",
                    "published_at": generated_at,
                    "summary": "Private canary body",
                    "channel": "AI",
                    "topics": ["MCP"],
                }
            ],
        },
    )
    job = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        job_type="source_test",
    )
    primary_connection, primary_token = store.create_agent_delegation(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        name="Primary read canary",
        access="read",
    )
    _secondary_connection, secondary_token = store.create_agent_delegation(
        workspace_id=workspace["id"],
        user_id=other["id"],
        name="Secondary read canary",
        access="read",
    )
    return {
        "owner": owner,
        "primary_connection": primary_connection,
        "primary_token": primary_token,
        "secondary_token": secondary_token,
        "private_values": (
            article_id,
            job["id"],
            subscription["id"],
            "Private canary title",
        ),
    }


@pytest.mark.anyio
async def test_verify_canary_calls_safe_tools_checks_isolation_and_leaks_nothing(
    tmp_path, monkeypatch
):
    app = _app(tmp_path, monkeypatch)
    seeded = _seed_canary(app)
    transport = httpx.ASGITransport(app=app)
    before_proposals = app.state.service_store.connect().execute(
        "SELECT COUNT(*) FROM agent_change_proposals"
    ).fetchone()[0]

    async with app.router.lifespan_context(app):
        result = await verify_canary(
            url="http://127.0.0.1:8080/mcp",
            primary_token=seeded["primary_token"],
            secondary_token=seeded["secondary_token"],
            transport=transport,
        )

    assert result["ok"] is True
    assert result["mode"] == "verify"
    assert result["tool_count"] == 20
    assert result["registered_tools"] == list(ALL_REMOTE_TOOLS)
    assert result["read_tools"] == {name: "ok" for name in SAFE_READ_TOOLS}
    assert result["isolation_checks"] == 3
    assert result["write_guard"] == "subscription_writes_disabled"
    assert result["latency_ms"]["sample_count"] == 11
    assert result["bilibili_lookup_latency_ms"]["sample_count"] == 1
    assert result["source_resolution_latency_ms"]["sample_count"] == 1
    after_proposals = app.state.service_store.connect().execute(
        "SELECT COUNT(*) FROM agent_change_proposals"
    ).fetchone()[0]
    assert after_proposals == before_proposals

    serialized = json.dumps(result, ensure_ascii=False)
    for private in (
        seeded["primary_token"],
        seeded["secondary_token"],
        *seeded["private_values"],
    ):
        assert private not in serialized


@pytest.mark.anyio
async def test_verify_canary_fails_closed_when_required_objects_are_missing(
    tmp_path, monkeypatch
):
    app = _app(tmp_path, monkeypatch)
    store = app.state.service_store
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    other = store.create_user(
        workspace_id=workspace["id"],
        username="empty-secondary",
        password="secondary-password",
        role="viewer",
    )
    _primary, primary_token = store.create_agent_delegation(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        name="Empty primary",
    )
    _secondary, secondary_token = store.create_agent_delegation(
        workspace_id=workspace["id"],
        user_id=other["id"],
        name="Empty secondary",
    )
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        with pytest.raises(CanaryFailure) as error:
            await verify_canary(
                url="http://127.0.0.1:8080/mcp",
                primary_token=primary_token,
                secondary_token=secondary_token,
                transport=transport,
            )

    assert error.value.code == "precondition_missing"
    assert primary_token not in str(error.value)
    assert secondary_token not in str(error.value)


@pytest.mark.anyio
async def test_expect_unauthorized_accepts_only_revoked_token(
    tmp_path, monkeypatch
):
    app = _app(tmp_path, monkeypatch)
    seeded = _seed_canary(app)
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        with pytest.raises(CanaryFailure) as active:
            await expect_unauthorized(
                url="http://127.0.0.1:8080/mcp",
                token=seeded["primary_token"],
                transport=transport,
            )
        assert active.value.code == "token_still_authorized"

        app.state.service_store.revoke_agent_delegation(
            seeded["owner"]["id"], seeded["primary_connection"]["id"]
        )
        result = await expect_unauthorized(
            url="http://127.0.0.1:8080/mcp",
            token=seeded["primary_token"],
            transport=transport,
        )

    assert result == {"ok": True, "mode": "expect-unauthorized", "status": 401}
    assert seeded["primary_token"] not in json.dumps(result)
