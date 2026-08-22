"""Compose selection and image reuse for local OpenClaw setup."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.openclaw_setup_process import CommandRunner
from scripts.openclaw_setup_validation import SetupError


def compose_file(root: Path) -> Path:
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
                raise SetupError(
                    "docker compose ps did not return valid JSON."
                ) from exc
    for record in records:
        if isinstance(record, dict) and record.get("Service") == "horizon-api":
            image = record.get("Image")
            return image if isinstance(image, str) and image else None
    return None


def resolve_compose_image(
    runner: CommandRunner,
    compose: Path,
    env_values: dict[str, str],
) -> str:
    ps_result = runner.capture(
        [
            "docker",
            "compose",
            "-f",
            str(compose),
            "ps",
            "--format",
            "json",
            "horizon-api",
        ],
        check=False,
    )
    current = (
        compose_image_from_ps(ps_result.stdout) if ps_result.returncode == 0 else None
    )
    candidate = current or env_values.get("INTELISCOPE_IMAGE") or "inteliscope-service:local"
    inspect = runner.capture(["docker", "image", "inspect", candidate], check=False)
    if inspect.returncode != 0:
        raise SetupError(
            f"Docker image {candidate!r} is not available. "
            "Re-run with --rebuild to build the current workspace."
        )
    return candidate
