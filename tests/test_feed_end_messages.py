import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.api.server import create_app
from src.ai.client import OpenAIClient, create_ai_client
from src.models import Config
from src.services.feed_end_messages import (
    BUILTIN_FEED_END_MESSAGES,
    FEED_END_MESSAGE_CONTRACT_VERSION,
    FeedEndMessagesDisabled,
    FeedEndMessagesOutputError,
    FeedEndMessagesService,
    feed_end_messages_config_fingerprint,
    feed_end_messages_prompt,
    parse_feed_end_messages_response,
    run_due_feed_end_messages_generation,
    validate_feed_end_message_lists,
)
from src.services.job_queue import JobQueue
from src.services.worker import run_worker_once
from src.storage.service_store import ServiceStore
from src.ui.server import apply_config_action, validate_config_data


def _config_data(*, ai_enabled: bool = True, generator_enabled: bool = True):
    return {
        "version": "1.0",
        "ai": {
            "enabled": ai_enabled,
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_key_env": "OPENAI_API_KEY",
        },
        "feed_end_messages": {
            "ai_generation_enabled": generator_enabled,
            "refresh_days": 7,
            "style_preset": "restrained",
            "style_prompt": "",
            "list_count": 3,
        },
        "sources": {
            "rss": [],
            "github": [],
            "hackernews": {"enabled": False},
        },
        "filtering": {"ai_score_threshold": 7.5, "time_window_hours": 24},
    }


def _config(*, ai_enabled: bool = True, generator_enabled: bool = True) -> Config:
    return validate_config_data(
        _config_data(
            ai_enabled=ai_enabled,
            generator_enabled=generator_enabled,
        )
    )


def _messages(count: int = 3) -> dict[str, list[str]]:
    labels = {
        "empty": "空白处先歇一会",
        "first_end": "这一轮先读到这里",
        "repeat_end": "再次走到列表末尾",
    }
    return {
        scene: [f"{label}，版本{index + 1}。" for index in range(count)]
        for scene, label in labels.items()
    }


def _store(tmp_path, monkeypatch) -> tuple[ServiceStore, dict, dict]:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    assert owner is not None
    return store, workspace, owner


def test_feed_end_message_config_defaults_and_strict_boundaries():
    data = _config_data()
    data.pop("feed_end_messages")
    defaulted = validate_config_data(data).feed_end_messages

    assert defaulted.model_dump() == {
        "ai_generation_enabled": False,
        "refresh_days": 7,
        "style_preset": "restrained",
        "style_prompt": "",
        "list_count": 12,
        "ai_key_env": "",
        "model": "",
    }

    for field, value in [
        ("refresh_days", 2),
        ("refresh_days", "7"),
        ("list_count", 2),
        ("list_count", 31),
        ("list_count", 3.0),
        ("style_preset", "loud"),
        ("style_prompt", "字" * 501),
        ("ai_key_env", 123),
        ("ai_key_env", "x" * 129),
        ("model", 123),
        ("model", "x" * 257),
    ]:
        invalid = _config_data()
        invalid["feed_end_messages"][field] = value
        with pytest.raises(ValueError):
            validate_config_data(invalid)


