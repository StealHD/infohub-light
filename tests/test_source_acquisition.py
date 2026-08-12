from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.models import ContentItem, SourceType
from src.orchestrator import HorizonOrchestrator
from src.services.apify_actor_ops import ApifyActorOpsService
from src.services.apify_actor_route import ApifyActorRoutedList
from src.services.apify_key_pool import ApifyKeyPoolService
from src.services.source_acquisition import (
    AcquisitionBusyError,
    AcquisitionLeaseLostError,
    SourceAcquisitionCoordinator,
)
from src.storage.service_store import ServiceStore


def _store(tmp_path, monkeypatch, request=None):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    if request is not None:
        request.addfinalizer(store.close)
    return store, store.get_default_workspace(), store.get_user_by_username("owner")


def test_source_acquisition_schema_is_additive(tmp_path, monkeypatch):
    store, _workspace, _owner = _store(tmp_path, monkeypatch)

    tables = {
        row["name"]
        for row in store.connect().execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    state_columns = {
        row["name"]
        for row in store.connect().execute(
            "PRAGMA table_info(source_acquisition_states)"
        ).fetchall()
    }
    snapshot_columns = {
        row["name"]
        for row in store.connect().execute(
            "PRAGMA table_info(source_content_snapshots)"
        ).fetchall()
    }

    assert {
        "source_acquisition_states",
        "source_content_snapshots",
        "source_content_items",
    }.issubset(tables)
    assert {
        "acquisition_key",
        "workspace_id",
        "source_id",
        "isolation_scope",
        "config_fingerprint",
        "owner_job_id",
        "claim_token",
        "locked_until",
        "retry_after",
        "last_error_code",
        "updated_at",
    }.issubset(state_columns)
    assert {
        "id",
        "acquisition_key",
        "workspace_id",
        "source_id",
        "config_fingerprint",
        "isolation_scope",
        "window_hours",
        "generated_at",
        "fresh_until",
        "item_count",
        "producer_job_id",
    }.issubset(snapshot_columns)


def _catalog_source(
    store: ServiceStore,
    workspace: dict,
    owner: dict,
    *,
    scope: str = "public",
    secret_env: str | None = None,
) -> str:
    return store.create_source(
        workspace_id=workspace["id"],
        scope=scope,
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Shared RSS",
        config={"name": "Shared RSS", "url": "https://example.com/feed.xml"},
        source_key="rss:https://example.com/feed.xml",
        secret_env=secret_env,
    )


def _projection(
    source_id: str,
    subscription_id: str,
    *,
    channel: str,
    personal_tag: str,
    analysis_mode: str = "personal_only",
):
    return SimpleNamespace(
        source_id=source_id,
        subscription_id=subscription_id,
        source_key="rss:https://example.com/feed.xml",
        source_display_name="Shared RSS",
        catalog_source_type="rss",
        source_priority=7,
        analysis_mode=analysis_mode,
        channel=channel,
        category=channel,
        topics=[f"{channel}-topic"],
        tags=[f"{channel}-topic"],
        personal_tags=[personal_tag],
    )


def _content_item(*, suffix: str = "one") -> ContentItem:
    return ContentItem(
        id=f"rss:item:{suffix}",
        source_type=SourceType.RSS,
        title=f"Item {suffix}",
        url=f"https://example.com/articles/{suffix}?lang=zh",
        published_at=datetime.now(timezone.utc),
        metadata={
            "feed_name": "Shared RSS",
            "source_id": "must-be-reprojected",
            "subscription_id": "must-be-reprojected",
            "channel": "must-be-reprojected",
            "topics": ["must-be-reprojected"],
            "personal_tags": ["must-not-leak"],
        },
    )


def _youtube_fallback_source(
    store: ServiceStore,
    workspace: dict,
    owner: dict,
) -> tuple[str, str, SimpleNamespace]:
    route = store.connect().execute(
        """
        SELECT route_id FROM apify_actor_route_profiles
        WHERE workspace_id = ? AND route_key = 'youtube/channel/items'
        """,
        (workspace["id"],),
    ).fetchone()
    assert route is not None
    canonical_url = (
        "https://www.youtube.com/feeds/videos.xml?channel_id=UC-fence-test"
    )
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="YouTube fallback fence",
        config={"name": "YouTube fallback fence", "url": canonical_url},
        source_key=f"rss:{canonical_url}",
    )
    subscription = store.create_subscription(
        user_id=owner["id"],
        source_id=source_id,
    )
    ApifyActorOpsService(store, workspace_id=workspace["id"]).bind_source(
        source_id=source_id,
        route_id=str(route["route_id"]),
        target_fingerprint="a" * 64,
        mode="fallback",
    )
    projection = _projection(
        source_id,
        subscription["id"],
        channel="youtube",
        personal_tag="youtube-only",
        analysis_mode="full",
    )
    return source_id, str(route["route_id"]), projection


