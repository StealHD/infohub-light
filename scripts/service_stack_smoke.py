"""Run the Docker-backed InfoHub service smoke sequence.

This script intentionally stays stdlib-only. It starts the lightweight API
service, waits for the API health endpoint, then runs the smaller smoke
scripts and writes a compact aggregate report.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol


STATUS_ORDER = ("passed", "failed", "skipped", "degraded_optional")


class CommandResult(Protocol):
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[list[str]], CommandResult]
HealthChecker = Callable[[str, int], dict[str, Any]]


def build_report(steps: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {status: 0 for status in STATUS_ORDER}
    for step in steps:
        status = str(step.get("status") or "failed")
        summary[status] = summary.get(status, 0) + 1
    failed = [step["name"] for step in steps if step.get("status") == "failed"]
    return {
        "ok": not failed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "failed": failed,
        "steps": steps,
    }


def _default_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True)


def _trim_output(value: str, *, limit: int = 4000) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...<truncated>"


def _command_step(
    name: str,
    command: list[str],
    *,
    runner: Runner,
    report_path: str | None = None,
    degraded_optional: bool = False,
) -> dict[str, Any]:
    result = runner(command)
    passed = result.returncode == 0
    status = "passed" if passed else "failed"
    if not passed and degraded_optional:
        status = "degraded_optional"
    step: dict[str, Any] = {
        "name": name,
        "status": status,
        "command": command,
        "exit_code": result.returncode,
    }
    if report_path:
        step["report_path"] = report_path
    if result.stdout:
        step["stdout"] = _trim_output(result.stdout)
    if result.stderr:
        step["stderr"] = _trim_output(result.stderr)
    return step


def wait_for_api_health(base_url: str, timeout_seconds: int = 90) -> dict[str, Any]:
    endpoint = f"{base_url.rstrip('/')}/api/health/ready"
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(endpoint, headers={"Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=5) as response:
                raw = response.read().decode("utf-8", errors="replace")
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    payload = {"raw": raw[:200]}
                return {
                    "name": "api_health",
                    "status": "passed",
                    "endpoint": endpoint,
                    "message": "API health endpoint responded",
                    "payload": payload,
                }
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            last_error = str(exc)
            time.sleep(2)
    return {
        "name": "api_health",
        "status": "failed",
        "endpoint": endpoint,
        "message": "API health endpoint did not become ready",
        "error": last_error,
    }


def _child_report_path(prefix: str, report_dir: str) -> str:
    return str(Path(report_dir) / f"{prefix}-latest.json")


def run_stack_smoke(
    *,
    compose_file: str,
    base_url: str,
    username: str,
    password: str,
    api_only: bool,
    full_real_source: bool,
    run_worker: bool,
    project_name: str | None = None,
    cleanup: bool = False,
    report_dir: str = "logs",
    runner: Runner = _default_runner,
    health_checker: HealthChecker = wait_for_api_health,
    health_timeout_seconds: int = 90,
    hours: int = 168,
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    command_runner = runner
    if runner is _default_runner:
        child_environment = dict(os.environ)
        child_environment["HORIZON_AUTH_USER"] = username
        child_environment["HORIZON_AUTH_PASSWORD"] = password
        if api_only and not run_worker:
            child_environment["HORIZON_REQUIRE_WORKER_FOR_READINESS"] = "false"

        def command_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                env=child_environment,
            )

    compose_prefix = ["docker", "compose", "-f", compose_file]
    if project_name:
        compose_prefix.extend(["-p", project_name])

    def finish() -> dict[str, Any]:
        if cleanup:
            steps.append(
                _command_step(
                    "compose_down",
                    [*compose_prefix, "down", "--volumes", "--remove-orphans"],
                    runner=command_runner,
                )
            )
        return build_report(steps)

    compose_services = ["horizon-api"]
    if run_worker:
        compose_services.append("horizon-worker")
    steps.append(
        _command_step(
            "compose_up",
            [
                *compose_prefix,
                "up",
                "-d",
                "--build",
                *compose_services,
            ],
            runner=command_runner,
        )
    )
    if steps[-1]["status"] != "passed":
        steps.append(
            {
                "name": "api_health",
                "status": "skipped",
                "reason": "compose_up_failed",
            }
        )
        steps.append(
            {
                "name": "api_smoke",
                "status": "skipped",
                "reason": "compose_up_failed",
            }
        )
        steps.append(
            {
                "name": "real_source_smoke",
                "status": "skipped",
                "reason": "compose_up_failed",
            }
        )
        return finish()

    try:
        health_step = health_checker(base_url, health_timeout_seconds)
    except Exception as exc:  # pragma: no cover - defensive manual-smoke guard
        health_step = {
            "name": "api_health",
            "status": "failed",
            "message": str(exc),
            "error_type": type(exc).__name__,
        }
    health_step.setdefault("name", "api_health")
    steps.append(health_step)
    if health_step.get("status") != "passed":
        steps.append(
            _command_step(
                "api_container_logs",
                [*compose_prefix, "logs", "--no-color", "--tail", "120", "horizon-api"],
                runner=command_runner,
            )
        )
        steps.append(
            {
                "name": "api_smoke",
                "status": "skipped",
                "reason": "api_health_failed",
            }
        )
        steps.append(
            {
                "name": "real_source_smoke",
                "status": "skipped",
                "reason": "api_health_failed",
            }
        )
        return finish()

    api_report_path = _child_report_path("service-api-smoke", report_dir)
    steps.append(
        _command_step(
            "api_smoke",
            [
                sys.executable,
                "scripts/service_api_smoke.py",
                "--base-url",
                base_url,
                "--username",
                username,
                "--json-output",
                api_report_path,
            ],
            runner=command_runner,
            report_path=api_report_path,
        )
    )

    if api_only or not full_real_source:
        steps.append(
            {
                "name": "real_source_smoke",
                "status": "skipped",
                "reason": "full_real_source_not_requested",
            }
        )
        return finish()

    if run_worker:
        steps.append(
            {
                "name": "worker_once",
                "status": "passed",
                "message": "service_real_source_smoke will execute worker --once for queued jobs",
            }
        )
    else:
        steps.append(
            {
                "name": "worker_once",
                "status": "skipped",
                "reason": "run_worker_not_requested",
            }
        )

    real_report_path = _child_report_path("service-real-source-smoke", report_dir)
    real_command = [
        sys.executable,
        "scripts/service_real_source_smoke.py",
        "--base-url",
        base_url,
        "--hours",
        str(hours),
        "--json-output",
        real_report_path,
    ]
    if run_worker:
        real_command.append("--run-worker")
    steps.append(
        _command_step(
            "real_source_smoke",
            real_command,
            runner=command_runner,
            report_path=real_report_path,
        )
    )

    return finish()


def write_report(report: dict[str, Any], output: str | None) -> Path | None:
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if output == "-":
        print(text)
        return None
    if output:
        path = Path(output)
    else:
        path = Path("logs") / "service-stack-smoke-latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    path.chmod(0o600)
    print(f"wrote {path}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Docker-backed InfoHub service smoke checks.")
    parser.add_argument("--compose-file", default="docker-compose.light.yml")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--username", default=os.getenv("HORIZON_AUTH_USER", "admin"))
    parser.add_argument("--password", default=os.getenv("HORIZON_AUTH_PASSWORD"))
    parser.add_argument("--api-only", action="store_true")
    parser.add_argument("--full-real-source", action="store_true")
    parser.add_argument("--run-worker", action="store_true")
    parser.add_argument("--project-name", default=None)
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--report-dir", default="logs")
    parser.add_argument("--hours", type=int, default=168)
    parser.add_argument("--health-timeout", type=int, default=90)
    parser.add_argument("--json-output", default=None)
    args = parser.parse_args()

    if args.api_only and args.full_real_source:
        parser.error("--api-only and --full-real-source cannot be used together")
    if not args.password:
        print("--password or HORIZON_AUTH_PASSWORD is required", file=sys.stderr)
        return 2

    report = run_stack_smoke(
        compose_file=args.compose_file,
        base_url=args.base_url,
        username=args.username,
        password=args.password,
        api_only=args.api_only,
        full_real_source=args.full_real_source,
        run_worker=args.run_worker,
        project_name=args.project_name,
        cleanup=args.cleanup,
        report_dir=args.report_dir,
        health_timeout_seconds=args.health_timeout,
        hours=args.hours,
    )
    write_report(report, args.json_output)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
