from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.setup_openclaw_local import (
    MANAGED_COMMENT,
    SetupError,
    compose_image_from_ps,
    default_origin,
    merge_allowed_origins,
    parse_gateway_status,
    update_env_text,
    validate_gateway_url,
    validate_origin,
)


ROOT = Path(__file__).resolve().parents[1]


def test_parse_gateway_status_uses_running_control_ui_socket() -> None:
    payload = {
        "cli": {"version": "2026.7.1"},
        "service": {"runtime": {"status": "running"}},
        "gateway": {
            "probeUrl": "ws://127.0.0.1:18789",
            "controlUiLinks": {"wsUrl": "ws://127.0.0.1:13789"},
        },
    }

    result = parse_gateway_status(payload)

    assert result.cli_version == "2026.7.1"
    assert result.gateway_url == "ws://127.0.0.1:13789"
    assert result.running is True


def test_parse_gateway_status_rejects_incompatible_version() -> None:
    with pytest.raises(SetupError, match="2026.7.1 or newer"):
        parse_gateway_status(
            {
                "cli": {"version": "2026.6.9"},
                "service": {"runtime": {"status": "running"}},
                "gateway": {"probeUrl": "ws://127.0.0.1:18789"},
            }
        )


@pytest.mark.parametrize(
    "value",
    [
        "http://127.0.0.1:18789",
        "ws://example.com:18789",
        "ws://user@example.com:18789",
        "ws://127.0.0.1:18789?token=secret",
    ],
)
def test_validate_gateway_url_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(SetupError):
        validate_gateway_url(value)


def test_validate_origin_accepts_exact_loopback_and_rejects_paths() -> None:
    assert validate_origin("http://127.0.0.1:8080/") == "http://127.0.0.1:8080"
    with pytest.raises(SetupError, match="must not include a path"):
        validate_origin("http://127.0.0.1:8080/agents")
    with pytest.raises(SetupError, match="must use HTTPS"):
        validate_origin("http://inteliscope.example.com")


def test_default_origin_prefers_env_port_and_uses_light_fallback(tmp_path: Path) -> None:
    (tmp_path / "docker-compose.light.yml").write_text("services: {}\n", encoding="utf-8")

    assert default_origin(tmp_path, "HORIZON_WEB_PORT=8080\n") == "http://127.0.0.1:8080"
    assert default_origin(tmp_path, "") == "http://127.0.0.1:8081"


def test_update_env_text_is_idempotent_and_preserves_unmanaged_secrets() -> None:
    original = (
        "HORIZON_AUTH_PASSWORD=do-not-touch\n"
        "HORIZON_OPENCLAW_CHAT_ENABLED=false\n"
        "HORIZON_OPENCLAW_CHAT_ENABLED=false\n"
    )
    updates = {
        "HORIZON_OPENCLAW_CHAT_ENABLED": "true",
        "HORIZON_OPENCLAW_GATEWAY_DEFAULT_URL": "ws://127.0.0.1:13789",
    }

    once = update_env_text(original, updates)
    twice = update_env_text(once, updates)

    assert once == twice
    assert "HORIZON_AUTH_PASSWORD=do-not-touch" in once
    assert once.count("HORIZON_OPENCLAW_CHAT_ENABLED=true") == 1
    assert MANAGED_COMMENT in once
    assert "HORIZON_OPENCLAW_GATEWAY_DEFAULT_URL=ws://127.0.0.1:13789" in once


def test_merge_allowed_origins_preserves_existing_entries_without_duplicates() -> None:
    existing = ["https://private.example.com", "http://127.0.0.1:8080"]

    assert merge_allowed_origins(existing, "http://127.0.0.1:8080") == existing
    assert merge_allowed_origins(existing, "http://localhost:8080") == [*existing, "http://localhost:8080"]
    with pytest.raises(SetupError, match="JSON array"):
        merge_allowed_origins({"unsafe": "shape"}, "http://127.0.0.1:8080")


def test_compose_image_from_ps_reuses_the_running_api_image() -> None:
    record = {
        "Service": "horizon-api",
        "Image": "inteliscope-service:local-current",
        "State": "running",
    }

    assert compose_image_from_ps(json.dumps(record)) == "inteliscope-service:local-current"
    assert compose_image_from_ps("") is None


def test_wrapper_is_executable_and_routes_to_python_entrypoint() -> None:
    wrapper = ROOT / "scripts" / "setup_openclaw_local.sh"

    assert wrapper.stat().st_mode & 0o111
    assert "setup_openclaw_local.py" in wrapper.read_text(encoding="utf-8")


def test_managed_values_do_not_enable_subscription_writes() -> None:
    source = (ROOT / "scripts" / "setup_openclaw_local.py").read_text(encoding="utf-8")

    assert '("HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED", "false")' in source
    assert "INTELISCOPE_MCP_TOKEN" not in json.dumps(source)
