"""Classify bounded Actor Dataset rows before content mapping."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_CONTROL_TYPES = frozenset(
    {
        "diagnostic",
        "diagnostics",
        "mock",
        "placeholder",
        "run-report",
        "run_report",
        "receipt",
        "stats",
        "paywall",
        "payment-required",
        "payment_required",
        "upgrade-required",
        "upgrade_required",
    }
)


def is_placeholder_or_control(row: Mapping[str, Any]) -> bool:
    """Return whether a row is a non-content demo, control, or paywall row."""

    for key in (
        "demo", "isDemo", "is_demo", "mock", "isMock", "is_mock",
        "placeholder", "paywall", "isPaywalled", "is_paywalled",
        "paymentRequired", "payment_required",
    ):
        if row.get(key) is True:
            return True
    row_type = str(
        row.get("resultType") or row.get("result_type")
        or row.get("recordType") or row.get("record_type")
        or row.get("type") or ""
    ).strip().casefold()
    if row_type in _CONTROL_TYPES:
        return True
    control_text = " ".join(
        str(row.get(key) or "")
        for key in ("error", "message", "notice", "statusMessage", "warning", "status")
    ).casefold()
    return any(
        marker in control_text
        for marker in (
            "demo mode", "placeholder", "mock data", "payment required",
            "upgrade your plan",
        )
    )


def is_metadata_only_mapping(values: Mapping[str, Any]) -> bool:
    """Return whether a mapped row proves source metadata, not a content item."""

    if not any(
        values.get(field_name) is not None
        for field_name in ("native_id", "url", "published_at", "title", "text")
    ):
        return True
    # Profile-feed Actors may prepend a channel/profile record. A title and URL
    # alone do not form a ContentItem without a stable item ID and publish time.
    return (
        values.get("native_id") is None
        and values.get("published_at") is None
        and any(
            values.get(field_name) is not None
            for field_name in (
                "source_native_id", "source_name", "source_url", "author",
                "author_handle",
            )
        )
    )


__all__ = ["is_metadata_only_mapping", "is_placeholder_or_control"]
