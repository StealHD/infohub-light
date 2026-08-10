import asyncio
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.api.server import create_app
from src.models import AIConfig, AIProvider
from src.services.quota import QuotaService
from src.services.source_summary import (
    SOURCE_SUMMARY_INPUT_CHARS,
    SOURCE_SUMMARY_PROMPT_REVISION,
    SOURCE_SUMMARY_SYSTEM_PROMPT,
    SourceSummaryError,
    SourceSummaryService,
    build_source_summary_input,
)
from src.services.user_feed_store import UserFeedStore
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


class FakeAIClient:
    def __init__(self, result: str) -> None:
        self.result = result
        self.calls: list[tuple[str, str, float | None, int | None]] = []
        self.closed = False

    async def complete(self, system, user, temperature=None, max_tokens=None):
        self.calls.append((system, user, temperature, max_tokens))
        return self.result

    async def aclose(self):
        self.closed = True


def _ai_config(*, enabled: bool = True) -> AIConfig:
    return AIConfig(
        enabled=enabled,
        provider=AIProvider.OPENAI,
        model="fake-summary-model",
        api_key_env="FAKE_SUMMARY_KEY",
        summary_max_chars=220,
        analysis_max_output_tokens=700,
    )


def _store_with_items(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "summary-owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "safe-test-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "summary-session-secret")
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    owner = store.get_user_by_username("summary-owner")
    assert owner is not None
    items = [
        {
            "id": "article-1",
            "title": "第一条标题",
            "url": "https://secret.example.test/one?token=never-send",
            "summary_zh": "第一条现有摘要 https://embedded.example.test/do-not-send",
            "published_at": "2026-08-09T01:00:00+00:00",
            "presentation": {
                "content": {"title": "第一条标题", "excerpt": "第一条摘录"},
                "analysis": {"summary_zh": "第一条现有摘要 https://embedded.example.test/do-not-send"},
                "timing": {"published_at": "2026-08-09T01:00:00+00:00"},
                "links": {"canonical_url": "https://secret.example.test/one"},
            },
        },
        {
            "id": "article-2",
            "title": "第二条标题",
            "url": "https://secret.example.test/two",
            "summary_zh": "第二条现有摘要",
            "published_at": "2026-08-08T01:00:00+00:00",
        },
    ]
    UserFeedStore(store).save_snapshot(
        workspace_id=owner["workspace_id"],
        user_id=owner["id"],
        job_id=None,
        payload={
            "schema_version": 2,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "items": items,
        },
    )
    return store, owner


def test_source_summary_uses_visible_feed_text_without_urls_and_counts_one_attempt(tmp_path, monkeypatch):
    store, owner = _store_with_items(tmp_path, monkeypatch)
    fake = FakeAIClient(json.dumps({
        "overview": "两条内容都在更新同一专题。",
        "highlights": ["[1] 第一项发生变化", "[2] 第二项提供后续线索"],
    }, ensure_ascii=False))
    factory_calls = []

    def factory(config, **kwargs):
        factory_calls.append((config, kwargs))
        return fake

    service = SourceSummaryService(store, client_factory=factory)
    before = store.count_usage_since(
        workspace_id=owner["workspace_id"],
        user_id=owner["id"],
        event_types=["ai_attempt"],
        since=datetime(2000, 1, 1, tzinfo=timezone.utc),
    )
    result = asyncio.run(service.generate(
        workspace_id=owner["workspace_id"],
        user_id=owner["id"],
        article_ids=["article-1", "article-2"],
        ai_config=_ai_config(),
    ))
    after = store.count_usage_since(
        workspace_id=owner["workspace_id"],
        user_id=owner["id"],
        event_types=["ai_attempt"],
        since=datetime(2000, 1, 1, tzinfo=timezone.utc),
    )

    assert result == {
        "schema_version": 1,
        "overview": "两条内容都在更新同一专题。",
        "highlights": ["[1] 第一项发生变化", "[2] 第二项提供后续线索"],
        "item_count": 2,
    }
    assert after - before == 1
    assert factory_calls[0][1] == {"single_attempt": True, "timeout_seconds": 60.0}
    assert fake.closed is True
    prompt = "\n".join(fake.calls[0][:2])
    assert "第一条现有摘要" in prompt
    assert "第二条现有摘要" in prompt
    assert "secret.example.test" not in prompt
    assert "embedded.example.test" not in prompt
    assert "token=never-send" not in prompt
    assert "不得访问链接" in prompt
    assert SOURCE_SUMMARY_PROMPT_REVISION == "mainline-v1"
    assert fake.calls[0][0] == SOURCE_SUMMARY_SYSTEM_PROMPT
    assert "最主要的内容主线及变化方向" in prompt
    assert "合并重复内容" in prompt
    assert "不得逐篇复述" in prompt
    assert "[1][3]" in prompt
    assert "样本有限" in prompt
    assert "方括号编号仅用于" in prompt