def _publication_orchestrator(
    coordinator: SourceAcquisitionCoordinator,
) -> HorizonOrchestrator:
    orchestrator = object.__new__(HorizonOrchestrator)
    orchestrator._service_acquisition_coordinator = coordinator
    orchestrator._service_apify_actor_ops = None
    orchestrator._service_apify_actor_ops_snapshots = []
    return orchestrator


def _bump_youtube_actor_context(
    store: ServiceStore,
    workspace_id: str,
    source_id: str,
    route_id: str,
    changed_context: str,
) -> None:
    conn = store.connect()
    if changed_context == "route":
        cursor = conn.execute(
            """
            UPDATE apify_actor_route_profiles
            SET generation = generation + 1
            WHERE workspace_id = ? AND route_id = ?
            """,
            (workspace_id, route_id),
        )
    elif changed_context == "binding":
        cursor = conn.execute(
            """
            UPDATE apify_source_route_bindings
            SET generation = generation + 1
            WHERE workspace_id = ? AND source_id = ?
            """,
            (workspace_id, source_id),
        )
    else:
        cursor = conn.execute(
            """
            UPDATE apify_key_pool_state
            SET generation = generation + 1
            WHERE workspace_id = ?
            """,
            (workspace_id,),
        )
    assert cursor.rowcount == 1
    conn.commit()


@pytest.mark.parametrize("changed_context", ("route", "binding", "key"))
def test_youtube_fallback_cache_hit_is_fenced_from_changed_actor_context(
    tmp_path,
    monkeypatch,
    changed_context,
):
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    store, workspace, owner = _store(tmp_path, monkeypatch)
    source_id, route_id, source = _youtube_fallback_source(
        store,
        workspace,
        owner,
    )
    fallback_item = _content_item(suffix=f"youtube-{changed_context}")
    fallback_item.metadata["acquisition_origin"] = "apify_fallback"

    async def fetch_fallback():
        return [fallback_item]

    producer = SourceAcquisitionCoordinator(
        store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=f"job-youtube-producer-{changed_context}",
    )
    asyncio.run(
        producer.acquire(
            source=source,
            provider="rss",
            window_hours=24,
            fetch=fetch_fallback,
        )
    )

    async def must_use_cache():
        raise AssertionError("fresh YouTube fallback snapshot was not reused")

    consumer = SourceAcquisitionCoordinator(
        store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=f"job-youtube-consumer-{changed_context}",
    )
    cached = asyncio.run(
        consumer.acquire(
            source=source,
            provider="rss",
            window_hours=24,
            fetch=must_use_cache,
        )
    )
    assert [item.id for item in cached] == [fallback_item.id]
    assert consumer.origin_for(source_id) == "cache"
    consumer.assert_publication_current()

    _bump_youtube_actor_context(
        store,
        workspace["id"],
        source_id,
        route_id,
        changed_context,
    )

    conn = store.connect()
    conn.execute("BEGIN IMMEDIATE")
    try:
        assert conn.in_transaction is True
        with pytest.raises(AcquisitionLeaseLostError):
            _publication_orchestrator(
                consumer
            ).assert_service_apify_actor_ops_publishable()
        assert conn.in_transaction is True
    finally:
        conn.rollback()


