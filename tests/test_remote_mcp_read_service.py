import json
from datetime import datetime, timedelta, timezone

import pytest

from src.mcp.remote_service import RemoteMCPNotFound, RemoteMCPReadService
from src.services.job_queue import JobQueue
from src.services.user_feed_store import UserFeedStore
from src.services.user_item_state import UserItemStateStore
from src.storage.service_store import ServiceStore


def _item(
    article_id: str,
    title: str,
    *,
    body: str = "body",
    published_at: str | None = None,
    source_id: str = "source-internal",
) -> dict:
    resolved_published_at = published_at or datetime.now(timezone.utc).isoformat()
    return {
        "id": article_id,
        "title": title,
        "source": "Example Feed",
        "source_id": source_id,
        "source_ids": [source_id],
        "source_type": "rss",
        "url": f"https://example.com/{article_id}",
        "published_at": resolved_published_at,
        "channel": "AI",
        "topics": ["Agent"],
        "metadata": {"secret": "must-not-leak"},
        "reason": "legacy-reason-must-not-leak",
        "presentation": {
            "version": 1,
            "source": {
                "id": source_id,
                "catalog_type": "rss",
                "platform": "rss",
                "name": "Example Feed",
                "avatar_url": "/api/media/source-avatar",
            },
            "author": {"name": "Author", "kind": "person"},
            "timing": {
                "published_at": resolved_published_at,
                "fetched_at": resolved_published_at,
            },
            "links": {
                "canonical_url": f"https://example.com/{article_id}",
                "source_url": f"https://example.com/{article_id}",
            },
            "content": {
                "title": title,
                "title_origin": "native",
                "excerpt": "A bounded excerpt",
                "content_kind": "feed_summary",
                "excerpt_truncated": False,
                "body_text": body,
            },
            "taxonomy": {
                "channel": "AI",
                "configured_topics": ["Agent"],
                "inferred_topics": [],
                "topics": ["Agent"],
                "entities": [],
            },
            "engagement": {
                "native_score": None,
                "likes": None,
                "comments": None,
                "reposts": None,
                "shares": None,
                "upvote_ratio": None,
            },
            "analysis": {
                "status": "fallback",
                "score": 7,
                "signal_strength": "medium",
                "signal_type": "news",
                "summary_zh": "摘要",
                "reason": "private analysis reason",
            },
            "media": {"images": [{"url": "/api/media/secret"}]},
        },
    }


def _context(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    member = store.create_user(
        workspace_id=workspace["id"],
        username="member",
        password="member-password",
        role="admin",
    )
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Example Feed",
        default_channel="AI",
        default_topics=["Agent"],
        config={"url": "https://example.com/feed", "api_key": "secret"},
        secret_env="RSS_SECRET",
    )
    subscription = store.create_subscription(
        user_id=owner["id"],
        source_id=source_id,
        override_topics=["MCP"],
        personal_tags=["private-tag"],
        analysis_mode="personal_only",
        priority=80,
    )
    store.create_subscription(user_id=member["id"], source_id=source_id)

    feed = UserFeedStore(store)
    generated_at = datetime.now(timezone.utc)
    historical_at = (generated_at - timedelta(days=10)).isoformat()
    feed.save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=None,
        payload={
            "schema_version": 2,
            "generated_at": (generated_at - timedelta(minutes=1)).isoformat(),
            "items": [
                _item(
                    "article-c",
                    "Historical",
                    body="historical body",
                    published_at=historical_at,
                    source_id=source_id,
                ),
                _item("article-a", "Latest", body="X" * 100, source_id=source_id),
            ],
        },
    )
    feed.save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=None,
        payload={
            "schema_version": 2,
            "generated_at": generated_at.isoformat(),
            "items": [
                _item("article-a", "Latest", body="X" * 100, source_id=source_id),
                _item("article-b", "Dismissed", source_id=source_id),
            ],
        },
    )
    feed.save_snapshot(
        workspace_id=workspace["id"],
        user_id=member["id"],
        job_id=None,
        payload={
            "schema_version": 2,
            "generated_at": generated_at.isoformat(),
            "items": [
                _item("member-only", "Member private item", source_id=source_id)
            ],
        },
    )
    states = UserItemStateStore(store)
    states.update_state(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_id="article-a",
        is_read=True,
        is_saved=True,
    )
    states.update_state(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_id="article-b",
        dismissed=True,
    )
    states.update_state(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_id="article-c",
        is_later=True,
    )

    owner_job = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        job_type="source_fetch",
        payload={"authorization": "Bearer secret", "article_id": "private"},
    )
    member_job = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=member["id"],
        job_type="source_test",
        payload={"secret": "member"},
    )
    store.connect().execute(
        """
        UPDATE fetch_jobs
        SET status = 'succeeded', worker_id = 'worker-secret',
            claim_token = 'claim-secret', result_json = ?,
            error_code = 'upstream_failed', error_message = 'Bearer secret in upstream URL',
            finished_at = updated_at
        WHERE id = ?
        """,
        (
            json.dumps(
                {
                    "fetched_count": 4,
                    "snapshot_id": "snap-safe",
                    "raw_response": "secret response",
                }
            ),
            owner_job["id"],
        ),
    )
    store.connect().commit()
    return store, workspace, owner, member, owner_job, member_job