def test_source_summary_recovers_wrapped_json_and_scalar_highlight_without_retry(tmp_path, monkeypatch):
    store, owner = _store_with_items(tmp_path, monkeypatch)
    recovered = json.dumps({
        "overview": "近期主线是产品更新，变化方向是交付节奏加快。",
        "highlights": "[1][2] 连续发布的内容指向同一条产品主线。",
    }, ensure_ascii=False)
    fake = FakeAIClient(
        "输出如下（忽略此前调试对象）：\n"
        '{"debug":true}\n'
        f"```json\n{recovered}\n```\n"
        "以上是专题速览。"
    )
    service = SourceSummaryService(store, client_factory=lambda *_args, **_kwargs: fake)

    result = asyncio.run(service.generate(
        workspace_id=owner["workspace_id"],
        user_id=owner["id"],
        article_ids=["article-1", "article-2"],
        ai_config=_ai_config(),
    ))

    assert result == {
        "schema_version": 1,
        "overview": "近期主线是产品更新，变化方向是交付节奏加快。",
        "highlights": ["[1][2] 连续发布的内容指向同一条产品主线。"],
        "item_count": 2,
    }
    assert len(fake.calls) == 1


def test_source_summary_rejects_disabled_cross_user_and_invalid_output(tmp_path, monkeypatch):
    store, owner = _store_with_items(tmp_path, monkeypatch)
    other = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="summary-other",
        password="safe-test-password",
    )
    service = SourceSummaryService(store, client_factory=lambda *_args, **_kwargs: FakeAIClient("{}"))

    with pytest.raises(SourceSummaryError, match="尚未启用") as disabled:
        asyncio.run(service.generate(
            workspace_id=owner["workspace_id"],
            user_id=owner["id"],
            article_ids=["article-1"],
            ai_config=_ai_config(enabled=False),
        ))
    assert disabled.value.status_code == 409

    with pytest.raises(SourceSummaryError, match="不存在或不可见") as hidden:
        asyncio.run(service.generate(
            workspace_id=other["workspace_id"],
            user_id=other["id"],
            article_ids=["article-1"],
            ai_config=_ai_config(),
        ))
    assert hidden.value.status_code == 404

    with pytest.raises(SourceSummaryError) as invalid:
        asyncio.run(service.generate(
            workspace_id=owner["workspace_id"],
            user_id=owner["id"],
            article_ids=["article-1"],
            ai_config=_ai_config(),
        ))
    assert invalid.value.code == "source_summary_invalid_output"
    assert invalid.value.status_code == 502