@pytest.mark.parametrize("changed_context", ("route", "binding", "key"))
def test_youtube_native_cache_hit_ignores_changed_actor_context(
    tmp_path,
    monkeypatch,
    changed_context,
):
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    store, workspace, owner = _store(tmp_path, monkeypatch)
    source_id, route_id, source = _youtube_fallback_source(
        store,
        workspace,
        owner,
    )
    native_item = _content_item(suffix="youtube-native")

    async def fetch_native():
        return [native_item]

    producer = SourceAcquisitionCoordinator(
        store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=f"job-youtube-native-producer-{changed_context}",
    )
    asyncio.run(
        producer.acquire(
            source=source,
            provider="rss",
            window_hours=24,
            fetch=fetch_native,
        )
    )

    async def must_use_cache():
        raise AssertionError("fresh YouTube native snapshot was not reused")

    consumer = SourceAcquisitionCoordinator(
        store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=f"job-youtube-native-consumer-{changed_context}",
    )
    cached = asyncio.run(
        consumer.acquire(
            source=source,
            provider="rss",
            window_hours=24,
            fetch=must_use_cache,
        )
    )
    assert [item.id for item in cached] == [native_item.id]
    assert consumer.origin_for(source_id) == "cache"

    _bump_youtube_actor_context(
        store,
        workspace["id"],
        source_id,
        route_id,
        changed_context,
    )

    conn = store.connect()
    conn.execute("BEGIN IMMEDIATE")
    try:
        _publication_orchestrator(
            consumer
        ).assert_service_apify_actor_ops_publishable()
        assert conn.in_transaction is True
    finally:
        conn.rollback()


@pytest.mark.parametrize("changed_context", ("route", "binding", "key"))
def test_youtube_native_upstream_ignores_actor_context_change_during_fetch(
    tmp_path,
    monkeypatch,
    changed_context,
):
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    store, workspace, owner = _store(tmp_path, monkeypatch)
    source_id, route_id, source = _youtube_fallback_source(
        store,
        workspace,
        owner,
    )
    native_item = _content_item(suffix=f"youtube-native-{changed_context}")

    async def fetch_native_during_actor_change():
        _bump_youtube_actor_context(
            store,
            workspace["id"],
            source_id,
            route_id,
            changed_context,
        )
        return [native_item]

    coordinator = SourceAcquisitionCoordinator(
        store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=f"job-youtube-native-race-{changed_context}",
    )
    items = asyncio.run(
        coordinator.acquire(
            source=source,
            provider="rss",
            window_hours=24,
            fetch=fetch_native_during_actor_change,
        )
    )

    assert [item.id for item in items] == [native_item.id]
    _publication_orchestrator(
        coordinator
    ).assert_service_apify_actor_ops_publishable()


def test_apify_pool_generation_is_in_fingerprint_and_blocks_stale_publication(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    store, workspace, owner = _store(tmp_path, monkeypatch)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="apify_social",
        display_name="Shared X",
        config={
            "platform": "x",
            "kind": "profile",
            "target": "OpenAI",
            "fetch_limit": 1,
        },
        source_key="apify:x:profile:openai",
    )
    subscription = store.create_subscription(
        user_id=owner["id"],
        source_id=source_id,
    )
    first_secret = store.create_secret_ref(
        workspace_id=workspace["id"],
        owner_user_id=owner["id"],
        name="Apify Primary",
        env_name="APIFY_POOL_PRIMARY_TEST",
        kind="apify",
        provider="apify",
    )
    second_secret = store.create_secret_ref(
        workspace_id=workspace["id"],
        owner_user_id=owner["id"],
        name="Apify Backup",
        env_name="APIFY_POOL_BACKUP_TEST",
        kind="apify",
        provider="apify",
    )
    pool = ApifyKeyPoolService(store)
    pool.append_secret(first_secret["id"])
    pool.append_secret(second_secret["id"])
    projection = SimpleNamespace(
        source_id=source_id,
        subscription_id=subscription["id"],
        source_key="apify:x:profile:openai",
        source_display_name="Shared X",
        catalog_source_type="apify_social",
        source_priority=0,
        analysis_mode="full",
        channel="AI",
        category="AI",
        topics=[],
        tags=[],
        personal_tags=[],
    )
    coordinator = SourceAcquisitionCoordinator(
        store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job-apify-old-generation",
    )
    old_context = coordinator._context(projection, window_hours=24)

    async def fetch_during_failover():
        pool.begin_drain(first_secret["id"])
        pool.complete_drain_and_failover(workspace["id"])
        return [_content_item(suffix="apify")]

    with pytest.raises(AcquisitionLeaseLostError):
        asyncio.run(
            coordinator.acquire(
                source=projection,
                provider="apify_social",
                window_hours=24,
                fetch=fetch_during_failover,
            )
        )

    new_context = coordinator._context(projection, window_hours=24)
    assert new_context.pool_generation != old_context.pool_generation
    assert new_context.config_fingerprint != old_context.config_fingerprint
    assert (
        store.connect().execute(
            "SELECT COUNT(*) FROM source_content_snapshots WHERE source_id = ?",
            (source_id,),
        ).fetchone()[0]
        == 0
    )


