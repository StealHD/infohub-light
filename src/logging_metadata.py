"""Value-free build and code-location metadata for private log files."""

from __future__ import annotations

import os
import re
from pathlib import Path
from types import TracebackType
from typing import Any


_SOURCE_ROOT = Path(__file__).resolve().parent
_VERSION = re.compile(r"(?:unknown|[0-9]+\.[0-9]+\.[0-9]+(?:[-+][a-zA-Z0-9.-]{1,48})?)\Z")
_REVISION = re.compile(r"(?:unknown|[0-9a-f]{7,40})\Z")
_SYMBOL = re.compile(r"[a-zA-Z_][a-zA-Z0-9_.-]{0,127}\Z")


def build_metadata() -> dict[str, str]:
    version = os.getenv("INTELISCOPE_VERSION", "unknown")
    revision = os.getenv("INTELISCOPE_BUILD_REVISION", "unknown")
    return {
        "version": version if _VERSION.fullmatch(version) else "unknown",
        "revision": revision if _REVISION.fullmatch(revision) else "unknown",
    }


def safe_frame(filename: str, function: str, line: int) -> dict[str, Any]:
    """Only first-party source gets a relative path; never include source text."""
    path = Path(filename)
    name = path.name
    safe_name = name if _SYMBOL.fullmatch(name) else "external"
    try:
        relative = path.resolve().relative_to(_SOURCE_ROOT)
    except (OSError, ValueError):
        pass
    else:
        if all(_SYMBOL.fullmatch(part) for part in relative.parts):
            safe_name = "src/" + relative.as_posix()
    return {
        "file": safe_name,
        "function": function if _SYMBOL.fullmatch(function) or function in {
            "<module>", "<lambda>", "<listcomp>", "<dictcomp>", "<genexpr>", "<setcomp>"
        } else "unknown",
        "line": max(int(line), 0),
    }


def exception_frames(tb: TracebackType | None) -> list[dict[str, Any]]:
    frames = []
    while tb is not None:
        code = tb.tb_frame.f_code
        frames.append(safe_frame(code.co_filename, code.co_name, tb.tb_lineno))
        tb = tb.tb_next
    return frames[-32:]
