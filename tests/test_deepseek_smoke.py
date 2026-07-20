from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import scripts.deepseek_analysis_smoke as deepseek_smoke
from src.ai.client import OpenAIClient
from src.models import ContentItem, SourceType
from src.services.user_feed_store import UserFeedStore
from src.services.user_content_store import UserContentStore
from src.storage.service_store import ServiceStore


class FakeClient:
    provider = "deepseek"

    def __init__(self, response: str | None = None):
        self.calls = 0
        self.complete_loop = None
        self.response = response or json.dumps(
            {
                "score": 8.0,
                "summary_zh": "一次调用完成",
                "channel": "AI",
                "topics": [],
            }
        )

    async def complete(self, **_kwargs):
        self.calls += 1
        self.complete_loop = asyncio.get_running_loop()
        return self.response


class OpenAITransportProbe:
    """Local SDK-shaped transport used with the real OpenAIClient.complete()."""

    def __init__(self, *, failure_mode: str):
        self.failure_mode = failure_mode
        self.requests = []
        self.options = []
        self.models = SimpleNamespace(list=self.list_models)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def with_options(self, **kwargs):
        self.options.append(kwargs)
        return self

    async def list_models(self):
        return SimpleNamespace(data=[SimpleNamespace(id=deepseek_smoke.MODEL)])

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        if (
            self.failure_mode == "reject_temperature" and "temperature" in kwargs
        ) or (self.failure_mode == "fail_first" and len(self.requests) == 1):
            raise RuntimeError("Unsupported parameter: temperature")
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "score": 8.0,
                                "summary_zh": "一次调用完成",
                                "channel": "AI",
                                "topics": [],
                            }
                        )
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0),
        )


def _real_openai_client_with_probe(*, failure_mode: str):
    probe = OpenAITransportProbe(failure_mode=failure_mode)
    client = OpenAIClient.__new__(OpenAIClient)
    client.client = probe
    client.model = deepseek_smoke.MODEL
    client.temperature = 0.0
    client.max_tokens = 384
    client.provider = "deepseek"
    client._supports_temperature = True
    return client, probe


@pytest.fixture
def captured_article(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    item = ContentItem(
        id="rss:smoke:1",
        source_type=SourceType.RSS,
        title="Smoke",
        url="https://example.com/smoke",
        content="captured body",
        published_at=datetime.now(timezone.utc),
    )
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="smoke-item",
        payload={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "items": [
                {
                    "id": item.id,
                    "title": item.title,
                    "url": str(item.url),
                    "summary_zh": "old",
                }
            ],
        },
    )
    UserContentStore(store).upsert_captured_items(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        items=[item],
    )
    store.connect().commit()
    store.close()
    return tmp_path, item


def test_preflight_success_makes_exactly_one_call_in_same_loop_and_returns_safe_summary(
    captured_article,
):
    data_dir, item = captured_article
    fake = FakeClient()
    preflight_calls = []

    async def allow_target_model(client, model):
        preflight_calls.append((client, model, asyncio.get_running_loop()))

    report = deepseek_smoke.run_smoke(
        data_dir=data_dir,
        article_id=item.id,
        client_factory=lambda _config: fake,
        model_preflight=allow_target_model,
    )

    assert len(preflight_calls) == 1
    assert preflight_calls[0][:2] == (fake, deepseek_smoke.MODEL)
    assert preflight_calls[0][2] is fake.complete_loop
    assert fake.calls == 1
    assert report == {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "input_tokens": 0,
        "output_tokens": 0,
        "status": "succeeded",
    }
    assert "captured body" not in json.dumps(report)


def test_preflight_failure_raises_before_completion(captured_article):
    data_dir, item = captured_article
    fake = FakeClient()

    async def reject_preflight(_client, _model):
        raise ConnectionError("preflight failed")

    with pytest.raises(ConnectionError, match="preflight failed"):
        deepseek_smoke.run_smoke(
            data_dir=data_dir,
            article_id=item.id,
            client_factory=lambda _config: fake,
            model_preflight=reject_preflight,
        )

    assert fake.calls == 0