def test_apify_actor_route_generation_blocks_stale_publication(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    store, workspace, owner = _store(tmp_path, monkeypatch)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="apify_social",
        display_name="Shared X",
        config={
            "platform": "x",
            "kind": "profile",
            "target": "OpenAI",
            "fetch_limit": 1,
        },
        source_key="apify:x:profile:openai-route-generation",
    )
    subscription = store.create_subscription(
        user_id=owner["id"],
        source_id=source_id,
    )
    projection = SimpleNamespace(
        source_id=source_id,
        subscription_id=subscription["id"],
        source_key="apify:x:profile:openai-route-generation",
        source_display_name="Shared X",
        catalog_source_type="apify_social",
        source_priority=0,
        analysis_mode="full",
        channel="AI",
        category="AI",
        topics=[],
        tags=[],
        personal_tags=[],
    )
    coordinator = SourceAcquisitionCoordinator(
        store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job-apify-old-actor-route",
    )
    old_context = coordinator._context(projection, window_hours=24)

    async def fetch_during_actor_switch():
        store.connect().execute(
            """
            UPDATE apify_actor_routes
            SET generation = generation + 1,
                updated_at = '2026-07-29T00:00:00+00:00'
            WHERE workspace_id = ? AND route_key = 'x/profile'
            """,
            (workspace["id"],),
        )
        store.connect().commit()
        return [_content_item(suffix="apify-route")]

    with pytest.raises(AcquisitionLeaseLostError):
        asyncio.run(
            coordinator.acquire(
                source=projection,
                provider="apify_social",
                window_hours=24,
                fetch=fetch_during_actor_switch,
            )
        )

    new_context = coordinator._context(projection, window_hours=24)
    assert (
        new_context.actor_route_generation
        != old_context.actor_route_generation
    )
    assert new_context.config_fingerprint != old_context.config_fingerprint
    assert (
        store.connect().execute(
            "SELECT COUNT(*) FROM source_content_snapshots WHERE source_id = ?",
            (source_id,),
        ).fetchone()[0]
        == 0
    )


def test_apify_actor_route_generation_accepts_proven_backup_result(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    store, workspace, owner = _store(tmp_path, monkeypatch)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="apify_social",
        display_name="Shared X",
        config={
            "platform": "x",
            "kind": "profile",
            "target": "OpenAI",
            "fetch_limit": 1,
        },
        source_key="apify:x:profile:openai-proven-generation",
    )
    subscription = store.create_subscription(
        user_id=owner["id"],
        source_id=source_id,
    )
    projection = SimpleNamespace(
        source_id=source_id,
        subscription_id=subscription["id"],
        source_key="apify:x:profile:openai-proven-generation",
        source_display_name="Shared X",
        catalog_source_type="apify_social",
        source_priority=0,
        analysis_mode="full",
        channel="AI",
        category="AI",
        topics=[],
        tags=[],
        personal_tags=[],
    )
    coordinator = SourceAcquisitionCoordinator(
        store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job-apify-proven-route",
    )
    old_context = coordinator._context(projection, window_hours=24)

    async def fetch_from_backup():
        store.connect().execute(
            """
            UPDATE apify_actor_routes
            SET generation = generation + 1,
                updated_at = '2026-07-29T00:00:00+00:00'
            WHERE workspace_id = ? AND route_key = 'x/profile'
            """,
            (workspace["id"],),
        )
        store.connect().commit()
        generation = store.connect().execute(
            """
            SELECT generation FROM apify_actor_routes
            WHERE workspace_id = ? AND route_key = 'x/profile'
            """,
            (workspace["id"],),
        ).fetchone()["generation"]
        return ApifyActorRoutedList(
            [_content_item(suffix="apify-proven-route")],
            route_generation=int(generation),
            workspace_id=str(workspace["id"]),
            source_id=source_id,
            candidate_id="candidate-publication-proof",
            latest_published_at="2026-07-29T00:00:00+00:00",
            latest_item_id="publication-item",
            semantic_outcome="advanced",
        )

    items = asyncio.run(
        coordinator.acquire(
            source=projection,
            provider="apify_social",
            window_hours=24,
            fetch=fetch_from_backup,
        )
    )

    new_context = coordinator._context(projection, window_hours=24)
    snapshot = store.connect().execute(
        """
        SELECT acquisition_key, config_fingerprint
        FROM source_content_snapshots WHERE source_id = ?
        """,
        (source_id,),
    ).fetchone()
    assert [item.id for item in items] == [
        _content_item(suffix="apify-proven-route").id
    ]
    assert new_context.actor_route_generation != old_context.actor_route_generation
    assert snapshot["acquisition_key"] == new_context.acquisition_key
    assert snapshot["config_fingerprint"] == new_context.config_fingerprint
    assert items._apify_actor_candidate_id == "candidate-publication-proof"
    assert items._apify_actor_semantic_outcome == "advanced"

    cached = asyncio.run(
        coordinator.acquire(
            source=projection,
            provider="apify_social",
            window_hours=24,
            fetch=fetch_from_backup,
        )
    )
    assert cached._apify_actor_candidate_id == "candidate-publication-proof"
    assert cached._apify_actor_latest_item_id_hash == (
        items._apify_actor_latest_item_id_hash
    )