def test_source_summary_maps_timeout_and_always_closes_client(tmp_path, monkeypatch):
    store, owner = _store_with_items(tmp_path, monkeypatch)

    class SlowAI(FakeAIClient):
        async def complete(self, *_args, **_kwargs):
            await asyncio.sleep(1)
            return self.result

    fake = SlowAI('{"overview":"ok","highlights":["one"]}')
    service = SourceSummaryService(store, client_factory=lambda *_args, **_kwargs: fake)
    service.timeout_seconds = 0.01
    with pytest.raises(SourceSummaryError) as timeout:
        asyncio.run(service.generate(
            workspace_id=owner["workspace_id"],
            user_id=owner["id"],
            article_ids=["article-1"],
            ai_config=_ai_config(),
        ))
    assert timeout.value.code == "source_summary_timeout"
    assert timeout.value.status_code == 504
    assert fake.closed is True


def test_source_summary_input_preserves_all_titles_within_budget():
    rendered = build_source_summary_input([
        {"title": f"标题 {index} " + "很长" * 200, "summary": "摘要" * 2_000, "published_at": "2026-08-09"}
        for index in range(1, 101)
    ])

    assert len(rendered) <= SOURCE_SUMMARY_INPUT_CHARS
    for index in range(1, 101):
        assert f"[{index}] 标题：标题 {index}" in rendered


def test_source_summary_output_respects_the_configured_character_budget(tmp_path, monkeypatch):
    store, owner = _store_with_items(tmp_path, monkeypatch)
    fake = FakeAIClient(json.dumps({
        "overview": "总览" * 200,
        "highlights": ["要点" * 200 for _ in range(5)],
    }, ensure_ascii=False))
    service = SourceSummaryService(store, client_factory=lambda *_args, **_kwargs: fake)
    result = asyncio.run(service.generate(
        workspace_id=owner["workspace_id"],
        user_id=owner["id"],
        article_ids=["article-1"],
        ai_config=_ai_config(),
    ))

    assert len(result["overview"]) + sum(len(value) for value in result["highlights"]) <= 220


def _api_client(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "safe-test-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "summary-api-session")
    data_dir = tmp_path / "data"
    static_dir = tmp_path / "static"
    data_dir.mkdir(parents=True)
    static_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (data_dir / "config.json").write_text(json.dumps({
        "version": "1.0",
        "ai": {
            "enabled": True,
            "provider": "openai",
            "model": "fake-summary-model",
            "api_key_env": "FAKE_SUMMARY_KEY",
        },
        "tags": [],
        "personal_tags": [],
        "sources": {"rss": [], "github": [], "hackernews": {"enabled": False}},
        "filtering": {"ai_score_threshold": 7.5, "time_window_hours": 24},
    }), encoding="utf-8")
    app = create_app(data_dir=data_dir, static_dir=static_dir)
    return TestClient(app)


def test_source_summary_api_auth_validation_dedup_and_viewer_guard(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)

    class FakeService:
        def __init__(self):
            self.calls = []

        async def generate(self, **kwargs):
            self.calls.append(kwargs)
            return {"schema_version": 1, "overview": "概览", "highlights": ["要点"], "item_count": len(kwargs["article_ids"])}

    fake = FakeService()
    client.app.state.source_summary_service = fake
    assert client.post("/api/feed/source-summary", json={"article_ids": ["a"]}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "owner", "password": "safe-test-password"}).status_code == 200

    response = client.post("/api/feed/source-summary", json={"article_ids": ["a", "a", "b"]})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["data"]["item_count"] == 2
    assert fake.calls[0]["article_ids"] == ["a", "b"]
    assert client.post("/api/feed/source-summary", json={"article_ids": [], "extra": True}).status_code == 400
    assert client.post("/api/feed/source-summary", json={"article_ids": [str(index) for index in range(101)]}).status_code == 400

    store = client.app.state.service_store
    store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="summary-viewer",
        password="safe-test-password",
        role="viewer",
    )
    assert client.post("/api/auth/login", json={"username": "summary-viewer", "password": "safe-test-password"}).status_code == 200
    forbidden = client.post("/api/feed/source-summary", json={"article_ids": ["a"]})
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "forbidden"
    assert len(fake.calls) == 1
