import pytest

from src.mcp.remote_config import OpenClawChatSettings, RemoteMCPSettings


def test_remote_mcp_is_disabled_by_default_without_a_public_url(monkeypatch):
    monkeypatch.delenv("HORIZON_REMOTE_MCP_ENABLED", raising=False)
    monkeypatch.delenv("HORIZON_REMOTE_MCP_PUBLIC_URL", raising=False)
    monkeypatch.delenv(
        "HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED", raising=False
    )

    assert RemoteMCPSettings.from_env() == RemoteMCPSettings(
        enabled=False,
        public_url="",
        subscription_writes_enabled=False,
    )


@pytest.mark.parametrize(
    "public_url",
    [
        "",
        "https://rb.jiefs.top/mcp/",
        "https://rb.jiefs.top/not-mcp",
        "https://rb.jiefs.top/mcp?token=bad",
        "https://user:password@rb.jiefs.top/mcp",
        "http://rb.jiefs.top/mcp",
    ],
)
def test_enabled_remote_mcp_rejects_missing_or_unsafe_public_urls(
    monkeypatch,
    public_url,
):
    monkeypatch.setenv("HORIZON_REMOTE_MCP_ENABLED", "true")
    monkeypatch.setenv("HORIZON_REMOTE_MCP_PUBLIC_URL", public_url)

    with pytest.raises(ValueError):
        RemoteMCPSettings.from_env()


def test_remote_mcp_derives_host_and_origin_from_valid_urls(monkeypatch):
    monkeypatch.setenv("HORIZON_REMOTE_MCP_ENABLED", "true")
    monkeypatch.setenv(
        "HORIZON_REMOTE_MCP_PUBLIC_URL",
        "https://rb.jiefs.top/mcp",
    )

    settings = RemoteMCPSettings.from_env()

    assert settings.host == "rb.jiefs.top"
    assert settings.origin == "https://rb.jiefs.top"

    monkeypatch.setenv(
        "HORIZON_REMOTE_MCP_PUBLIC_URL",
        "http://127.0.0.1:8080/mcp",
    )
    local = RemoteMCPSettings.from_env()
    assert local.host == "127.0.0.1:8080"
    assert local.origin == "http://127.0.0.1:8080"


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("HORIZON_REMOTE_MCP_ENABLED", "TRUE"),
        ("HORIZON_REMOTE_MCP_ENABLED", " true"),
        ("HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED", "1"),
        ("HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED", "False"),
    ],
)
def test_remote_mcp_boolean_flags_accept_only_exact_true_or_false(
    monkeypatch, variable, value
):
    monkeypatch.setenv("HORIZON_REMOTE_MCP_ENABLED", "false")
    monkeypatch.setenv("HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED", "false")
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValueError, match=f"{variable} must be true or false"):
        RemoteMCPSettings.from_env()


def test_subscription_writes_require_remote_mcp_to_be_enabled(monkeypatch):
    monkeypatch.setenv("HORIZON_REMOTE_MCP_ENABLED", "false")
    monkeypatch.setenv("HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED", "true")
    monkeypatch.delenv("HORIZON_REMOTE_MCP_PUBLIC_URL", raising=False)

    with pytest.raises(
        ValueError,
        match="subscription writes require Remote MCP to be enabled",
    ):
        RemoteMCPSettings.from_env()


def test_subscription_writes_are_exposed_when_both_flags_are_enabled(monkeypatch):
    monkeypatch.setenv("HORIZON_REMOTE_MCP_ENABLED", "true")
    monkeypatch.setenv("HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED", "true")
    monkeypatch.setenv(
        "HORIZON_REMOTE_MCP_PUBLIC_URL", "http://127.0.0.1:8080/mcp"
    )

    settings = RemoteMCPSettings.from_env()

    assert settings.subscription_writes_enabled is True


def test_openclaw_chat_is_disabled_with_a_safe_local_default(monkeypatch):
    monkeypatch.delenv("HORIZON_OPENCLAW_CHAT_ENABLED", raising=False)
    monkeypatch.delenv("HORIZON_OPENCLAW_GATEWAY_DEFAULT_URL", raising=False)

    assert OpenClawChatSettings.from_env() == OpenClawChatSettings(
        enabled=False,
        default_gateway_url="ws://127.0.0.1:18789",
        image_io_enabled=False,
        media_origins=(),
        protocol_version=4,
        target_version="2026.7.1",
    )


@pytest.mark.parametrize(
    "gateway_url",
    [
        "http://127.0.0.1:18789",
        "ws://192.168.1.20:18789",
        "ws://[::1]:18789",
        "ws://gateway.example.com",
        "wss://user:password@gateway.example.com",
        "wss://gateway.example.com/path?token=bad",
        "wss://gateway.example.com/path#token=bad",
    ],
)
def test_openclaw_chat_rejects_unsafe_gateway_defaults(monkeypatch, gateway_url):
    monkeypatch.setenv("HORIZON_OPENCLAW_CHAT_ENABLED", "true")
    monkeypatch.setenv("HORIZON_OPENCLAW_GATEWAY_DEFAULT_URL", gateway_url)

    with pytest.raises(ValueError):
        OpenClawChatSettings.from_env()


@pytest.mark.parametrize(
    "gateway_url",
    [
        "ws://localhost:18789",
        "wss://gateway.example.com",
        "wss://gateway.example.com/openclaw/ws",
    ],
)
def test_openclaw_chat_accepts_loopback_ws_and_remote_wss(monkeypatch, gateway_url):
    monkeypatch.setenv("HORIZON_OPENCLAW_CHAT_ENABLED", "true")
    monkeypatch.setenv("HORIZON_OPENCLAW_GATEWAY_DEFAULT_URL", gateway_url)

    settings = OpenClawChatSettings.from_env()

    assert settings.enabled is True
    assert settings.default_gateway_url == gateway_url


def test_openclaw_image_io_requires_safe_explicit_media_origins(monkeypatch):
    monkeypatch.setenv("HORIZON_OPENCLAW_IMAGE_IO_ENABLED", "true")
    monkeypatch.delenv("HORIZON_OPENCLAW_MEDIA_ORIGINS", raising=False)

    with pytest.raises(ValueError, match="MEDIA_ORIGINS is required"):
        OpenClawChatSettings.from_env()

    monkeypatch.setenv(
        "HORIZON_OPENCLAW_MEDIA_ORIGINS",
        "http://127.0.0.1:18789,https://openclaw.example.com",
    )
    settings = OpenClawChatSettings.from_env()

    assert settings.image_io_enabled is True
    assert settings.media_origins == (
        "http://127.0.0.1:18789",
        "https://openclaw.example.com",
    )


@pytest.mark.parametrize(
    "origin",
    [
        "http://gateway.example.com",
        "https://user:pass@gateway.example.com",
        "https://gateway.example.com/path",
        "https://gateway.example.com?ticket=bad",
    ],
)
def test_openclaw_image_io_rejects_unsafe_media_origins(monkeypatch, origin):
    monkeypatch.setenv("HORIZON_OPENCLAW_IMAGE_IO_ENABLED", "true")
    monkeypatch.setenv("HORIZON_OPENCLAW_MEDIA_ORIGINS", origin)

    with pytest.raises(ValueError):
        OpenClawChatSettings.from_env()