def test_default_preflight_rejects_when_target_model_is_absent(captured_article):
    data_dir, item = captured_article
    fake = FakeClient()

    class FakeModels:
        async def list(self):
            return SimpleNamespace(data=[SimpleNamespace(id="deepseek-chat")])

    fake.client = SimpleNamespace(models=FakeModels())

    with pytest.raises(LookupError, match="deepseek-v4-flash"):
        deepseek_smoke.run_smoke(
            data_dir=data_dir,
            article_id=item.id,
            client_factory=lambda _config: fake,
        )

    assert fake.calls == 0


def test_default_preflight_requires_model_list_capability(captured_article):
    data_dir, item = captured_article
    fake = FakeClient()

    with pytest.raises(RuntimeError, match="models.list"):
        deepseek_smoke.run_smoke(
            data_dir=data_dir,
            article_id=item.id,
            client_factory=lambda _config: fake,
        )

    assert fake.calls == 0


def test_production_client_is_bounded_before_preflight_and_completion(
    captured_article, monkeypatch
):
    data_dir, item = captured_article
    events = []
    options = []
    configs = []
    model_list_loop = None

    class ConfiguredModels:
        async def list(self):
            nonlocal model_list_loop
            events.append("models.list")
            model_list_loop = asyncio.get_running_loop()
            return SimpleNamespace(
                data=[SimpleNamespace(id=deepseek_smoke.MODEL)]
            )

    configured_raw_client = SimpleNamespace(models=ConfiguredModels())

    class InitialRawClient:
        def with_options(self, **kwargs):
            events.append("with_options")
            options.append(kwargs)
            return configured_raw_client

    fake = FakeClient()
    fake._supports_temperature = True
    fake.client = InitialRawClient()
    original_complete = fake.complete

    async def complete_with_configured_client(**kwargs):
        assert fake.client is configured_raw_client
        events.append("complete")
        return await original_complete(**kwargs)

    fake.complete = complete_with_configured_client

    def load_secret_store(_self):
        events.append("load_secret_store")
        return set()

    def create_client(config):
        events.append("create_client")
        configs.append(config)
        return fake

    monkeypatch.setattr(
        deepseek_smoke.SecretStore, "load_into_environ", load_secret_store
    )
    monkeypatch.setattr(deepseek_smoke, "create_ai_client", create_client)

    report = deepseek_smoke.run_smoke(data_dir=data_dir, article_id=item.id)

    assert report["status"] == "succeeded"
    assert events == [
        "load_secret_store",
        "create_client",
        "with_options",
        "models.list",
        "complete",
    ]
    assert len(configs) == 1
    assert configs[0].model == "deepseek-v4-flash"
    assert configs[0].base_url == "https://api.deepseek.com"
    assert options == [{"max_retries": 0, "timeout": 10.0}]
    assert model_list_loop is fake.complete_loop
    assert fake.calls == 1


def test_production_smoke_omits_temperature_and_avoids_application_fallback(
    captured_article, monkeypatch
):
    data_dir, item = captured_article
    client, probe = _real_openai_client_with_probe(
        failure_mode="reject_temperature"
    )
    monkeypatch.setattr(
        deepseek_smoke.SecretStore, "load_into_environ", lambda _self: set()
    )
    monkeypatch.setattr(deepseek_smoke, "create_ai_client", lambda _config: client)

    report = deepseek_smoke.run_smoke(data_dir=data_dir, article_id=item.id)

    assert report["status"] == "succeeded"
    assert probe.options == [{"max_retries": 0, "timeout": 10.0}]
    assert len(probe.requests) == 1
    assert "temperature" not in probe.requests[0]


