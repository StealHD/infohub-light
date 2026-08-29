"""Bounded timestamp normalization for Apify Actor Dataset rows."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from dateutil.parser import isoparse


def parse_actor_datetime(value: Any) -> datetime:
    if isinstance(value, bool):
        raise TypeError("datetime must not be a boolean")
    if isinstance(value, (int, float)):
        return _parse_epoch_datetime(value)
    if not isinstance(value, str) or not value.strip():
        raise TypeError("datetime must be a nonempty string or epoch number")
    normalized = value.strip()
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", normalized):
        return _parse_epoch_datetime(float(normalized))
    try:
        parsed = isoparse(normalized)
    except ValueError:
        parsed = datetime.strptime(normalized, "%a %b %d %H:%M:%S %z %Y")
    if parsed.tzinfo is None:
        raise ValueError("datetime must include a timezone")
    return parsed.astimezone(timezone.utc)


def _parse_epoch_datetime(value: int | float) -> datetime:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("epoch datetime must be finite and nonnegative")
    max_epoch_seconds = 4_102_444_800
    if number > max_epoch_seconds:
        number /= 1_000
    if number < 946_684_800 or number > max_epoch_seconds:
        raise ValueError("epoch datetime is outside the supported range")
    try:
        return datetime.fromtimestamp(number, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        raise ValueError("epoch datetime is invalid") from None


__all__ = ["parse_actor_datetime"]