def test_public_source_reuses_fresh_acquisition_and_reprojects_per_user(
    tmp_path, monkeypatch, request
):
    store, workspace, owner = _store(tmp_path, monkeypatch, request)
    member = store.create_user(
        workspace_id=workspace["id"],
        username="member",
        password="member-password",
    )
    source_id = _catalog_source(store, workspace, owner)
    owner_sub = store.create_subscription(user_id=owner["id"], source_id=source_id)
    member_sub = store.create_subscription(user_id=member["id"], source_id=source_id)
    calls = 0

    async def fetch():
        nonlocal calls
        calls += 1
        item = _content_item()
        item.ai_score = 9.7
        item.ai_reason = "PRODUCER_AI_REASON"
        item.ai_summary = "PRODUCER_AI_SUMMARY"
        item.ai_summary_zh = "PRODUCER_AI_SUMMARY_ZH"
        item.ai_category = "Producer AI Category"
        item.ai_is_featured = True
        item.ai_tags = ["Producer AI Tag"]
        item.ai_channel = "Producer AI Channel"
        item.ai_topics = ["Producer AI Topic"]
        item.ai_signal_strength = "strong"
        item.ai_signal_type = "producer_signal"
        item.ai_entities = ["Producer Entity"]
        item.ai_action_suggestion = "PRODUCER_AI_ACTION"
        item.metadata.update(
            {
                "ai_content_format": "video",
                "analysis_status": "ai",
                "configured_topics": ["Producer Configured"],
                "detailed_summary_zh": "PRODUCER_DETAILED_SUMMARY",
                "interest_score": 9.4,
                "inferred_topics": ["Producer Inferred"],
                "scoring_disabled": True,
                "signal_strength": "strong",
                "signal_type": "producer_metadata_signal",
                "title_zh": "PRODUCER_TRANSLATED_TITLE",
                "user_state": {"is_saved": True},
            }
        )
        return [item]

    first = SourceAcquisitionCoordinator(
        store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job-owner",
    )
    second = SourceAcquisitionCoordinator(
        store,
        workspace_id=workspace["id"],
        user_id=member["id"],
        job_id="job-member",
    )

    owner_items = asyncio.run(
        first.acquire(
            source=_projection(
                source_id, owner_sub["id"], channel="owner", personal_tag="owner-only"
            ),
            provider="rss",
            window_hours=24,
            fetch=fetch,
        )
    )
    member_items = asyncio.run(
        second.acquire(
            source=_projection(
                source_id,
                member_sub["id"],
                channel="member",
                personal_tag="member-only",
                analysis_mode="full",
            ),
            provider="rss",
            window_hours=24,
            fetch=fetch,
        )
    )

    assert calls == 1
    assert owner_items[0].metadata["subscription_id"] == owner_sub["id"]
    assert owner_items[0].metadata["personal_tags"] == ["owner-only"]
    assert member_items[0].metadata["subscription_id"] == member_sub["id"]
    assert member_items[0].metadata["personal_tags"] == ["member-only"]
    assert member_items[0].metadata["channel"] == "member"
    assert member_items[0].metadata["configured_topics"] == ["member-topic"]
    assert member_items[0].metadata["analysis_mode"] == "full"
    assert "show_in_personal_feed" not in member_items[0].metadata
    assert member_items[0].ai_score is None
    assert member_items[0].ai_reason is None
    assert member_items[0].ai_summary is None
    assert member_items[0].ai_summary_zh is None
    assert member_items[0].ai_category is None
    assert member_items[0].ai_is_featured is False
    assert member_items[0].ai_tags == []
    assert member_items[0].ai_channel is None
    assert member_items[0].ai_topics == []
    assert member_items[0].ai_signal_strength is None
    assert member_items[0].ai_signal_type is None
    assert member_items[0].ai_entities == []
    assert member_items[0].ai_action_suggestion is None
    for metadata_key in (
        "ai_content_format",
        "analysis_status",
        "detailed_summary_zh",
        "interest_score",
        "inferred_topics",
        "scoring_disabled",
        "signal_strength",
        "signal_type",
        "title_zh",
        "user_state",
    ):
        assert metadata_key not in member_items[0].metadata
    assert first.metrics.as_dict() == {
        "cache_hits": 0,
        "cache_misses": 1,
        "upstream_attempts": 1,
        "waits": 0,
    }
    assert second.metrics.as_dict()["cache_hits"] == 1
    assert first.origin_for(source_id) == "upstream"
    assert second.origin_for(source_id) == "cache"
    assert second.origin_for("missing-source") is None