def _all_keys(value):
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _all_keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _all_keys(item)}
    return set()


def test_remote_mcp_feed_collections_are_paginated_safe_and_match_ui_semantics(
    tmp_path, monkeypatch
):
    store, workspace, owner, *_ = _context(tmp_path, monkeypatch)
    service = RemoteMCPReadService(store)
    scope = {"workspace_id": workspace["id"], "user_id": owner["id"]}

    latest = service.get_my_feed(**scope, collection="latest", limit=20, offset=0)
    history = service.get_my_feed(**scope, collection="history", limit=20, offset=0)
    saved = service.get_my_feed(**scope, collection="saved", limit=20, offset=0)
    later = service.get_my_feed(**scope, collection="later", limit=20, offset=0)

    assert [item["article_id"] for item in latest["items"]] == ["article-a"]
    assert [item["article_id"] for item in history["items"]] == ["article-c"]
    assert [item["article_id"] for item in saved["items"]] == ["article-a"]
    assert [item["article_id"] for item in later["items"]] == ["article-c"]
    assert latest["page"] == {
        "limit": 20,
        "offset": 0,
        "returned": 1,
        "total": 1,
        "has_more": False,
    }
    assert "metadata" not in _all_keys(latest)
    assert "media" not in _all_keys(latest)
    assert "avatar_url" not in _all_keys(latest)
    assert "reason" not in _all_keys(latest)
    assert "body_text" not in _all_keys(latest)


def test_remote_mcp_detail_is_self_scoped_and_body_is_bounded(tmp_path, monkeypatch):
    store, workspace, owner, member, *_ = _context(tmp_path, monkeypatch)
    service = RemoteMCPReadService(store)

    detail = service.get_item(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_id="article-a",
        max_body_chars=20,
    )

    assert detail["article_id"] == "article-a"
    assert detail["presentation"]["version"] == 2
    assert detail["presentation"]["content"]["body_text"] == "X" * 20
    assert detail["presentation"]["content"]["body_truncated"] is True
    assert detail["presentation"]["content"] | {
        "body_offset": 0,
        "body_end": 20,
        "body_total_chars": 100,
        "body_has_more": True,
        "next_body_offset": 20,
    } == detail["presentation"]["content"]
    assert "media" not in detail["presentation"]
    with pytest.raises(RemoteMCPNotFound):
        service.get_item(
            workspace_id=workspace["id"],
            user_id=member["id"],
            article_id="article-a",
        )
    with pytest.raises(RemoteMCPNotFound):
        service.get_item(
            workspace_id=workspace["id"],
            user_id=owner["id"],
            article_id="missing",
        )


def test_remote_mcp_detail_pages_the_full_stored_body(tmp_path, monkeypatch):
    store, workspace, owner, *_ = _context(tmp_path, monkeypatch)
    service = RemoteMCPReadService(store)
    scope = {"workspace_id": workspace["id"], "user_id": owner["id"]}
    long_item = _item("article-long", "Long body", body="Y" * 20_000)
    long_item["presentation"]["content"]["body_truncated"] = True
    long_item["presentation"]["content"]["body_completeness"] = "captured"
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=None,
        payload={
            "schema_version": 2,
            "generated_at": "2026-07-17T00:00:00+00:00",
            "items": [long_item],
        },
    )

    first = service.get_item(
        **scope, article_id="article-long", body_offset=0, max_body_chars=8000
    )
    second = service.get_item(
        **scope, article_id="article-long", body_offset=8000, max_body_chars=8000
    )
    last = service.get_item(
        **scope, article_id="article-long", body_offset=16000, max_body_chars=8000
    )

    chunks = [
        page["presentation"]["content"]["body_text"]
        for page in (first, second, last)
    ]
    assert "".join(chunks) == "Y" * 20_000
    assert first["presentation"]["content"]["next_body_offset"] == 8000
    assert second["presentation"]["content"]["next_body_offset"] == 16000
    assert last["presentation"]["content"] | {
        "body_offset": 16000,
        "body_end": 20_000,
        "body_total_chars": 20_000,
        "body_has_more": False,
        "next_body_offset": None,
    } == last["presentation"]["content"]
    assert last["presentation"]["content"]["body_truncated"] is True


