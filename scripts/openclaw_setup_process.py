"""Bounded subprocess helpers for the local OpenClaw setup workflow."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any, Sequence

from scripts.openclaw_setup_validation import SetupError


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

    def execute(
        self,
        argv: Sequence[str],
        *,
        env_override: dict[str, str] | None = None,
    ) -> None:
        prefix = " ".join(
            f"{key}={shlex.quote(value)}" for key, value in (env_override or {}).items()
        )
        print(f"$ {prefix + ' ' if prefix else ''}{shlex.join(argv)}")
        if self.dry_run:
            return
        process_env = os.environ.copy()
        process_env.update(env_override or {})
        try:
            subprocess.run(list(argv), cwd=self.cwd, env=process_env, check=True)
        except subprocess.CalledProcessError as exc:
            command = shlex.join(argv)
            raise SetupError(
                f"command failed with exit code {exc.returncode}: {command}"
            ) from exc


def json_output(result: subprocess.CompletedProcess[str], label: str) -> Any:
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SetupError(f"{label} did not return valid JSON.") from exc
