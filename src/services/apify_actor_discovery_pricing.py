"""Safe, stable pricing evidence used by Actor discovery and maintenance."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


def safe_pricing_summary(pricing: Mapping[str, Any]) -> dict[str, Any]:
    """Reduce pricing evidence to deterministic, finite, non-sensitive fields."""

    allowed = (
        "pricingModel", "model", "minimumChargeUsd", "minChargeUsd",
        "minimumPriceUsd", "pricePerRunUsd", "minimalMaxTotalChargeUsd",
        "pricePerUnitUsd",
    )
    summary: dict[str, Any] = {
        key: value for key in allowed
        if isinstance((value := pricing.get(key)), str)
        or _finite_price(value) is not None
    }
    pricing_per_event = pricing.get("pricingPerEvent")
    events = (
        pricing_per_event.get("actorChargeEvents")
        if isinstance(pricing_per_event, Mapping)
        else pricing.get("actorChargeEvents")
    )
    safe_events = _safe_events(events)
    if safe_events:
        summary["pricingPerEvent"] = {"actorChargeEvents": safe_events}
    safe_tiers = _safe_dataset_tiers(pricing.get("tieredPricing"))
    if safe_tiers:
        summary["tieredPricing"] = safe_tiers
    return summary


def _safe_events(events: Any) -> dict[str, Any]:
    if not isinstance(events, Mapping):
        return {}
    safe_events: dict[str, Any] = {}
    for event_name, event in sorted(events.items())[:64]:
        if not isinstance(event_name, str) or not isinstance(event, Mapping):
            continue
        safe_event: dict[str, Any] = {}
        value = event.get("eventPriceUsd")
        if _finite_price(value) is not None:
            safe_event["eventPriceUsd"] = value
        tiered = event.get("eventTieredPricingUsd")
        if isinstance(tiered, Mapping):
            safe_tiers = {
                tier_name: safe_value
                for tier_name, tier in sorted(tiered.items())[:32]
                if isinstance(tier_name, str)
                and (safe_value := _finite_price(
                    tier.get("tieredEventPriceUsd")
                    if isinstance(tier, Mapping) else tier
                )) is not None
            }
            if safe_tiers:
                safe_event["eventTieredPricingUsd"] = safe_tiers
        if safe_event:
            safe_events[event_name[:128]] = safe_event
    return safe_events


def _safe_dataset_tiers(tiered_dataset: Any) -> dict[str, dict[str, float]]:
    if not isinstance(tiered_dataset, Mapping):
        return {}
    return {
        tier_name[:64]: {"tieredPricePerUnitUsd": safe_value}
        for tier_name, tier in sorted(tiered_dataset.items())[:32]
        if isinstance(tier_name, str)
        and (safe_value := _finite_price(
            tier.get("tieredPricePerUnitUsd") if isinstance(tier, Mapping) else None
        )) is not None
    }


def _finite_price(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        numeric = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) and numeric >= 0 else None
