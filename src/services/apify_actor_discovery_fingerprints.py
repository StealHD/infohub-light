"""Stable non-sensitive fingerprints for generic Actor discovery evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def mapping_hash(value: Mapping[str, Any]) -> str:
    """Hash a mapping in a deterministic, JSON-compatible form."""

    return hashlib.sha256(
        json.dumps(
            dict(value), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