def test_remote_mcp_final_chunk_distinguishes_complete_storage_from_capture_truncation(
    tmp_path, monkeypatch
):
    store, workspace, owner, *_ = _context(tmp_path, monkeypatch)
    service = RemoteMCPReadService(store)
    scope = {"workspace_id": workspace["id"], "user_id": owner["id"]}
    complete = _item("article-complete", "Complete", body="Z" * 12_000)
    complete["presentation"]["content"]["body_truncated"] = False
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=None,
        payload={
            "schema_version": 2,
            "generated_at": "2026-07-17T00:00:00+00:00",
            "items": [complete],
        },
    )

    first = service.get_item(
        **scope, article_id="article-complete", body_offset=0, max_body_chars=8000
    )
    final = service.get_item(
        **scope,
        article_id="article-complete",
        body_offset=8000,
        max_body_chars=8000,
    )

    assert first["presentation"]["content"]["body_truncated"] is True
    assert first["presentation"]["content"]["body_has_more"] is True
    assert final["presentation"]["content"]["body_has_more"] is False
    assert final["presentation"]["content"]["body_truncated"] is False


@pytest.mark.parametrize("body_offset", [-1, 20_001, True])
def test_remote_mcp_detail_rejects_invalid_body_offsets(
    tmp_path, monkeypatch, body_offset
):
    store, workspace, owner, *_ = _context(tmp_path, monkeypatch)
    service = RemoteMCPReadService(store)

    with pytest.raises(ValueError, match="body_offset"):
        service.get_item(
            workspace_id=workspace["id"],
            user_id=owner["id"],
            article_id="article-a",
            body_offset=body_offset,
        )


def test_remote_mcp_subscriptions_health_and_jobs_are_safe_and_self_scoped(
    tmp_path, monkeypatch
):
    store, workspace, owner, member, owner_job, member_job = _context(
        tmp_path, monkeypatch
    )
    service = RemoteMCPReadService(store)
    scope = {"workspace_id": workspace["id"], "user_id": owner["id"]}

    subscriptions = service.list_subscriptions(**scope)
    health = service.source_health(**scope)
    jobs = service.list_jobs(**scope, limit=20)
    job = service.get_job(**scope, job_id=owner_job["id"])

    assert subscriptions["items"][0]["topics"] == ["MCP"]
    assert subscriptions["items"][0]["analysis_mode"] == "personal_only"
    assert not {"personal_tags", "config", "secret_env"} & _all_keys(subscriptions)
    assert health["scope"] == "user"
    assert [item["id"] for item in jobs["items"]] == [owner_job["id"]]
    assert job["result_summary"] == {
        "fetched_count": 4,
        "snapshot_id": "snap-safe",
    }
    assert not {
        "workspace_id",
        "user_id",
        "worker_id",
        "claim_token",
        "locked_until",
        "payload",
        "result",
        "raw_response",
        "message",
    } & _all_keys({"jobs": jobs, "job": job})
    assert "Bearer secret" not in json.dumps({"jobs": jobs, "job": job})
    with pytest.raises(RemoteMCPNotFound):
        service.get_job(**scope, job_id=member_job["id"])


def test_remote_mcp_job_reads_stay_narrow_when_diagnostics_need_raw_errors(
    tmp_path, monkeypatch
):
    store, workspace, owner, _member, owner_job, _member_job = _context(
        tmp_path, monkeypatch
    )
    service = RemoteMCPReadService(store)
    scope = {"workspace_id": workspace["id"], "user_id": owner["id"]}

    listed = service.list_jobs(**scope)["items"][0]
    fetched = service.get_job(**scope, job_id=owner_job["id"])

    expected_keys = {
        "id",
        "job_type",
        "status",
        "source_id",
        "subscription_id",
        "priority",
        "attempts",
        "max_attempts",
        "next_run_at",
        "created_at",
        "started_at",
        "finished_at",
        "cancelled_at",
        "updated_at",
        "error",
        "result_summary",
    }
    assert set(listed) == expected_keys
    assert set(fetched) == expected_keys
    assert listed["error"] == {"code": "upstream_failed"}
    assert fetched["error"] == {"code": "upstream_failed"}
    assert "message" not in _all_keys({"listed": listed, "fetched": fetched})
    assert "Bearer secret" not in repr({"listed": listed, "fetched": fetched})


def test_all_remote_mcp_read_methods_leave_business_tables_unchanged(
    tmp_path, monkeypatch
):
    store, workspace, owner, *_rest = _context(tmp_path, monkeypatch)
    service = RemoteMCPReadService(store)
    scope = {"workspace_id": workspace["id"], "user_id": owner["id"]}
    before = "\n".join(store.connect().iterdump())

    for collection in ("latest", "history", "saved", "later"):
        service.get_my_feed(**scope, collection=collection)
    service.get_item(**scope, article_id="article-a")
    service.list_subscriptions(**scope)
    service.source_health(**scope)
    service.list_jobs(**scope)
    service.get_job(**scope, job_id=_rest[1]["id"])

    assert "\n".join(store.connect().iterdump()) == before
