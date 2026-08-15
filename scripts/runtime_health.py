#!/usr/bin/env python3
"""Wait for one API/Worker runtime to become consistently healthy."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable


class MigrationRequired(RuntimeError):
    """The target revision is live but needs an explicit database migration."""


class RuntimeUnhealthy(RuntimeError):
    """A container reached Docker's terminal unhealthy state."""


@dataclass(frozen=True)
class RuntimeExpectation:
    base_url: str
    expected_revision: str
    expected_version: str | None
    api_container: str
    worker_container: str
    public_url: str | None = None


def _fetch(url: str) -> bytes:
    result = subprocess.run(
        ["curl", "-fsS", "--max-time", "10", url],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise OSError(detail or f"curl failed for {url}")
    return result.stdout


def _json(url: str) -> dict[str, Any]:
    payload = json.loads(_fetch(url))
    if not isinstance(payload, dict):
        raise ValueError(f"non-object JSON from {url}")
    return payload


def _data(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("data")
    return value if isinstance(value, dict) else payload


def _container_health(name: str) -> str:
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Health.Status}}", name],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "missing"


def _frontend_asset(base_url: str, fetch: Callable[[str], bytes]) -> str:
    html = fetch(f"{base_url.rstrip('/')}/").decode("utf-8", errors="replace")
    match = re.search(r'/assets/[^"\s]+\.js', html)
    if not match:
        raise ValueError("React frontend asset was not found")
    asset = match.group(0)
    fetch(f"{base_url.rstrip('/')}{asset}")
    return asset.rsplit("/", 1)[-1]


def check_once(
    expectation: RuntimeExpectation,
    *,
    fetch_json: Callable[[str], dict[str, Any]] = _json,
    fetch_bytes: Callable[[str], bytes] = _fetch,
    container_health: Callable[[str], str] = _container_health,
) -> tuple[bool, str]:
    base = expectation.base_url.rstrip("/")
    live = _data(fetch_json(f"{base}/api/health/live"))
    ready_payload = fetch_json(f"{base}/api/health/ready")
    ready = _data(ready_payload)
    if ready.get("status") == "migration_required" or (
        isinstance(ready_payload.get("error"), dict)
        and ready_payload["error"].get("code") == "migration_required"
    ):
        if live.get("revision") == expectation.expected_revision:
            raise MigrationRequired("target revision requires an explicit migration")
        raise RuntimeUnhealthy("migration response did not come from the target revision")
    if live.get("revision") != expectation.expected_revision:
        return False, "waiting for target revision"
    if expectation.expected_version and live.get("version") != expectation.expected_version:
        return False, "waiting for target version"
    if ready.get("status") != "ready" or ready.get("worker_status") != "ready":
        return False, "waiting for API/Worker readiness"
    api_health = container_health(expectation.api_container)
    worker_health = container_health(expectation.worker_container)
    if "unhealthy" in {api_health, worker_health}:
        raise RuntimeUnhealthy(
            f"container unhealthy: api={api_health or 'missing'} worker={worker_health or 'missing'}"
        )
    if api_health != "healthy" or worker_health != "healthy":
        return False, f"waiting for container health: api={api_health} worker={worker_health}"
    asset = _frontend_asset(base, fetch_bytes)
    if expectation.public_url:
        public_live = _data(fetch_json(f"{expectation.public_url.rstrip('/')}/api/health/live"))
        if public_live.get("revision") != expectation.expected_revision:
            return False, "waiting for public revision"
    return True, f"ready revision={expectation.expected_revision} asset={asset}"


def wait_for_runtime(
    expectation: RuntimeExpectation,
    *,
    timeout: float,
    interval: float,
    check: Callable[[RuntimeExpectation], tuple[bool, str]] = check_once,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> str:
    deadline = monotonic() + timeout
    detail = "runtime has not been checked"
    while True:
        try:
            ready, detail = check(expectation)
        except (MigrationRequired, RuntimeUnhealthy):
            raise
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            ready, detail = False, str(exc)
        if ready:
            return detail
        if monotonic() >= deadline:
            raise TimeoutError(f"runtime health timed out: {detail}")
        sleep(interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--expected-version")
    parser.add_argument("--api-container", required=True)
    parser.add_argument("--worker-container", required=True)
    parser.add_argument("--public-url")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--interval", type=float, default=2)
    args = parser.parse_args(argv)
    expectation = RuntimeExpectation(
        base_url=args.base_url,
        expected_revision=args.expected_revision,
        expected_version=args.expected_version,
        api_container=args.api_container,
        worker_container=args.worker_container,
        public_url=args.public_url,
    )
    try:
        detail = wait_for_runtime(expectation, timeout=args.timeout, interval=args.interval)
    except MigrationRequired as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except (RuntimeUnhealthy, TimeoutError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(detail)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
