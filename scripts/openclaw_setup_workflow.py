"""Orchestration for the local Inteliscope and OpenClaw setup workflow."""

from __future__ import annotations

import argparse
import json
import shutil
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from scripts.openclaw_setup_compose import compose_file, resolve_compose_image
from scripts.openclaw_setup_env import (
    default_origin,
    managed_updates,
    parse_env_values,
    update_env_text,
    write_env_atomic,
)
from scripts.openclaw_setup_gateway import (
    merge_allowed_origins,
    parse_gateway_status,
    wait_for_ready,
)
from scripts.openclaw_setup_mcp import standard_tool_filter_upgrade
from scripts.openclaw_setup_process import CommandRunner, json_output
from scripts.openclaw_setup_skill import skill_tree_matches
from scripts.openclaw_setup_validation import (
    SetupError,
    validate_gateway_url,
    validate_origin,
)


@dataclass(frozen=True)
class SkillInspection:
    directory: Path | None
    present: bool
    current: bool

    @property
    def changed(self) -> bool:
        return self.directory is not None and not self.current


def run_setup(args: argparse.Namespace) -> None:
    root = Path(args.project_root).expanduser().resolve()
    env_path = (
        Path(args.env_file).expanduser().resolve() if args.env_file else root / ".env"
    )
    if not env_path.exists():
        raise SetupError(
            f"{env_path} does not exist. Create it from .env.example and "
            "configure Service login first."
        )
    for command in ("openclaw", "docker"):
        if shutil.which(command) is None:
            raise SetupError(f"required command is not installed: {command}")

    runner = CommandRunner(cwd=root, dry_run=args.dry_run)
    status_result = runner.capture(
        ["openclaw", "gateway", "status", "--json", "--no-probe"]
    )
    gateway = parse_gateway_status(json_output(status_result, "openclaw gateway status"))
    gateway_url = (
        validate_gateway_url(args.gateway_url)
        if args.gateway_url
        else gateway.gateway_url
    )

    original_env = env_path.read_text(encoding="utf-8")
    origin = validate_origin(args.origin or default_origin(root, original_env))
    updates = managed_updates(origin, gateway_url)
    updated_env = update_env_text(original_env, updates)
    env_changed = updated_env != original_env

    compose: Path | None = None
    compose_image: str | None = None
    if not args.skip_service and not args.rebuild:
        compose = compose_file(root)
        compose_image = resolve_compose_image(
            runner,
            compose,
            parse_env_values(original_env),
        )

    origins_result = runner.capture(
        ["openclaw", "config", "get", "gateway.controlUi.allowedOrigins", "--json"],
        check=False,
    )
    current_origins = (
        []
        if origins_result.returncode != 0
        else json_output(origins_result, "allowedOrigins")
    )
    merged_origins = merge_allowed_origins(current_origins, origin)
    origins_changed = merged_origins != current_origins

    mcp_filter_upgrade, custom_mcp_filter = _inspect_mcp_filter(runner)
    skill = _inspect_skill(root, runner, skip=args.skip_skill)

    _print_plan(
        gateway.cli_version,
        gateway_url,
        origin,
        env_changed=env_changed,
        origins_changed=origins_changed,
        mcp_filter_upgrade=mcp_filter_upgrade,
        custom_mcp_filter=custom_mcp_filter,
        skip_skill=args.skip_skill,
        skill_present=skill.present,
        skill_current=skill.current,
        compose_image=compose_image,
    )

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

    if skill.changed:
        assert skill.directory is not None
        install_command = [
            "openclaw",
            "skills",
            "install",
            str(skill.directory),
            "--as",
            "inteliscope",
        ]
        if skill.present:
            install_command.append("--force")
        runner.execute(install_command)

    if mcp_filter_upgrade is not None:
        runner.execute(
            [
                "openclaw",
                "mcp",
                "tools",
                "inteliscope",
                "--include",
                ",".join(mcp_filter_upgrade),
            ]
        )

    _apply_gateway_changes(
        runner,
        running=gateway.running,
        restart_needed=(
            origins_changed or skill.changed or mcp_filter_upgrade is not None
        ),
    )

    if not args.skip_service:
        if args.rebuild:
            runner.execute([str(root / "scripts" / "up-latest.sh")])
        else:
            assert compose is not None and compose_image is not None
            compose_env = {"INTELISCOPE_IMAGE": compose_image}
            base = ["docker", "compose", "-f", str(compose), "up", "-d", "--no-build"]
            runner.execute([*base, "horizon-worker"], env_override=compose_env)
            runner.execute(
                [*base, "--force-recreate", "horizon-api"],
                env_override=compose_env,
            )
        if not args.dry_run:
            ready_url = f"{origin}/api/health/ready"
            print(f"Waiting for {ready_url}")
            wait_for_ready(ready_url, args.timeout)
            print("Inteliscope readiness: passed")

    agents_url = f"{origin}/agents"
    if not args.no_open and not args.dry_run:
        webbrowser.open(agents_url)
    _print_completion(agents_url, args.dry_run)


