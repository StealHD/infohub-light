import pytest

from src.mcp.remote_config import RemoteMCPSettings


def test_remote_mcp_is_disabled_by_default_without_a_public_url(monkeypatch):
    monkeypatch.delenv("HORIZON_REMOTE_MCP_ENABLED", raising=False)
    monkeypatch.delenv("HORIZON_REMOTE_MCP_PUBLIC_URL", raising=False)

    assert RemoteMCPSettings.from_env() == RemoteMCPSettings(
        enabled=False,
        public_url="",
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
