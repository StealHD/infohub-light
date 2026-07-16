from datetime import datetime, timezone

import pytest

import src.ai.analysis_cache as analysis_cache_module
from src.ai.analysis_cache import ANALYSIS_PROMPT_VERSION
from src.models import ContentItem, SourceType
from src.services.job_eligibility import JobIneligibleError
from src.services.job_queue import JobQueue
from src.services.quota import QuotaExceeded
from src.services.user_analysis_cache import UserAnalysisCache
from src.storage.service_store import ServiceStore


def _item(item_id: str = "rss:test:1", content: str = "same body") -> ContentItem:
    return ContentItem(
        id=item_id,
        source_type=SourceType.RSS,
        title="Same title",
        url="https://example.com/item",
        content=content,
        author="Author",
        published_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        metadata={
            "source_display_name": "Feed",
            "catalog_source_type": "rss",
            "channel": "AI",
            "topics": ["Codex"],
        },
    )


def _analyzed_item() -> ContentItem:
    item = _item()
    item.ai_score = 8.4
    item.ai_summary = "Summary"
    item.ai_summary_zh = "中文概括"
    item.ai_channel = "AI"
    item.ai_topics = ["Codex"]
    item.ai_signal_strength = "strong"
    item.ai_signal_type = "release"
    item.ai_entities = ["OpenAI"]
    item.ai_is_featured = True
    item.ai_action_suggestion = "保存"
    item.metadata["analysis_status"] = "ai"
    return item


def test_user_analysis_cache_reuses_only_same_user_and_input(tmp_path, monkeypatch) -> None:
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
        role="member",
    )
    owner_cache = UserAnalysisCache(store, workspace_id=workspace["id"], user_id=owner["id"])
    member_cache = UserAnalysisCache(store, workspace_id=workspace["id"], user_id=member["id"])

    owner_cache.store(_analyzed_item(), model="gemini-test", prompt_version=ANALYSIS_PROMPT_VERSION)

    owner_hit = _item()
    member_miss = _item()
    changed_miss = _item(content="changed body")
    assert owner_cache.apply(owner_hit, model="gemini-test", prompt_version=ANALYSIS_PROMPT_VERSION) is True
    assert member_cache.apply(member_miss, model="gemini-test", prompt_version=ANALYSIS_PROMPT_VERSION) is False
    assert owner_cache.apply(changed_miss, model="gemini-test", prompt_version=ANALYSIS_PROMPT_VERSION) is False
    assert owner_hit.ai_summary_zh == "中文概括"
    assert owner_hit.ai_reason is None
    assert owner_hit.metadata["analysis_status"] == "ai"
    assert owner_hit.metadata["analysis_cache_hit"] is True