def test_feed_end_message_settings_bundle_is_validated_atomically():
    base = _config_data()
    updated = apply_config_action(
        base,
        "set_settings_bundle",
        {
            "feed_end_messages": {
                "ai_generation_enabled": True,
                "refresh_days": 30,
                "style_preset": "warm",
                "style_prompt": "像安静的图书管理员",
                "list_count": 8,
                "ai_key_env": "DEEPSEEK_API_KEY",
                "model": "deepseek-v4-flash",
            }
        },
    )

    assert updated["feed_end_messages"] == {
        "ai_generation_enabled": True,
        "refresh_days": 30,
        "style_preset": "warm",
        "style_prompt": "像安静的图书管理员",
        "list_count": 8,
        "ai_key_env": "DEEPSEEK_API_KEY",
        "model": "deepseek-v4-flash",
    }
    fallback = apply_config_action(
        base,
        "set_feed_end_messages",
        {
            "ai_generation_enabled": False,
            "refresh_days": 7,
            "style_preset": "restrained",
            "style_prompt": "",
            "list_count": 12,
            "ai_key_env": "",
            "model": "",
        },
    )
    assert fallback["feed_end_messages"]["ai_key_env"] == ""
    with pytest.raises(ValueError, match="触底文案 AI Key 环境变量名"):
        apply_config_action(
            base,
            "set_feed_end_messages",
            {
                "ai_generation_enabled": True,
                "refresh_days": 7,
                "style_preset": "restrained",
                "style_prompt": "",
                "list_count": 12,
                "ai_key_env": "sk-not-an-env-name",
            },
        )
    with pytest.raises(ValueError, match="list_count"):
        apply_config_action(
            base,
            "set_feed_end_messages",
            {
                "ai_generation_enabled": True,
                "refresh_days": 7,
                "style_preset": "restrained",
                "style_prompt": "",
                "list_count": True,
            },
        )
    with pytest.raises(ValueError, match="未知触底文案设置字段"):
        apply_config_action(
            base,
            "set_feed_end_messages",
            {"unexpected": "value"},
        )
    with pytest.raises(ValueError, match="style_prompt 必须是字符串"):
        apply_config_action(
            base,
            "set_feed_end_messages",
            {"style_prompt": 123},
        )


def test_feed_end_message_output_requires_exact_safe_unique_plain_text():
    messages = _messages()
    assert validate_feed_end_message_lists(
        BUILTIN_FEED_END_MESSAGES,
        expected_count=None,
    ) == BUILTIN_FEED_END_MESSAGES
    assert validate_feed_end_message_lists(messages, expected_count=3) == messages
    assert parse_feed_end_messages_response(
        json.dumps(messages, ensure_ascii=False),
        expected_count=3,
    ) == messages
    decorated = _messages()
    decorated["empty"][0] = "这里先休息一下🙂"
    decorated["first_end"][0] = "这一轮先读到这里^_^"
    assert validate_feed_end_message_lists(
        decorated,
        expected_count=3,
    ) == decorated
    system_prompt, user_prompt = feed_end_messages_prompt(_config())
    assert "最多使用一个克制装饰" in system_prompt
    assert "禁止其他 Emoji 或颜文字" in system_prompt
    assert "替代空列表的原有说明" in user_prompt

    invalid_values = []
    missing_scene = _messages()
    missing_scene.pop("repeat_end")
    invalid_values.append(missing_scene)
    duplicate = _messages()
    duplicate["repeat_end"][0] = duplicate["empty"][0]
    invalid_values.append(duplicate)
    markup = _messages()
    markup["empty"][0] = "**这里没有内容**"
    invalid_values.append(markup)
    markdown_list = _messages()
    markdown_list["empty"][0] = "- 这里没有内容"
    invalid_values.append(markdown_list)
    unsupported_emoji = _messages()
    unsupported_emoji["empty"][0] = "这里先休息一下🚀"
    invalid_values.append(unsupported_emoji)
    decoration_spam = _messages()
    decoration_spam["empty"][0] = "这里先休息一下🙂✨"
    invalid_values.append(decoration_spam)
    visual_duplicate = _messages()
    visual_duplicate["empty"][0] = "这里先休息一下☕"
    visual_duplicate["empty"][1] = "这里先休息一下☕️"
    invalid_values.append(visual_duplicate)
    url = _messages()
    url["empty"][0] = "去 https://example.com 看看"
    invalid_values.append(url)
    unsafe = _messages()
    unsafe["empty"][0] = "快点去加载更多内容。"
    invalid_values.append(unsafe)
    false_completion = _messages()
    false_completion["first_end"][0] = "所有工作都搞定了。"
    invalid_values.append(false_completion)
    traditional = _messages()
    traditional["empty"][0] = "這裡暫時沒有內容。"
    invalid_values.append(traditional)

    for value in invalid_values:
        with pytest.raises(FeedEndMessagesOutputError):
            validate_feed_end_message_lists(value, expected_count=3)

    with pytest.raises(FeedEndMessagesOutputError):
        parse_feed_end_messages_response(
            f"```json\n{json.dumps(messages, ensure_ascii=False)}\n```",
            expected_count=3,
        )