def test_production_smoke_does_not_retry_a_recognized_first_request_failure(
    captured_article, monkeypatch
):
    data_dir, item = captured_article
    client, probe = _real_openai_client_with_probe(failure_mode="fail_first")
    monkeypatch.setattr(
        deepseek_smoke.SecretStore, "load_into_environ", lambda _self: set()
    )
    monkeypatch.setattr(deepseek_smoke, "create_ai_client", lambda _config: client)

    with pytest.raises(RuntimeError, match="Unsupported parameter: temperature"):
        deepseek_smoke.run_smoke(data_dir=data_dir, article_id=item.id)

    assert len(probe.requests) == 1
    assert "temperature" not in probe.requests[0]


def test_production_smoke_fails_before_preflight_without_temperature_capability(
    captured_article, monkeypatch
):
    data_dir, item = captured_article
    events = []
    fake = FakeClient()

    class Models:
        async def list(self):
            events.append("models.list")
            return SimpleNamespace(data=[SimpleNamespace(id=deepseek_smoke.MODEL)])

    class RawClient:
        def with_options(self, **_kwargs):
            events.append("with_options")
            return SimpleNamespace(models=Models())

    fake.client = RawClient()
    monkeypatch.setattr(
        deepseek_smoke.SecretStore, "load_into_environ", lambda _self: set()
    )
    monkeypatch.setattr(deepseek_smoke, "create_ai_client", lambda _config: fake)

    with pytest.raises(RuntimeError, match="temperature"):
        deepseek_smoke.run_smoke(data_dir=data_dir, article_id=item.id)

    assert events == []
    assert fake.calls == 0


def test_missing_key_failure_from_client_construction_prevents_completion(
    captured_article, monkeypatch
):
    data_dir, item = captured_article
    events = []

    def load_secret_store(_self):
        events.append("load_secret_store")
        return set()

    def reject_missing_key(_config):
        events.append("create_client")
        raise ValueError("missing API key")

    monkeypatch.setattr(
        deepseek_smoke.SecretStore, "load_into_environ", load_secret_store
    )
    monkeypatch.setattr(deepseek_smoke, "create_ai_client", reject_missing_key)

    with pytest.raises(ValueError, match="missing API key"):
        deepseek_smoke.run_smoke(data_dir=data_dir, article_id=item.id)

    assert events == ["load_secret_store", "create_client"]


def test_malformed_completion_json_fails_after_exactly_one_call(captured_article):
    data_dir, item = captured_article
    fake = FakeClient(response="not-json")

    async def allow_target_model(_client, _model):
        return None

    with pytest.raises(ValueError, match="JSON contract"):
        deepseek_smoke.run_smoke(
            data_dir=data_dir,
            article_id=item.id,
            client_factory=lambda _config: fake,
            model_preflight=allow_target_model,
        )

    assert fake.calls == 1


@pytest.mark.parametrize("succeeds", [True, False])
def test_main_prints_only_safe_report_keys(succeeds, monkeypatch, capsys):
    safe_report = {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "input_tokens": 0,
        "output_tokens": 0,
        "status": "succeeded",
    }

    if succeeds:
        monkeypatch.setattr(deepseek_smoke, "run_smoke", lambda **_kwargs: safe_report)
    else:
        def fail_with_sensitive_details(**_kwargs):
            raise RuntimeError("secret response body")

        monkeypatch.setattr(deepseek_smoke, "run_smoke", fail_with_sensitive_details)

    monkeypatch.setattr(
        sys,
        "argv",
        ["deepseek_analysis_smoke.py", "--article-id", "rss:smoke:1"],
    )

    if succeeds:
        deepseek_smoke.main()
    else:
        with pytest.raises(SystemExit) as exc_info:
            deepseek_smoke.main()
        assert exc_info.value.code == 1

    output = capsys.readouterr().out.strip()
    payload = json.loads(output)
    assert set(payload) == {
        "provider",
        "model",
        "input_tokens",
        "output_tokens",
        "status",
    }
    assert "secret response body" not in output
