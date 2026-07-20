import asyncio

from src.ai.client import GeminiClient
from src.models import AIConfig, AIProvider


class _Response:
    text = '{"ok": true}'
    usage_metadata = None


class _Models:
    def __init__(self):
        self.calls = []

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return _Response()


class _Client:
    def __init__(self, **_kwargs):
        self.aio = type("Aio", (), {"models": _Models()})()


def test_gemini_disables_thinking_so_output_budget_is_reserved_for_json(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setattr("src.ai.client.genai.Client", _Client)
    config = AIConfig(
        enabled=True,
        provider=AIProvider.GEMINI,
        model="gemini-2.5-flash",
        api_key_env="GOOGLE_API_KEY",
    )
    client = GeminiClient(config)

    result = asyncio.run(
        client.complete(system="Return JSON", user="Hello", max_tokens=800)
    )

    assert result == '{"ok": true}'
    request_config = client.client.aio.models.calls[0]["config"]
    assert request_config.max_output_tokens == 800
    assert request_config.response_mime_type == "application/json"
    assert request_config.thinking_config.thinking_budget == 0