def test_feed_end_message_fingerprint_includes_copy_contract_version(monkeypatch):
    config = _config()
    initial = feed_end_messages_config_fingerprint(config)

    monkeypatch.setattr(
        "src.services.feed_end_messages.FEED_END_MESSAGE_CONTRACT_VERSION",
        FEED_END_MESSAGE_CONTRACT_VERSION + 1,
    )

    assert feed_end_messages_config_fingerprint(config) != initial


def test_direct_feed_end_binding_ignores_workspace_ai_changes():
    data = _config_data()
    data["feed_end_messages"].update(
        {"ai_key_env": "GEMINI_COPY_KEY", "model": "gemini-2.5-flash"}
    )
    config = validate_config_data(data)
    initial = feed_end_messages_config_fingerprint(config)

    changed = config.model_copy(
        update={
            "ai": config.ai.model_copy(
                update={"enabled": False, "model": "another-workspace-model"}
            )
        }
    )

    assert feed_end_messages_config_fingerprint(changed) == initial


def test_disabled_generation_uses_builtins_and_rejects_manual_refresh(
    tmp_path, monkeypatch
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    service = FeedEndMessagesService(store)
    config = _config(generator_enabled=False)

    state = service.public_state(
        workspace_id=workspace["id"],
        config=config,
    )

    assert state["status"] == "disabled"
    assert state["source"] == "builtin"
    assert state["scenes"] == BUILTIN_FEED_END_MESSAGES
    with pytest.raises(FeedEndMessagesDisabled):
        service.request_refresh(
            workspace_id=workspace["id"],
            requested_by_user_id=owner["id"],
            config=config,
        )


def test_first_generation_failure_falls_back_to_builtins(tmp_path, monkeypatch):
    store, workspace, _owner = _store(tmp_path, monkeypatch)
    current = datetime(2026, 7, 29, tzinfo=timezone.utc)
    config = _config()
    service = FeedEndMessagesService(store)
    claim = service.claim_due(config=config, worker_id="copy-worker", now=current)
    assert claim is not None

    service.complete_failure(
        claim,
        error_code="feed_end_messages_timeout",
        now=current,
    )
    state = service.public_state(
        workspace_id=workspace["id"],
        config=config,
        now=current,
    )

    assert state["status"] == "degraded"
    assert state["source"] == "builtin"
    assert state["scenes"] == BUILTIN_FEED_END_MESSAGES


def test_atomic_claim_manual_refresh_fingerprint_and_failure_retention(
    tmp_path, monkeypatch
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    current = datetime(2026, 7, 29, 1, 0, tzinfo=timezone.utc)
    config = _config()
    service = FeedEndMessagesService(store, now_factory=lambda: current)

    first_claim = service.claim_due(
        config=config,
        worker_id="worker-one",
        now=current,
    )
    assert first_claim is not None

    other_store = ServiceStore(tmp_path)
    other_store.initialize()
    other_service = FeedEndMessagesService(other_store)
    assert other_service.claim_due(
        config=config,
        worker_id="worker-two",
        now=current,
    ) is None

    generated = _messages()
    assert service.complete_success(
        first_claim,
        config=config,
        messages=generated,
        now=current,
    )
    ready = service.public_state(
        workspace_id=workspace["id"],
        config=config,
        now=current,
    )
    assert ready["source"] == "ai"
    assert ready["status"] == "ready"
    assert ready["generation"] == 1

    disabled = config.model_copy(deep=True)
    disabled.ai.enabled = False
    disabled_state = service.public_state(
        workspace_id=workspace["id"],
        config=disabled,
        now=current,
    )
    assert disabled_state["status"] == "disabled"
    assert disabled_state["source"] == "builtin"
    assert disabled_state["scenes"] == BUILTIN_FEED_END_MESSAGES

    requested = service.request_refresh(
        workspace_id=workspace["id"],
        requested_by_user_id=owner["id"],
        config=config,
        now=current + timedelta(minutes=1),
    )
    requested_again = service.request_refresh(
        workspace_id=workspace["id"],
        requested_by_user_id=owner["id"],
        config=config,
        now=current + timedelta(minutes=1),
    )
    assert requested["status"] == requested_again["status"] == "pending"
    assert requested_again["generation"] == 1

    failed_claim = service.claim_due(
        config=config,
        worker_id="worker-three",
        now=current + timedelta(minutes=2),
    )
    assert failed_claim is not None
    service.complete_failure(
        failed_claim,
        error_code="feed_end_messages_invalid_output",
        now=current + timedelta(minutes=2),
    )
    degraded = service.public_state(
        workspace_id=workspace["id"],
        config=config,
        now=current + timedelta(minutes=3),
    )
    assert degraded["status"] == "degraded"
    assert degraded["source"] == "ai"
    assert degraded["scenes"] == generated
    assert degraded["last_error_code"] == "feed_end_messages_invalid_output"
    assert datetime.fromisoformat(degraded["retry_at"]) == current + timedelta(
        hours=6, minutes=2
    )
    assert service.claim_due(
        config=config,
        worker_id="worker-four",
        now=current + timedelta(hours=1),
    ) is None

    changed = config.model_copy(deep=True)
    changed.feed_end_messages.style_prompt = "更温和一些"
    assert service.claim_due(
        config=changed,
        worker_id="worker-five",
        now=current + timedelta(hours=1),
    ) is not None


def test_workspace_cache_rows_are_isolated(tmp_path, monkeypatch):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    now = datetime(2026, 7, 29, tzinfo=timezone.utc)
    other_workspace_id = "ws_other"
    conn = store.connect()
    conn.execute(
        """
        INSERT INTO workspaces (id, name, created_at, updated_at)
        VALUES (?, 'Other', ?, ?)
        """,
        (other_workspace_id, now.isoformat(), now.isoformat()),
    )
    conn.commit()
    other_owner = store.create_user(
        workspace_id=other_workspace_id,
        username="other-owner",
        password="other-password",
        role="owner",
    )
    config = _config()
    service = FeedEndMessagesService(store)
    first = service.claim_due(config=config, worker_id="worker-a", now=now)
    assert first is not None
    service.complete_success(first, config=config, messages=_messages(), now=now)

    first_state = service.public_state(
        workspace_id=workspace["id"],
        config=config,
        now=now,
    )
    second_state = service.public_state(
        workspace_id=other_workspace_id,
        config=config,
        now=now,
    )
    assert first_state["generation"] == 1
    assert second_state["generation"] == 0
    assert second_state["source"] == "builtin"
    assert owner["id"] != other_owner["id"]


def test_expired_generation_lease_can_be_reclaimed(tmp_path, monkeypatch):
    store, _workspace, _owner = _store(tmp_path, monkeypatch)
    current = datetime(2026, 7, 29, tzinfo=timezone.utc)
    config = _config()
    first = FeedEndMessagesService(store).claim_due(
        config=config,
        worker_id="worker-one",
        now=current,
    )
    assert first is not None

    other_store = ServiceStore(tmp_path)
    other_store.initialize()
    reclaimed = FeedEndMessagesService(other_store).claim_due(
        config=config,
        worker_id="worker-two",
        now=current + timedelta(seconds=76),
    )

    assert reclaimed is not None
    assert reclaimed["claim_token"] != first["claim_token"]


class _FakeClient:
    def __init__(self, response: str):
        self.response = response
        self.calls = 0

    async def complete(self, *_args, **_kwargs):
        self.calls += 1
        return self.response


def test_due_generation_makes_one_metered_model_call(tmp_path, monkeypatch):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    (tmp_path / "config.json").write_text(
        json.dumps(_config_data(), ensure_ascii=False),
        encoding="utf-8",
    )
    fake = _FakeClient(json.dumps(_messages(), ensure_ascii=False))

    result = run_due_feed_end_messages_generation(
        data_dir=str(tmp_path),
        store=store,
        worker_id="copy-worker",
        client_factory=lambda _config: fake,
        now=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )

    assert result == {
        "ok": True,
        "job_type": "feed_end_messages_generation",
        "workspace_id": workspace["id"],
        "message_count": 3,
    }
    assert fake.calls == 1
    usage = store.connect().execute(
        """
        SELECT event_type, provider, quantity
        FROM usage_events
        WHERE workspace_id = ? AND user_id = ?
        """,
        (workspace["id"], owner["id"]),
    ).fetchall()
    assert [tuple(row) for row in usage] == [("ai_attempt", "openai", 1)]


def test_due_generation_uses_bound_ai_key_env_and_base_url(tmp_path, monkeypatch):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    data = _config_data()
    data["feed_end_messages"]["ai_key_env"] = "DEEPSEEK_API_KEY"
    data["feed_end_messages"]["model"] = "copy-model"
    (tmp_path / "config.json").write_text(
        json.dumps(data, ensure_ascii=False),
        encoding="utf-8",
    )
    fake = _FakeClient(json.dumps(_messages(), ensure_ascii=False))
    seen_key_envs: list[str] = []
    seen_base_urls: list[str | None] = []
    seen_models: list[str] = []

    store.create_secret_ref(
        workspace_id=workspace["id"],
        owner_user_id=owner["id"],
        name="OpenAI copy Key",
        env_name="DEEPSEEK_API_KEY",
        kind="ai",
        provider="openai",
        base_url="https://copy.example.test/v1",
    )

    def factory(ai_config):
        seen_key_envs.append(ai_config.api_key_env)
        seen_base_urls.append(ai_config.base_url)
        seen_models.append(ai_config.model)
        return fake

    result = run_due_feed_end_messages_generation(
        data_dir=str(tmp_path),
        store=store,
        worker_id="copy-worker",
        client_factory=factory,
        now=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )

    assert result["ok"] is True
    assert seen_key_envs == ["DEEPSEEK_API_KEY"]
    assert seen_base_urls == ["https://copy.example.test/v1"]
    assert seen_models == ["copy-model"]


def test_due_generation_uses_provider_default_when_bound_key_has_no_url(
    tmp_path, monkeypatch
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    data = _config_data()
    data["ai"]["base_url"] = "https://workspace-key.example.test/v1"
    data["feed_end_messages"]["ai_key_env"] = "OPENAI_COPY_DEFAULT_KEY"
    (tmp_path / "config.json").write_text(
        json.dumps(data, ensure_ascii=False),
        encoding="utf-8",
    )
    fake = _FakeClient(json.dumps(_messages(), ensure_ascii=False))
    seen_base_urls: list[str | None] = []
    store.create_secret_ref(
        workspace_id=workspace["id"],
        owner_user_id=owner["id"],
        name="OpenAI provider default Key",
        env_name="OPENAI_COPY_DEFAULT_KEY",
        kind="ai",
        provider="openai",
    )

    result = run_due_feed_end_messages_generation(
        data_dir=str(tmp_path),
        store=store,
        worker_id="copy-worker",
        client_factory=lambda ai_config: (
            seen_base_urls.append(ai_config.base_url) or fake
        ),
        now=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )

    assert result["ok"] is True
    assert seen_base_urls == [None]


def test_due_generation_uses_bound_key_provider_without_global_fallback(
    tmp_path, monkeypatch
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    data = _config_data()
    data["feed_end_messages"]["ai_key_env"] = "GOOGLE_API_KEY_2"
    (tmp_path / "config.json").write_text(
        json.dumps(data, ensure_ascii=False),
        encoding="utf-8",
    )
    store.create_secret_ref(
        workspace_id=workspace["id"],
        owner_user_id=owner["id"],
        name="Gemini secondary",
        env_name="GOOGLE_API_KEY_2",
        kind="ai",
        provider="gemini",
    )
    fake = _FakeClient(json.dumps(_messages(), ensure_ascii=False))
    seen_key_envs: list[str] = []
    seen_providers: list[str] = []

    def factory(ai_config):
        seen_key_envs.append(ai_config.api_key_env)
        seen_providers.append(ai_config.provider.value)
        return fake

    result = run_due_feed_end_messages_generation(
        data_dir=str(tmp_path),
        store=store,
        worker_id="copy-worker",
        client_factory=factory,
        now=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )

    assert result["ok"] is True
    assert seen_key_envs == ["GOOGLE_API_KEY_2"]
    assert seen_providers == ["gemini"]


def test_due_generation_with_direct_key_does_not_require_workspace_ai_enabled(
    tmp_path, monkeypatch
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    data = _config_data(ai_enabled=False)
    data["feed_end_messages"].update(
        {"ai_key_env": "GEMINI_COPY_KEY", "model": "gemini-2.5-flash"}
    )
    (tmp_path / "config.json").write_text(json.dumps(data), encoding="utf-8")
    store.create_secret_ref(
        workspace_id=workspace["id"],
        owner_user_id=owner["id"],
        name="Gemini copy",
        env_name="GEMINI_COPY_KEY",
        kind="ai",
        provider="gemini",
    )
    seen: list[tuple[str, str]] = []
    fake = _FakeClient(json.dumps(_messages(), ensure_ascii=False))

    result = run_due_feed_end_messages_generation(
        data_dir=str(tmp_path),
        store=store,
        worker_id="copy-worker",
        client_factory=lambda ai_config: (seen.append((ai_config.provider.value, ai_config.model)) or fake),
        now=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )

    assert result["ok"] is True
    assert seen == [("gemini", "gemini-2.5-flash")]


def test_due_generation_without_binding_falls_back_to_global_key(tmp_path, monkeypatch):
    store, workspace, _owner = _store(tmp_path, monkeypatch)
    (tmp_path / "config.json").write_text(
        json.dumps(_config_data(), ensure_ascii=False),
        encoding="utf-8",
    )
    fake = _FakeClient(json.dumps(_messages(), ensure_ascii=False))
    seen_key_envs: list[str] = []

    def factory(ai_config):
        seen_key_envs.append(ai_config.api_key_env)
        return fake

    result = run_due_feed_end_messages_generation(
        data_dir=str(tmp_path),
        store=store,
        worker_id="copy-worker",
        client_factory=factory,
        now=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )

    assert result["ok"] is True
    assert seen_key_envs == ["OPENAI_API_KEY"]


def test_due_generation_times_out_once_and_schedules_six_hour_retry(
    tmp_path, monkeypatch
):
    store, workspace, _owner = _store(tmp_path, monkeypatch)
    current = datetime(2026, 7, 29, tzinfo=timezone.utc)
    (tmp_path / "config.json").write_text(
        json.dumps(_config_data(), ensure_ascii=False),
        encoding="utf-8",
    )

    class SlowClient:
        calls = 0

        async def complete(self, *_args, **_kwargs):
            self.calls += 1
            await asyncio.sleep(1)
            return ""

    fake = SlowClient()
    monkeypatch.setattr(
        "src.services.feed_end_messages.FEED_END_MESSAGE_TIMEOUT_SECONDS",
        0.01,
    )

    result = run_due_feed_end_messages_generation(
        data_dir=str(tmp_path),
        store=store,
        worker_id="copy-worker",
        client_factory=lambda _config: fake,
        now=current,
    )
    state = FeedEndMessagesService(store).public_state(
        workspace_id=workspace["id"],
        config=_config(),
        now=current,
    )

    assert result["error_code"] == "feed_end_messages_timeout"
    assert fake.calls == 1
    assert datetime.fromisoformat(state["retry_at"]) == current + timedelta(hours=6)


def test_feed_end_generation_client_disables_sdk_retries(monkeypatch):
    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    monkeypatch.setattr("src.ai.client.AsyncOpenAI", FakeOpenAI)

    client = create_ai_client(
        _config().ai,
        single_attempt=True,
        timeout_seconds=60,
    )

    assert isinstance(client, OpenAIClient)
    assert captured["max_retries"] == 0
    assert captured["timeout"] == 60
    assert client._allow_compatibility_fallback is False


def test_worker_only_checks_generation_after_normal_queue_is_empty(
    tmp_path, monkeypatch
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Priority Feed",
        config={"name": "Priority Feed", "url": "https://example.com/feed.xml"},
    )
    JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        job_type="source_test",
        payload={},
    )
    generation_calls = []
    monkeypatch.setattr(
        "src.services.worker.run_due_feed_end_messages_generation",
        lambda **kwargs: generation_calls.append(kwargs) or {"ok": True},
    )
    monkeypatch.setattr(
        "src.services.worker.run_source_test",
        lambda payload: {"ok": True, "source_type": payload["source_type"]},
    )

    job_result = run_worker_once(
        data_dir=str(tmp_path),
        worker_id="priority-worker",
        enqueue_schedules=False,
    )
    assert job_result["job_type"] == "source_test"
    assert generation_calls == []

    idle_result = run_worker_once(
        data_dir=str(tmp_path),
        worker_id="priority-worker",
        enqueue_schedules=False,
    )
    assert idle_result == {"ok": True}
    assert len(generation_calls) == 1


def test_feed_end_messages_api_envelope_permissions_and_idempotent_refresh(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "test-session-secret")
    data_dir = tmp_path / "data"
    static_dir = tmp_path / "static"
    data_dir.mkdir()
    static_dir.mkdir()
    (data_dir / "config.json").write_text(
        json.dumps(_config_data(), ensure_ascii=False),
        encoding="utf-8",
    )
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    client = TestClient(create_app(data_dir=data_dir, static_dir=static_dir))

    assert client.get("/api/feed/end-messages").status_code == 401
    assert client.post("/api/auth/login", json={
        "username": "owner",
        "password": "secret-password",
    }).status_code == 200

    state = client.get("/api/feed/end-messages")
    assert state.status_code == 200
    assert state.headers["cache-control"] == "no-store"
    assert state.json()["data"]["status"] == "pending"
    first = client.post("/api/admin/feed-end-messages/refresh")
    second = client.post("/api/admin/feed-end-messages/refresh")
    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["generation"] == second.json()["data"]["generation"] == 0
    assert first.json()["data"]["status"] == second.json()["data"]["status"] == "pending"

    created = client.post(
        "/api/users",
        json={
            "username": "member",
            "password": "member-password",
            "role": "member",
        },
    )
    assert created.status_code == 200
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={
        "username": "member",
        "password": "member-password",
    }).status_code == 200
    assert client.get("/api/feed/end-messages").status_code == 200
    forbidden = client.post("/api/admin/feed-end-messages/refresh")
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "forbidden"


def test_feed_end_messages_refresh_fails_closed_while_disabled(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "test-session-secret")
    data_dir = tmp_path / "data"
    static_dir = tmp_path / "static"
    data_dir.mkdir()
    static_dir.mkdir()
    (data_dir / "config.json").write_text(
        json.dumps(_config_data(generator_enabled=False)),
        encoding="utf-8",
    )
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    client = TestClient(create_app(data_dir=data_dir, static_dir=static_dir))
    client.post("/api/auth/login", json={
        "username": "owner",
        "password": "secret-password",
    })

    response = client.post("/api/admin/feed-end-messages/refresh")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "feed_end_messages_disabled"