def test_acquisition_does_not_commit_a_callers_transaction(tmp_path, monkeypatch):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    source_id = _catalog_source(store, workspace, owner)
    subscription = store.create_subscription(user_id=owner["id"], source_id=source_id)
    conn = store.connect()
    conn.execute(
        """
        INSERT INTO usage_events (
            id, workspace_id, user_id, event_type, quantity, created_at
        ) VALUES ('usage-uncommitted', ?, ?, 'source_fetch', 1, ?)
        """,
        (workspace["id"], owner["id"], datetime.now(timezone.utc).isoformat()),
    )
    fetch_called = False

    async def fetch():
        nonlocal fetch_called
        fetch_called = True
        return []

    coordinator = SourceAcquisitionCoordinator(
        store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job-transaction-boundary",
    )
    try:
        with pytest.raises(RuntimeError, match="requires no active transaction"):
            asyncio.run(
                coordinator.acquire(
                    source=_projection(
                        source_id,
                        subscription["id"],
                        channel="owner",
                        personal_tag="owner-only",
                    ),
                    provider="rss",
                    window_hours=24,
                    fetch=fetch,
                )
            )
        assert conn.in_transaction is True
        assert fetch_called is False
    finally:
        conn.rollback()

    assert conn.execute(
        "SELECT 1 FROM usage_events WHERE id = 'usage-uncommitted'"
    ).fetchone() is None


def test_successful_empty_acquisition_is_cached(tmp_path, monkeypatch):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    source_id = _catalog_source(store, workspace, owner)
    subscription = store.create_subscription(user_id=owner["id"], source_id=source_id)
    calls = 0

    async def fetch():
        nonlocal calls
        calls += 1
        return []

    async def run_twice():
        coordinator = SourceAcquisitionCoordinator(
            store,
            workspace_id=workspace["id"],
            user_id=owner["id"],
            job_id="job-empty",
        )
        source = _projection(
            source_id, subscription["id"], channel="empty", personal_tag="private"
        )
        return (
            await coordinator.acquire(
                source=source, provider="rss", window_hours=24, fetch=fetch
            ),
            await coordinator.acquire(
                source=source, provider="rss", window_hours=24, fetch=fetch
            ),
        )

    assert asyncio.run(run_twice()) == ([], [])
    assert calls == 1