def _inspect_mcp_filter(
    runner: CommandRunner,
) -> tuple[tuple[str, ...] | None, bool]:
    result = runner.capture(
        ["openclaw", "mcp", "show", "inteliscope", "--json"],
        check=False,
    )
    if result.returncode != 0:
        return None, False
    return standard_tool_filter_upgrade(
        json_output(result, "Inteliscope MCP configuration")
    )


def _inspect_skill(
    root: Path,
    runner: CommandRunner,
    *,
    skip: bool,
) -> SkillInspection:
    if skip:
        return SkillInspection(directory=None, present=False, current=False)
    skill_dir = root / "integrations" / "openclaw" / "inteliscope"
    if not skill_dir.is_dir():
        raise SetupError(f"bundled Inteliscope Skill was not found: {skill_dir}")
    result = runner.capture(
        ["openclaw", "skills", "info", "inteliscope", "--json"],
        check=False,
    )
    if result.returncode != 0:
        return SkillInspection(directory=skill_dir, present=False, current=False)
    payload = json_output(result, "openclaw skills info")
    installed_base = payload.get("baseDir") if isinstance(payload, dict) else None
    current = isinstance(installed_base, str) and bool(installed_base) and skill_tree_matches(
        skill_dir,
        Path(installed_base).expanduser().resolve(),
    )
    return SkillInspection(directory=skill_dir, present=True, current=current)


def _apply_gateway_changes(
    runner: CommandRunner,
    *,
    running: bool,
    restart_needed: bool,
) -> None:
    if not running:
        runner.execute(["openclaw", "gateway", "start"])
    elif restart_needed:
        runner.execute(["openclaw", "gateway", "restart"])
    runner.execute(
        ["openclaw", "gateway", "status", "--require-rpc", "--timeout", "10000"]
    )


def _print_plan(
    cli_version: str,
    gateway_url: str,
    origin: str,
    *,
    env_changed: bool,
    origins_changed: bool,
    mcp_filter_upgrade: tuple[str, ...] | None,
    custom_mcp_filter: bool,
    skip_skill: bool,
    skill_present: bool,
    skill_current: bool,
    compose_image: str | None,
) -> None:
    print("OpenClaw local setup")
    print(f"  version: {cli_version}")
    print(f"  Gateway: {gateway_url}")
    print(f"  Inteliscope: {origin}")
    print(f"  env update: {'needed' if env_changed else 'already configured'}")
    print(f"  Origin update: {'needed' if origins_changed else 'already configured'}")
    if mcp_filter_upgrade is not None:
        print("  MCP tool filter: standard filter upgrade needed")
    elif custom_mcp_filter:
        print("  MCP tool filter: custom filter preserved; add resolve_source manually")
    if not skip_skill:
        skill_status = (
            "current"
            if skill_current
            else ("refresh needed" if skill_present else "install needed")
        )
        print(f"  Skill: {skill_status}")
    if compose_image:
        print(f"  Docker image: reuse {compose_image}")


def _print_completion(agents_url: str, dry_run: bool) -> None:
    print("\nSetup complete." if not dry_run else "\nDry run complete; no changes were made.")
    print("Remaining user-owned steps:")
    print(f"  1. Open {agents_url} and create a read-only Inteliscope connection.")
    print(
        "  2. Save its one-time MCP token in ~/.openclaw/.env, then run the "
        "page-generated MCP commands."
    )
    print(
        "  3. Run `openclaw dashboard`, then paste that dashboard URL into "
        "the Feed OpenClaw panel."
    )
    print("Do not paste either token into an Agent conversation or shell history.")
