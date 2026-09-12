"""Smoke an existing production image in an isolated, egress-free API container."""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import tempfile
import time
from pathlib import Path

from scripts.test_gate_changes import GateConfigError


def docker(*args: str, **kwargs) -> str:
    return subprocess.run(["docker", *args], check=True, capture_output=True,
                          text=True, timeout=180, **kwargs).stdout.strip()


def smoke(root: Path, image: str) -> dict:
    started = time.monotonic()
    metadata = json.loads(docker("image", "inspect", image))[0]
    if metadata["Architecture"] != "amd64" or metadata["Os"] != "linux":
        raise GateConfigError("fast smoke requires a linux/amd64 image")
    image_id = metadata["Id"]
    name = "inteliscope-fast-smoke-" + secrets.token_hex(6)
    password = secrets.token_urlsafe(32)
    environment = {k: v for k, v in os.environ.items()
                   if not k.startswith(("HORIZON_", "INTELISCOPE_"))}
    environment["HORIZON_AUTH_PASSWORD"] = password
    created = False
    with tempfile.TemporaryDirectory(prefix="inteliscope-fast-smoke-") as temp:
        directory = Path(temp)
        (directory / "data").mkdir(mode=0o700)
        (directory / "logs").mkdir(mode=0o700)
        config = directory / "data/config.json"
        config.write_bytes((root / "data/config.light.example.json").read_bytes())
        config.chmod(0o600)
        try:
            docker("run", "-d", "--pull=never", "--platform", "linux/amd64",
                   "--name", name, "--network", "none",
                   "-v", f"{directory / 'data'}:/app/data",
                   "-v", f"{directory / 'logs'}:/app/logs",
                   "-e", "HORIZON_AUTH_USER=admin", "-e", "HORIZON_AUTH_PASSWORD",
                   "-e", "HORIZON_REQUIRE_WORKER_FOR_READINESS=false",
                   "-e", "HORIZON_SQLITE_JOURNAL_MODE=DELETE",
                   "-e", "HORIZON_APIFY_KEY_POOL_ENABLED=false",
                   "-e", "HORIZON_REMOTE_MCP_ENABLED=false",
                   "--entrypoint", "/app/.venv/bin/horizon-api", image_id,
                   "--host", "0.0.0.0", "--port", "8080", env=environment)
            created = True
            docker("exec", name, "/app/.venv/bin/python", "-c",
                   "from scripts.service_stack_smoke import wait_for_api_health; "
                   "import sys; sys.exit(0 if wait_for_api_health('http://127.0.0.1:8080', 120)"
                   "['status'] == 'passed' else 1)")
            report = json.loads(docker("exec", name, "/app/.venv/bin/python",
                                      "scripts/service_api_smoke.py", "--base-url",
                                      "http://127.0.0.1:8080", "--json-output", "-"))
            if not report["ok"]:
                raise GateConfigError("prepared image API smoke failed: " + ", ".join(report["failed"]))
            report.update(image_id=image_id, duration=round(time.monotonic() - started, 3))
            return report
        finally:
            if created:
                docker("rm", "-f", "-v", name)
            else:
                # A failed docker run can still have created a stopped container.
                subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True)