def test_expired_content_and_configuration_or_secret_changes_miss_cache(
    tmp_path, monkeypatch
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    store.create_secret_ref(
        workspace_id=workspace["id"],
        owner_user_id=owner["id"],
        name="RSS token",
        env_name="RSS_TOKEN",
        kind="source",
        provider="rss",
    )
    source_id = _catalog_source(
        store, workspace, owner, secret_env="RSS_TOKEN"
    )
    subscription = store.create_subscription(user_id=owner["id"], source_id=source_id)
    source = _projection(
        source_id, subscription["id"], channel="owner", personal_tag="owner-only"
    )
    calls = 0

    async def fetch():
        nonlocal calls
        calls += 1
        return [_content_item(suffix=str(calls))]

    def acquire(job_id: str):
        return asyncio.run(
            SourceAcquisitionCoordinator(
                store,
                workspace_id=workspace["id"],
                user_id=owner["id"],
                job_id=job_id,
            ).acquire(
                source=source, provider="rss", window_hours=24, fetch=fetch
            )
        )

    acquire("job-first")
    store.connect().execute(
        "UPDATE source_content_snapshots SET fresh_until = ?",
        ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),),
    )
    store.connect().commit()
    acquire("job-expired")
    store.update_source(
        source_id,
        config={"name": "Renamed only", "url": "https://example.com/changed.xml"},
    )
    acquire("job-config")
    store.connect().execute(
        "UPDATE secret_refs SET updated_at = ? WHERE env_name = 'RSS_TOKEN'",
        ((datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(),),
    )
    store.connect().commit()
    acquire("job-secret")

    assert calls == 4


def test_private_source_acquisition_is_never_shared_between_users(
    tmp_path, monkeypatch
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    member = store.create_user(
        workspace_id=workspace["id"],
        username="member",
        password="member-password",
    )
    source_id = _catalog_source(store, workspace, owner, scope="private")
    calls = 0

    async def fetch():
        nonlocal calls
        calls += 1
        return [_content_item(suffix=str(calls))]

    for user, subscription_id in ((owner, "sub-owner"), (member, "sub-member")):
        asyncio.run(
            SourceAcquisitionCoordinator(
                store,
                workspace_id=workspace["id"],
                user_id=user["id"],
                job_id=f"job-{user['id']}",
            ).acquire(
                source=_projection(
                    source_id,
                    subscription_id,
                    channel=user["username"],
                    personal_tag=user["username"],
                ),
                provider="rss",
                window_hours=24,
                fetch=fetch,
            )
        )

    assert calls == 2


def test_concurrent_waiter_reuses_winner_and_stale_lease_is_recovered(
    tmp_path, monkeypatch
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    source_id = _catalog_source(store, workspace, owner)
    subscription = store.create_subscription(user_id=owner["id"], source_id=source_id)
    source = _projection(
        source_id, subscription["id"], channel="owner", personal_tag="owner"
    )
    calls = 0

    async def run_concurrently():
        started = asyncio.Event()
        release = asyncio.Event()

        async def fetch():
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return [_content_item()]

        first = SourceAcquisitionCoordinator(
            store,
            workspace_id=workspace["id"],
            user_id=owner["id"],
            job_id="job-winner",
            poll_seconds=0.01,
        )
        second = SourceAcquisitionCoordinator(
            store,
            workspace_id=workspace["id"],
            user_id=owner["id"],
            job_id="job-waiter",
            poll_seconds=0.01,
        )
        winner = asyncio.create_task(
            first.acquire(
                source=source, provider="rss", window_hours=24, fetch=fetch
            )
        )
        await started.wait()
        waiter = asyncio.create_task(
            second.acquire(
                source=source, provider="rss", window_hours=24, fetch=fetch
            )
        )
        await asyncio.sleep(0.03)
        release.set()
        return await asyncio.gather(winner, waiter), second

    (winner_items, waiter_items), waiter = asyncio.run(run_concurrently())

    assert calls == 1
    assert winner_items[0].id == waiter_items[0].id
    assert waiter.metrics.as_dict()["waits"] >= 1

    store.connect().execute(
        "UPDATE source_content_snapshots SET fresh_until = ?",
        ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),),
    )
    store.connect().execute(
        """
        UPDATE source_acquisition_states
        SET owner_job_id = 'dead-job', claim_token = 'dead-token', locked_until = ?
        """,
        ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),),
    )
    store.connect().commit()

    async def recovered_fetch():
        nonlocal calls
        calls += 1
        return [_content_item(suffix="recovered")]

    recovered = asyncio.run(
        SourceAcquisitionCoordinator(
            store,
            workspace_id=workspace["id"],
            user_id=owner["id"],
            job_id="job-recovered",
        ).acquire(
            source=source,
            provider="rss",
            window_hours=24,
            fetch=recovered_fetch,
        )
    )

    assert calls == 2
    assert recovered[0].id == "rss:item:recovered"


