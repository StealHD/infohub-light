"""Shared logging setup."""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def configure_logging(log_dir: str = "logs", filename: str = "horizon.log") -> None:
    """Configure root logging once with console and file handlers."""
    root = logging.getLogger()
    if root.handlers:
        return

    Path(log_dir).mkdir(parents=True, exist_ok=True)
    root.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    file_handler = logging.FileHandler(Path(log_dir) / filename, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)
