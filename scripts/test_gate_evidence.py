"""Input-bound local test evidence, independent of commit-message-only changes."""
from __future__ import annotations

import functools
import hashlib
import json
import os
import platform
import stat
import subprocess
from pathlib import Path
from typing import Any

from scripts.test_gate_changes import _git_file_paths, _is_safe_relative_path


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def inputs(root: Path) -> dict[str, Any]:
    """Hash only Git-owned inputs; never traverse runtime or credential files."""
    files = {}
    for relative in _git_file_paths(root):
        path = root / relative
        if not path.exists() and not path.is_symlink():
            continue
        info = path.lstat()
        content = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
        files[relative] = [stat.S_IFMT(info.st_mode), bool(info.st_mode & stat.S_IXUSR),
                           hashlib.sha256(content).hexdigest()]
    # Tracked excluded inputs (for example data/config.light.example.json) are
    # identified by Git objects, without opening operator-owned runtime files.
    index = subprocess.run(["git", "ls-files", "-s", "-z"], cwd=root, check=True,
                           capture_output=True, text=True).stdout
    for entry in index.split("\0"):
        if entry:
            metadata, name = entry.split("\t", 1)
            if not _is_safe_relative_path(name):
                files[name] = metadata
    dirty = subprocess.run(["git", "diff", "--name-only", "HEAD", "-z"], cwd=root,
                           check=True, capture_output=True, text=True).stdout.split("\0")
    if any(name and not _is_safe_relative_path(name) for name in dirty):
        raise ValueError("excluded tracked input changed; validate after committing it")
    business = {name: value for name, value in files.items()
                if not (name.endswith(".md") and isinstance(value, list)
                        and value[0] == stat.S_IFREG and not value[1])}
    return {"source": digest(business), "all_inputs": digest(files)}


def environment() -> dict[str, str]:
    try:
        node = subprocess.run(["node", "--version"], capture_output=True, text=True,
                              timeout=10, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        node = "unavailable"
    return {"python": platform.python_version(), "system": platform.system(),
            "machine": platform.machine(), "node": node}


def normalized(argv: list[str] | tuple[str, ...], root: Path) -> list[str]:
    result = [str(arg).replace(str(root), "{root}") for arg in argv]
    if result and ("python" in Path(result[0]).name):
        result[0] = "python"
    return result


def record_evidence(function):
    @functools.wraps(function)
    def wrapped(root, specs, base_result, **kwargs):
        before = None
        try:
            before = inputs(root)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        result = function(root, specs, base_result, **kwargs)
        try:
            after = inputs(root)
        except (OSError, ValueError, subprocess.SubprocessError):
            after = None
        result["verification"] = {
            "schema": 1, "reusable": before is not None and before == after,
            "inputs": before, "environment": environment(),
            "specs": [{"id": spec.command_id, "argv": normalized(spec.argv, root),
                       "domain": spec.domain} for spec in specs],
        }
        return result
    return wrapped
