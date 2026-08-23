import json
import sqlite3
from datetime import datetime, timezone

import anyio
import httpx
import pytest
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from src.api.server import create_app
from src.mcp.remote_server import AgentDelegationTokenVerifier, DelegationRateLimiter
from src.services.bilibili_user_search import BilibiliUserSearchService
from src.services.job_queue import JobQueue
from src.services.user_feed_store import UserFeedStore


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _app(tmp_path, monkeypatch, *, enabled: bool = True):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv(
        "HORIZON_REMOTE_MCP_ENABLED", "true" if enabled else "false"
    )
    monkeypatch.setenv("HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED", "false")
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
    if enabled:
        monkeypatch.setenv(
            "HORIZON_REMOTE_MCP_PUBLIC_URL", "http://127.0.0.1:8080/mcp"
        )
    else:
        monkeypatch.delenv("HORIZON_REMOTE_MCP_PUBLIC_URL", raising=False)
    static_dir = tmp_path / "static"
    static_dir.mkdir(parents=True)
    static_dir.joinpath("assets").mkdir()
    static_dir.joinpath("index.html").write_text("<!doctype html>", encoding="utf-8")
    return create_app(data_dir=tmp_path / "data", static_dir=static_dir)


def _token(app):
    store = app.state.service_store
    user = store.get_user_by_username("owner")
    connection, token = store.create_agent_delegation(
        workspace_id=user["workspace_id"], user_id=user["id"], name="Test OpenClaw"
    )
    return user, connection, token


def _seed_feed(app, user):
    generated_at = datetime.now(timezone.utc).isoformat()
    UserFeedStore(app.state.service_store).save_snapshot(
        workspace_id=user["workspace_id"],
        user_id=user["id"],
        job_id=None,
        payload={
            "schema_version": 2,
            "generated_at": generated_at,
            "items": [
                {
                    "id": "article-1",
                    "title": "Remote MCP",
                    "source": "Example",
                    "source_type": "rss",
                    "url": "https://example.com/article-1",
                    "published_at": generated_at,
                    "excerpt": "Read-only feed item",
                }
            ],
        },
    )
    return JobQueue(app.state.service_store).create_job(
        workspace_id=user["workspace_id"],
        user_id=user["id"],
        job_type="source_test",
    )


def _business_dump(app):
    return "\n".join(
        statement
        for statement in app.state.service_store.connect().iterdump()
        if "agent_delegations" not in statement
    )


def _initialize_payload():
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "1"},
        },
    }

def test_support_exports_http_fixture_and_app_factory() -> None:
    assert callable(anyio_backend)
    assert callable(_app)


__all__ = [
    name
    for name in globals()
    if not name.startswith("__") and name != "test_support_exports_http_fixture_and_app_factory"
]