def test_source_test_probe_bypasses_success_cache_and_never_publishes(
    tmp_path, monkeypatch
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    source_id = _catalog_source(store, workspace, owner)
    subscription = store.create_subscription(user_id=owner["id"], source_id=source_id)
    source = _projection(
        source_id, subscription["id"], channel="owner", personal_tag="owner"
    )
    coordinator = SourceAcquisitionCoordinator(
        store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job-production",
    )

    async def fetch():
        return [_content_item()]

    asyncio.run(
        coordinator.acquire(
            source=source, provider="rss", window_hours=24, fetch=fetch
        )
    )
    probe_calls = 0

    def probe():
        nonlocal probe_calls
        probe_calls += 1
        return {"ok": True}

    result = SourceAcquisitionCoordinator(
        store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job-probe",
    ).run_probe(source=source, call=probe)

    assert result == {"ok": True}
    assert probe_calls == 1
    assert store.connect().execute(
        "SELECT COUNT(*) FROM source_content_snapshots"
    ).fetchone()[0] == 1


def test_source_test_probe_respects_live_production_same_source_claim(
    tmp_path, monkeypatch
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    source_id = _catalog_source(store, workspace, owner)
    subscription = store.create_subscription(user_id=owner["id"], source_id=source_id)
    source = _projection(
        source_id, subscription["id"], channel="owner", personal_tag="owner"
    )
    production = SourceAcquisitionCoordinator(
        store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job-production-live",
    )
    production_context = production._context(source, window_hours=24)
    assert production._try_claim(production_context, "production-token") == "claimed"
    probe_calls = 0

    def probe():
        nonlocal probe_calls
        probe_calls += 1
        return {"ok": True}

    with pytest.raises(AcquisitionBusyError):
        SourceAcquisitionCoordinator(
            store,
            workspace_id=workspace["id"],
            user_id=owner["id"],
            job_id="job-probe-blocked",
            wait_seconds=0,
        ).run_probe(source=source, call=probe)

    assert probe_calls == 0


def test_telegram_identity_channel_is_part_of_acquisition_fingerprint(
    tmp_path, monkeypatch
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="telegram_channel",
        display_name="Telegram",
        config={"channel": "durov", "limit": 1},
        source_key="telegram:durov",
    )
    subscription = store.create_subscription(user_id=owner["id"], source_id=source_id)
    projection = _projection(
        source_id, subscription["id"], channel="AI", personal_tag="owner"
    )
    coordinator = SourceAcquisitionCoordinator(
        store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job-telegram-key",
    )
    before = coordinator._context(projection, window_hours=24)

    store.update_source(
        source_id,
        config={"channel": "telegram", "limit": 1},
        source_key="telegram:telegram",
    )
    after = coordinator._context(projection, window_hours=24)

    assert after.config_fingerprint != before.config_fingerprint
    assert after.acquisition_key != before.acquisition_key


def test_public_acquisition_is_single_upstream_call_across_worker_connections(
    tmp_path, monkeypatch
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    member = store.create_user(
        workspace_id=workspace["id"],
        username="member-thread",
        password="member-password",
    )
    source_id = _catalog_source(store, workspace, owner)
    owner_sub = store.create_subscription(user_id=owner["id"], source_id=source_id)
    member_sub = store.create_subscription(user_id=member["id"], source_id=source_id)
    barrier = threading.Barrier(2)
    calls_lock = threading.Lock()
    calls = 0

    def run(user, subscription):
        worker_store = ServiceStore(tmp_path)
        barrier.wait(timeout=2)

        async def fetch():
            nonlocal calls
            with calls_lock:
                calls += 1
            await asyncio.sleep(0.08)
            return [_content_item()]

        try:
            return asyncio.run(
                SourceAcquisitionCoordinator(
                    worker_store,
                    workspace_id=workspace["id"],
                    user_id=user["id"],
                    job_id=f"job-thread-{user['id']}",
                    poll_seconds=0.01,
                ).acquire(
                    source=_projection(
                        source_id,
                        subscription["id"],
                        channel=user["username"],
                        personal_tag=user["username"],
                    ),
                    provider="rss",
                    window_hours=24,
                    fetch=fetch,
                )
            )
        finally:
            worker_store.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(run, owner, owner_sub),
            pool.submit(run, member, member_sub),
        ]
        results = [future.result(timeout=5) for future in futures]

    assert calls == 1
    assert {
        items[0].metadata["subscription_id"] for items in results
    } == {owner_sub["id"], member_sub["id"]}
