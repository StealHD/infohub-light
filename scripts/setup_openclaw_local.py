#!/usr/bin/env python3
"""Prepare a local Inteliscope + OpenClaw browser chat and read-only MCP setup."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
TARGET_OPENCLAW_VERSION = (2026, 7, 1)
MANAGED_ENV_VALUES = (
    ("HORIZON_REMOTE_MCP_ENABLED", "true"),
    ("HORIZON_REMOTE_MCP_PUBLIC_URL", "{origin}/mcp"),
    ("HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED", "false"),
    ("HORIZON_OPENCLAW_CHAT_ENABLED", "true"),
    ("HORIZON_OPENCLAW_GATEWAY_DEFAULT_URL", "{gateway_url}"),
)
MANAGED_COMMENT = "# OpenClaw local setup (managed by scripts/setup_openclaw_local.py)"
ENV_ASSIGNMENT = re.compile(r"^\s*(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=")


class SetupError(RuntimeError):
    """Safe, actionable local setup failure."""


@dataclass(frozen=True)
class GatewayInfo:
    cli_version: str
    gateway_url: str
    running: bool


class CommandRunner:
    def __init__(self, *, cwd: Path, dry_run: bool = False) -> None:
        self.cwd = cwd
        self.dry_run = dry_run

    def capture(
        self,
        argv: Sequence[str],
        *,
        check: bool = True,
        env_override: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        process_env = os.environ.copy()
        process_env.update(env_override or {})
        result = subprocess.run(
            list(argv),
            cwd=self.cwd,
            env=process_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            if len(detail) > 1200:
                detail = detail[-1200:]
            raise SetupError(f"command failed: {shlex.join(argv)}\n{detail}")
        return result

    def execute(self, argv: Sequence[str], *, env_override: dict[str, str] | None = None) -> None:
        prefix = " ".join(f"{key}={shlex.quote(value)}" for key, value in (env_override or {}).items())
        print(f"$ {prefix + ' ' if prefix else ''}{shlex.join(argv)}")
        if self.dry_run:
            return
        process_env = os.environ.copy()
        process_env.update(env_override or {})
        try:
            subprocess.run(list(argv), cwd=self.cwd, env=process_env, check=True)
        except subprocess.CalledProcessError as exc:
            raise SetupError(f"command failed with exit code {exc.returncode}: {shlex.join(argv)}") from exc


def _version_tuple(value: str) -> tuple[int, ...]:
    numbers = tuple(int(part) for part in re.findall(r"\d+", value)[:3])
    if len(numbers) < 3:
        raise SetupError(f"cannot parse OpenClaw version: {value!r}")
    return numbers


def validate_gateway_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
        raise SetupError("Gateway URL must use ws:// or wss://.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SetupError("Gateway URL must not contain credentials, query parameters, or fragments.")
    host = parsed.hostname.lower()
    if parsed.scheme == "ws" and host not in {"127.0.0.1", "localhost"}:
        raise SetupError("A plain ws:// Gateway must use 127.0.0.1 or localhost.")
    path = "" if parsed.path in {"", "/"} else parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def validate_origin(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SetupError("Origin must be an absolute http:// or https:// URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SetupError("Origin must not contain credentials, query parameters, or fragments.")
    if parsed.path not in {"", "/"}:
        raise SetupError("Origin must not include a path.")
    if parsed.scheme == "http" and parsed.hostname.lower() not in {"127.0.0.1", "localhost"}:
        raise SetupError("A non-loopback Inteliscope Origin must use HTTPS.")
    return f"{parsed.scheme}://{parsed.netloc}"


def parse_gateway_status(payload: dict[str, Any]) -> GatewayInfo:
    cli = payload.get("cli")
    gateway = payload.get("gateway")
    service = payload.get("service")
    if not isinstance(cli, dict) or not isinstance(gateway, dict):
        raise SetupError("OpenClaw gateway status JSON is missing cli/gateway data.")
    version = str(cli.get("version") or "")
    if _version_tuple(version) < TARGET_OPENCLAW_VERSION:
        required = ".".join(str(part) for part in TARGET_OPENCLAW_VERSION)
        raise SetupError(f"OpenClaw {required} or newer is required; found {version or 'unknown'}.")
    links = gateway.get("controlUiLinks")
    gateway_url = links.get("wsUrl") if isinstance(links, dict) else None
    if not gateway_url:
        gateway_url = gateway.get("probeUrl")
    if not isinstance(gateway_url, str):
        raise SetupError("OpenClaw did not report a Gateway WebSocket URL.")
    runtime = service.get("runtime") if isinstance(service, dict) else None
    running = isinstance(runtime, dict) and runtime.get("status") == "running"
    return GatewayInfo(
        cli_version=version,
        gateway_url=validate_gateway_url(gateway_url),
        running=running,
    )


def parse_env_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = ENV_ASSIGNMENT.match(line)
        if not match:
            continue
        key = match.group("key")
        value = line[match.end() :].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def default_origin(root: Path, env_text: str) -> str:
    values = parse_env_values(env_text)
    fallback_port = "8081" if (root / "docker-compose.light.yml").exists() else "8080"
    port = values.get("HORIZON_WEB_PORT") or fallback_port
    try:
        port_number = int(port)
    except ValueError as exc:
        raise SetupError(f"HORIZON_WEB_PORT must be a port number; found {port!r}.") from exc
    if port_number < 1 or port_number > 65535:
        raise SetupError(f"HORIZON_WEB_PORT is outside 1..65535: {port_number}.")
    return f"http://127.0.0.1:{port_number}"


def merge_allowed_origins(current: Any, origin: str) -> list[str]:
    if current is None:
        entries: list[str] = []
    elif isinstance(current, list) and all(isinstance(item, str) for item in current):
        entries = list(current)
    else:
        raise SetupError("gateway.controlUi.allowedOrigins must be a JSON array of strings.")
    if origin not in entries:
        entries.append(origin)
    return entries


def update_env_text(text: str, updates: dict[str, str]) -> str:
    output: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        match = ENV_ASSIGNMENT.match(line)
        key = match.group("key") if match else None
        if key not in updates:
            output.append(line)
            continue
        if key in seen:
            continue
        output.append(f"{key}={updates[key]}")
        seen.add(key)
    missing = [key for key in updates if key not in seen]
    if missing:
        if output and output[-1].strip():
            output.append("")
        if MANAGED_COMMENT not in output:
            output.append(MANAGED_COMMENT)
        output.extend(f"{key}={updates[key]}" for key in missing)
    return "\n".join(output).rstrip() + "\n"


def write_env_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _json_output(result: subprocess.CompletedProcess[str], label: str) -> Any:
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SetupError(f"{label} did not return valid JSON.") from exc


def skill_tree_matches(source: Path, installed: Path) -> bool:
    """Compare managed Skill content while ignoring OpenClaw install metadata."""

    def managed_files(root: Path) -> dict[Path, bytes] | None:
        if not root.is_dir():
            return None
        files: dict[Path, bytes] = {}
        try:
            for path in root.rglob("*"):
                relative = path.relative_to(root)
                if any(part.startswith(".") for part in relative.parts):
                    continue
                if path.is_symlink():
                    return None
                if path.is_file():
                    files[relative] = path.read_bytes()
        except OSError:
            return None
        return files

    source_files = managed_files(source)
    installed_files = managed_files(installed)
    return source_files is not None and source_files == installed_files


def _compose_file(root: Path) -> Path:
    light = root / "docker-compose.light.yml"
    standard = root / "docker-compose.yml"
    if light.exists():
        return light
    if standard.exists():
        return standard
    raise SetupError("No docker-compose.light.yml or docker-compose.yml was found.")


def compose_image_from_ps(output: str) -> str | None:
    records: list[Any] = []
    stripped = output.strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
        records = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        for line in stripped.splitlines():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SetupError("docker compose ps did not return valid JSON.") from exc
    for record in records:
        if isinstance(record, dict) and record.get("Service") == "horizon-api":
            image = record.get("Image")
            return image if isinstance(image, str) and image else None
    return None


def _resolve_compose_image(
    runner: CommandRunner,
    compose: Path,
    env_values: dict[str, str],
) -> str:
    ps_result = runner.capture(
        ["docker", "compose", "-f", str(compose), "ps", "--format", "json", "horizon-api"],
        check=False,
    )
    current = compose_image_from_ps(ps_result.stdout) if ps_result.returncode == 0 else None
    candidate = current or env_values.get("INTELISCOPE_IMAGE") or "inteliscope-service:local"
    inspect = runner.capture(["docker", "image", "inspect", candidate], check=False)
    if inspect.returncode != 0:
        raise SetupError(
            f"Docker image {candidate!r} is not available. Re-run with --rebuild to build the current workspace."
        )
    return candidate


def _wait_for_ready(url: str, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = "no response"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if response.status == 200 and payload.get("ok") is True:
                    return
                last_error = f"unexpected readiness payload: {payload!r}"
        except (OSError, ValueError, urllib.error.HTTPError) as exc:
            last_error = str(exc)
        time.sleep(2)
    raise SetupError(f"Inteliscope readiness did not pass within {timeout_seconds}s: {last_error}")


def _managed_updates(origin: str, gateway_url: str) -> dict[str, str]:
    return {
        key: template.format(origin=origin, gateway_url=gateway_url)
        for key, template in MANAGED_ENV_VALUES
    }


def run_setup(args: argparse.Namespace) -> None:
    root = Path(args.project_root).expanduser().resolve()
    env_path = Path(args.env_file).expanduser().resolve() if args.env_file else root / ".env"
    if not env_path.exists():
        raise SetupError(
            f"{env_path} does not exist. Create it from .env.example and configure Service login first."
        )
    for command in ("openclaw", "docker"):
        if shutil.which(command) is None:
            raise SetupError(f"required command is not installed: {command}")

    runner = CommandRunner(cwd=root, dry_run=args.dry_run)
    status_result = runner.capture(["openclaw", "gateway", "status", "--json", "--no-probe"])
    gateway = parse_gateway_status(_json_output(status_result, "openclaw gateway status"))
    gateway_url = validate_gateway_url(args.gateway_url) if args.gateway_url else gateway.gateway_url

    original_env = env_path.read_text(encoding="utf-8")
    origin = validate_origin(args.origin or default_origin(root, original_env))
    updates = _managed_updates(origin, gateway_url)
    updated_env = update_env_text(original_env, updates)
    env_changed = updated_env != original_env

    compose: Path | None = None
    compose_image: str | None = None
    if not args.skip_service and not args.rebuild:
        compose = _compose_file(root)
        compose_image = _resolve_compose_image(runner, compose, parse_env_values(original_env))

    origins_result = runner.capture(
        ["openclaw", "config", "get", "gateway.controlUi.allowedOrigins", "--json"],
        check=False,
    )
    current_origins = [] if origins_result.returncode != 0 else _json_output(origins_result, "allowedOrigins")
    merged_origins = merge_allowed_origins(current_origins, origin)
    origins_changed = merged_origins != current_origins

    skill_dir: Path | None = None
    skill_present = False
    skill_current = False
    if not args.skip_skill:
        skill_dir = root / "integrations" / "openclaw" / "inteliscope"
        if not skill_dir.is_dir():
            raise SetupError(f"bundled Inteliscope Skill was not found: {skill_dir}")
        skill_info_result = runner.capture(
            ["openclaw", "skills", "info", "inteliscope", "--json"],
            check=False,
        )
        skill_present = skill_info_result.returncode == 0
        if skill_present:
            skill_info = _json_output(skill_info_result, "openclaw skills info")
            installed_base = skill_info.get("baseDir") if isinstance(skill_info, dict) else None
            if isinstance(installed_base, str) and installed_base:
                skill_current = skill_tree_matches(
                    skill_dir,
                    Path(installed_base).expanduser().resolve(),
                )
    skill_changed = not args.skip_skill and not skill_current

    print("OpenClaw local setup")
    print(f"  version: {gateway.cli_version}")
    print(f"  Gateway: {gateway_url}")
    print(f"  Inteliscope: {origin}")
    print(f"  env update: {'needed' if env_changed else 'already configured'}")
    print(f"  Origin update: {'needed' if origins_changed else 'already configured'}")
    if not args.skip_skill:
        skill_status = (
            "current"
            if skill_current
            else ("refresh needed" if skill_present else "install needed")
        )
        print(f"  Skill: {skill_status}")
    if compose_image:
        print(f"  Docker image: reuse {compose_image}")

    if env_changed:
        for key, value in updates.items():
            print(f"  set {key}={value}")
        if not args.dry_run:
            write_env_atomic(env_path, updated_env)

    if origins_changed:
        runner.execute(
            [
                "openclaw",
                "config",
                "set",
                "gateway.controlUi.allowedOrigins",
                json.dumps(merged_origins, ensure_ascii=False, separators=(",", ":")),
                "--strict-json",
            ]
        )

    if skill_changed:
        assert skill_dir is not None
        install_command = [
            "openclaw",
            "skills",
            "install",
            str(skill_dir),
            "--as",
            "inteliscope",
        ]
        if skill_present:
            install_command.append("--force")
        runner.execute(install_command)

    if not gateway.running:
        runner.execute(["openclaw", "gateway", "start"])
    elif origins_changed or skill_changed:
        runner.execute(["openclaw", "gateway", "restart"])
    runner.execute(["openclaw", "gateway", "status", "--require-rpc", "--timeout", "10000"])

    if not args.skip_service:
        if args.rebuild:
            runner.execute([str(root / "scripts" / "up-latest.sh")])
        else:
            assert compose is not None and compose_image is not None
            compose_env = {"INTELISCOPE_IMAGE": compose_image}
            base = ["docker", "compose", "-f", str(compose), "up", "-d", "--no-build"]
            runner.execute([*base, "horizon-worker"], env_override=compose_env)
            runner.execute([*base, "--force-recreate", "horizon-api"], env_override=compose_env)
        if not args.dry_run:
            ready_url = f"{origin}/api/health/ready"
            print(f"Waiting for {ready_url}")
            _wait_for_ready(ready_url, args.timeout)
            print("Inteliscope readiness: passed")

    agents_url = f"{origin}/agents"
    if not args.no_open and not args.dry_run:
        webbrowser.open(agents_url)

    print("\nSetup complete." if not args.dry_run else "\nDry run complete; no changes were made.")
    print("Remaining user-owned steps:")
    print(f"  1. Open {agents_url} and create a read-only Inteliscope connection.")
    print("  2. Save its one-time MCP token in ~/.openclaw/.env, then run the page-generated MCP commands.")
    print("  3. Run `openclaw dashboard`, then paste that dashboard URL into the Feed OpenClaw panel.")
    print("Do not paste either token into an Agent conversation or shell history.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Inspect and print planned mutations only.")
    parser.add_argument("--origin", help="Exact Inteliscope browser Origin; defaults from HORIZON_WEB_PORT.")
    parser.add_argument("--gateway-url", help="Override the Gateway URL reported by OpenClaw.")
    parser.add_argument("--env-file", help="Path to the Inteliscope .env file.")
    parser.add_argument("--project-root", default=str(ROOT), help=argparse.SUPPRESS)
    parser.add_argument("--skip-skill", action="store_true", help="Do not install the bundled Inteliscope Skill.")
    parser.add_argument("--skip-service", action="store_true", help="Do not start/recreate Docker services.")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild the current workspace with up-latest.sh.")
    parser.add_argument("--no-open", action="store_true", help="Do not open the /agents page after setup.")
    parser.add_argument("--timeout", type=int, default=120, help="Readiness timeout in seconds (default: 120).")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.timeout < 1:
        parser.error("--timeout must be at least 1 second")
    try:
        run_setup(args)
    except SetupError as exc:
        print(f"OpenClaw setup failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