def test_user_analysis_cache_reuses_safe_same_input_across_models(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    cache = UserAnalysisCache(store, workspace_id=workspace["id"], user_id=owner["id"])
    cache.store(_analyzed_item(), model="gemini-old", prompt_version=ANALYSIS_PROMPT_VERSION)

    reused = _item()
    assert cache.apply(reused, model="deepseek-v4-flash", prompt_version=ANALYSIS_PROMPT_VERSION) is True
    assert reused.ai_summary_zh == "中文概括"
    assert reused.metadata["analysis_cache_hit"] is True
    assert reused.metadata["analysis_reused_across_model"] is True
    assert reused.metadata["analysis_source_model"] == "gemini-old"
    assert reused.metadata.get("analysis_model") != "deepseek-v4-flash"

    changed = _item(content="a genuinely changed article")
    assert cache.apply(changed, model="deepseek-v4-flash", prompt_version=ANALYSIS_PROMPT_VERSION) is False


def test_user_analysis_cache_reuses_safe_stable_content_when_cache_table_is_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    item = _item(item_id="rss:stable-analysis:1")
    input_hash = UserAnalysisCache.content_hash(item)
    now = datetime.now(timezone.utc).isoformat()
    store.connect().execute(
        """
        INSERT INTO user_content_items (
            id, workspace_id, user_id, article_id, item_json, body_text,
            body_completeness, analysis_input_hash, first_seen_at, last_seen_at,
            created_at, updated_at
        ) VALUES ('uci_stable', ?, ?, ?, ?, ?, 'captured', ?, ?, ?, ?, ?)
        """,
        (
            workspace["id"], owner["id"], item.id,
            __import__("json").dumps({
                "id": item.id, "score": 8.1, "summary_zh": "既有安全概括",
                "channel": "AI", "topics": ["Codex"], "signal_strength": "strong",
                "signal_type": "release", "entities": ["OpenAI"],
                "presentation": {"analysis": {"status": "ai", "summary_zh": "既有安全概括"}},
            }, ensure_ascii=False),
            item.content, input_hash, now, now, now, now,
        ),
    )
    store.connect().commit()
    cache = UserAnalysisCache(store, workspace_id=workspace["id"], user_id=owner["id"])

    assert cache.apply(item, model="deepseek-v4-flash", prompt_version=ANALYSIS_PROMPT_VERSION) is True
    assert item.ai_summary_zh == "既有安全概括"
    assert item.metadata["analysis_reused_across_model"] is True
    assert item.metadata["analysis_source_model"] == "stored-content"
    assert store.connect().execute("SELECT COUNT(*) FROM user_analysis_cache").fetchone()[0] == 0


def test_user_analysis_cache_persists_no_raw_input_or_reason(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    cache = UserAnalysisCache(store, workspace_id=workspace["id"], user_id=owner["id"])

    item = _analyzed_item()
    item.content = "PRIVATE RAW BODY"
    item.ai_reason = "obsolete reason"
    cache.store(item, model="gemini-test", prompt_version=ANALYSIS_PROMPT_VERSION)

    row = store.connect().execute(
        "SELECT result_json FROM user_analysis_cache WHERE user_id = ?",
        (owner["id"],),
    ).fetchone()
    assert row is not None
    assert "PRIVATE RAW BODY" not in row["result_json"]
    assert "obsolete reason" not in row["result_json"]
    assert '"reason"' not in row["result_json"]
    assert '"action_suggestion"' not in row["result_json"]


def test_analysis_prompt_version_changes_with_topic_library() -> None:
    analysis_prompt_version = getattr(analysis_cache_module, "analysis_prompt_version", None)
    assert callable(analysis_prompt_version)
    first = analysis_prompt_version(["AI Agent", "RAG/MCP"])
    reordered = analysis_prompt_version(["RAG/MCP", "AI Agent"])
    changed = analysis_prompt_version(["AI Agent", "模型发布"])

    assert first == reordered
    assert first != changed
    assert first.startswith(f"{ANALYSIS_PROMPT_VERSION}:")
    assert analysis_prompt_version(None) != analysis_prompt_version([])


def test_user_analysis_cache_atomically_enforces_daily_ai_item_quota(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("INFOHUB_MAX_AI_ITEMS_PER_DAY", "1")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    cache = UserAnalysisCache(
        store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
    )

    cache.before_ai_item(provider="gemini")
    with pytest.raises(QuotaExceeded, match="daily AI item quota exceeded"):
        cache.before_ai_item(provider="gemini")

    usage = store.connect().execute(
        """
        SELECT COALESCE(SUM(quantity), 0) AS total
        FROM usage_events
        WHERE user_id = ? AND event_type = 'ai_item'
        """,
        (owner["id"],),
    ).fetchone()
    assert int(usage["total"]) == 1


def test_user_analysis_cache_atomically_enforces_workspace_ai_attempt_quota(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("INFOHUB_MAX_WORKSPACE_AI_ATTEMPTS_PER_DAY", "1")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    member = store.create_user(
        workspace_id=workspace["id"],
        username="member-attempt",
        password="member-password",
    )
    owner_cache = UserAnalysisCache(
        store, workspace_id=workspace["id"], user_id=owner["id"]
    )
    member_cache = UserAnalysisCache(
        store, workspace_id=workspace["id"], user_id=member["id"]
    )

    owner_cache.before_ai_attempt(provider="gemini")
    with pytest.raises(QuotaExceeded, match="workspace AI attempt quota exceeded"):
        member_cache.before_ai_attempt(provider="gemini")

    usage = store.connect().execute(
        """
        SELECT COALESCE(SUM(quantity), 0) AS total
        FROM usage_events
        WHERE workspace_id = ? AND event_type = 'ai_attempt'
        """,
        (workspace["id"],),
    ).fetchone()
    assert int(usage["total"]) == 1


def test_ai_attempt_rechecks_source_eligibility_before_charging(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="AI Eligibility",
        config={"url": "https://example.com/ai-eligibility.xml"},
    )
    store.create_subscription(user_id=owner["id"], source_id=source_id)
    queue = JobQueue(store)
    job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="user_feed_refresh",
    )
    queue.claim_next_job(worker_id="analysis-worker")
    store.connect().execute(
        "UPDATE source_catalog SET enabled = 0 WHERE id = ?",
        (source_id,),
    )
    store.connect().commit()
    cache = UserAnalysisCache(
        store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=job["id"],
    )

    with pytest.raises(JobIneligibleError, match="source_disabled"):
        cache.before_ai_network_attempt(
            provider="gemini",
            source_id=source_id,
        )

    usage = store.connect().execute(
        "SELECT COUNT(*) AS total FROM usage_events WHERE event_type = 'ai_attempt'"
    ).fetchone()
    assert int(usage["total"]) == 0
    cache.close()
