from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

import pytest

from scripts import openclaw_setup_workflow, setup_openclaw_local
from scripts.setup_openclaw_local import (
    FULL_TOOL_FILTER,
    LEGACY_FULL_TOOL_FILTER,
    LEGACY_READ_TOOL_FILTER,
    MANAGED_COMMENT,
    READ_TOOL_FILTER,
    SetupError,
    compose_image_from_ps,
    default_origin,
    merge_allowed_origins,
    parse_gateway_status,
    skill_tree_matches,
    standard_tool_filter_upgrade,
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


def test_wrapper_is_executable_and_routes_to_python_entrypoint(tmp_path: Path) -> None:
    wrapper = ROOT / "scripts" / "setup_openclaw_local.sh"

    assert wrapper.stat().st_mode & 0o111
    assert "setup_openclaw_local.py" in wrapper.read_text(encoding="utf-8")
    result = subprocess.run(
        [str(wrapper), "--help"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--dry-run" in result.stdout


def test_managed_values_do_not_enable_subscription_writes() -> None:
    source = (ROOT / "scripts" / "openclaw_setup_env.py").read_text(encoding="utf-8")

    assert '("HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED", "false")' in source
    assert "INTELISCOPE_MCP_TOKEN" not in json.dumps(source)


def test_skill_tree_matches_ignores_install_metadata_and_detects_drift(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    installed = tmp_path / "installed"
    (source / "references").mkdir(parents=True)
    (installed / "references").mkdir(parents=True)
    (installed / ".openclaw").mkdir()
    (source / "SKILL.md").write_text("current\n", encoding="utf-8")
    (installed / "SKILL.md").write_text("current\n", encoding="utf-8")
    (source / "references" / "workflow.md").write_text("safe\n", encoding="utf-8")
    (installed / "references" / "workflow.md").write_text("safe\n", encoding="utf-8")
    (installed / ".openclaw" / "source-origin.json").write_text(
        "{}\n",
        encoding="utf-8",
    )

    assert skill_tree_matches(source, installed) is True

    (installed / "SKILL.md").write_text("stale\n", encoding="utf-8")

    assert skill_tree_matches(source, installed) is False


def test_setup_refreshes_a_stale_installed_skill_and_restarts_gateway(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    origin = "http://127.0.0.1:8080"
    gateway_url = "ws://127.0.0.1:18789"
    (tmp_path / ".env").write_text(
        "\n".join(
            (
                "HORIZON_REMOTE_MCP_ENABLED=true",
                f"HORIZON_REMOTE_MCP_PUBLIC_URL={origin}/mcp",
                "HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED=false",
                "HORIZON_OPENCLAW_CHAT_ENABLED=true",
                f"HORIZON_OPENCLAW_GATEWAY_DEFAULT_URL={gateway_url}",
                "",
            )
        ),
        encoding="utf-8",
    )
    skill_dir = tmp_path / "integrations" / "openclaw" / "inteliscope"
    installed_dir = tmp_path / "installed-skill"
    skill_dir.mkdir(parents=True)
    installed_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("current\n", encoding="utf-8")
    (installed_dir / "SKILL.md").write_text("stale\n", encoding="utf-8")

    gateway_status = {
        "cli": {"version": "2026.7.1"},
        "service": {"runtime": {"status": "running"}},
        "gateway": {"probeUrl": gateway_url},
    }
    executed: list[list[str]] = []

    class FakeRunner:
        def __init__(self, *, cwd: Path, dry_run: bool = False) -> None:
            assert cwd == tmp_path
            assert dry_run is False

        def capture(
            self,
            argv: list[str],
            *,
            check: bool = True,
            env_override: dict[str, str] | None = None,
        ) -> subprocess.CompletedProcess[str]:
            del check, env_override
            if argv[:3] == ["openclaw", "gateway", "status"]:
                return subprocess.CompletedProcess(argv, 0, json.dumps(gateway_status), "")
            if argv[:4] == ["openclaw", "config", "get", "gateway.controlUi.allowedOrigins"]:
                return subprocess.CompletedProcess(argv, 0, json.dumps([origin]), "")
            if argv[:4] == ["openclaw", "mcp", "show", "inteliscope"]:
                return subprocess.CompletedProcess(argv, 1, "", "missing")
            if argv[:4] == ["openclaw", "skills", "info", "inteliscope"]:
                return subprocess.CompletedProcess(
                    argv,
                    0,
                    json.dumps({"baseDir": str(installed_dir)}),
                    "",
                )
            raise AssertionError(f"unexpected capture: {argv}")

        def execute(
            self,
            argv: list[str],
            *,
            env_override: dict[str, str] | None = None,
        ) -> None:
            assert env_override is None
            executed.append(argv)

    monkeypatch.setattr(openclaw_setup_workflow, "CommandRunner", FakeRunner)
    monkeypatch.setattr(openclaw_setup_workflow.shutil, "which", lambda _: "/bin/tool")
    args = argparse.Namespace(
        project_root=str(tmp_path),
        env_file=None,
        dry_run=False,
        gateway_url=None,
        origin=origin,
        skip_service=True,
        rebuild=False,
        skip_skill=False,
        no_open=True,
        timeout=1,
    )

    openclaw_setup_workflow.run_setup(args)

    assert [
        "openclaw",
        "skills",
        "install",
        str(skill_dir),
        "--as",
        "inteliscope",
        "--force",
    ] in executed
    assert ["openclaw", "gateway", "restart"] in executed


def test_main_maps_setup_error_to_stable_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_setup(_: argparse.Namespace) -> None:
        raise SetupError("mocked failure")

    monkeypatch.setattr(setup_openclaw_local, "run_setup", fail_setup)

    assert setup_openclaw_local.main(["--dry-run"]) == 2
    assert "OpenClaw setup failed: mocked failure" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("legacy", "current"),
    [
        (LEGACY_READ_TOOL_FILTER, READ_TOOL_FILTER),
        (LEGACY_FULL_TOOL_FILTER, FULL_TOOL_FILTER),
    ],
)
def test_standard_tool_filter_upgrade_changes_only_known_legacy_sets(
    legacy: tuple[str, ...],
    current: tuple[str, ...],
) -> None:
    assert standard_tool_filter_upgrade(
        {"toolFilter": {"include": list(legacy)}}
    ) == (current, False)
    assert standard_tool_filter_upgrade(
        {"config": {"toolFilter": {"include": list(current)}}}
    ) == (None, False)


def test_standard_tool_filter_upgrade_preserves_custom_filter() -> None:
    custom = ["get_my_feed", "list_subscriptions"]

    assert standard_tool_filter_upgrade(
        {"toolFilter": {"include": custom}}
    ) == (None, True)
    assert standard_tool_filter_upgrade(
        {
            "toolFilter": {
                "include": list(LEGACY_READ_TOOL_FILTER),
                "exclude": ["get_item"],
            }
        }
    ) == (None, True)
    assert standard_tool_filter_upgrade({"name": "inteliscope"}) == (
        None,
        False,
    )
