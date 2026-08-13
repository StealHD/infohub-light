"""Safe, deterministic public projections for ActorOps routes and revisions."""

import math
from typing import Any

from ..services.apify_actor_ops import ApifyActorOpsService


def public_actor_ops_route(
    ops: ApifyActorOpsService,
    route: dict[str, Any],
) -> dict[str, Any]:
    gate = ops.schedule_gate(str(route["route_id"]))
    workflow = ops.workflow_state(str(route["route_id"]))
    profile_status = str(route["status"])
    if ops.source_capability_ready(str(route["route_id"])):
        support_status = "supported"
    elif profile_status == "candidate_shortfall":
        support_status = "degraded"
    elif profile_status in {
        "ready",
        "legacy_validation_pending",
        "discovery_required",
        "blocked_ai_unavailable",
    }:
        support_status = "pending"
    else:
        support_status = "blocked"
    runtime_status = (
        str(gate.status)
        if gate.allowed
        else (
            "exhausted"
            if str(gate.status) == "candidate_shortfall"
            or profile_status == "candidate_shortfall"
            else "budget_blocked"
            if str(gate.status) == "budget_blocked"
            else "blocked"
        )
    )
    return {
        "route_id": str(route["route_id"]),
        "route_key": str(route["route_key"]),
        "platform": str(route["platform"]),
        "target_type": str(route["target_type"]),
        "capability": str(route["capability"]),
        "mode": str(route["mode"]),
        "generation": int(route["generation"]),
        "support_status": support_status,
        "runtime_status": runtime_status,
        "runnable_slots": int(gate.runnable_count),
        "required_slots": int(route["required_slots"]),
        "min_runtime_healthy": int(route["min_runtime_healthy"]),
        "admission_mode": str(route.get("admission_mode") or "standard"),
        "publisher_count": int(
            len(
                {
                    str(slot.get("publisher") or "").casefold()
                    for slot in route.get("slots", [])
                    if slot.get("publisher")
                }
            )
        ),
        "per_run_cap_usd": float(route["per_run_cap_usd"]),
        "blocked_reason": (
            str(gate.error_code) if not gate.allowed and gate.error_code else None
        ),
        "updated_at": str(route["updated_at"]),
        "workflow": workflow,
    }


def _safe_price(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def _unit_prices(pricing: dict[str, Any]) -> list[float]:
    prices: list[float] = []
    direct = _safe_price(pricing.get("pricePerUnitUsd"))
    if direct is not None:
        prices.append(direct)
    tiered = pricing.get("tieredPricing")
    if isinstance(tiered, dict):
        for tier in tiered.values():
            if isinstance(tier, dict):
                value = _safe_price(tier.get("tieredPricePerUnitUsd"))
                if value is not None:
                    prices.append(value)
    event_pricing = pricing.get("pricingPerEvent")
    events = (
        event_pricing.get("actorChargeEvents")
        if isinstance(event_pricing, dict)
        else None
    )
    if isinstance(events, dict):
        for event in events.values():
            if not isinstance(event, dict):
                continue
            value = _safe_price(event.get("eventPriceUsd"))
            if value is not None:
                prices.append(value)
            tiers = event.get("eventTieredPricingUsd")
            if isinstance(tiers, dict):
                for tier in tiers.values():
                    tier_value = (
                        tier.get("tieredEventPriceUsd")
                        if isinstance(tier, dict)
                        else tier
                    )
                    value = _safe_price(tier_value)
                    if value is not None:
                        prices.append(value)
    return prices


def public_actor_ops_revision(revision: dict[str, Any]) -> dict[str, Any]:
    pricing = (
        revision.get("pricing")
        if isinstance(revision.get("pricing"), dict)
        else {}
    )
    listed = pricing.get("price_per_1000")
    model = (
        str(pricing.get("pricingModel") or pricing.get("model") or "").upper()
        or None
    )
    unit_prices = _unit_prices(pricing)
    minimum_cap = _safe_price(pricing.get("minimalMaxTotalChargeUsd"))
    minimum_charge = next(
        (
            value
            for key in (
                "minimumChargeUsd",
                "minChargeUsd",
                "minimumPriceUsd",
                "pricePerRunUsd",
            )
            if (value := _safe_price(pricing.get(key))) is not None
        ),
        None,
    )
    return {
        "revision_id": str(revision["revision_id"]),
        "actor_id": str(revision["actor_id"]),
        "actor_public_name": revision.get("actor_public_name"),
        "publisher": str(revision["publisher"]),
        "build_id": revision.get("build_id"),
        "build_number": revision.get("build_number"),
        "manifest_hash": revision.get("manifest_hash"),
        "execution_mode": str(revision.get("execution_mode") or "pinned"),
        "observed_manifest": bool(revision.get("observed_manifest") or False),
        "lifecycle": str(revision["lifecycle"]),
        "certification_progress": revision.get("certification_progress"),
        "listed_price_usd_per_1000": (
            float(listed)
            if isinstance(listed, (int, float)) and not isinstance(listed, bool)
            else None
        ),
        "pricing": {
            "model": model,
            "billing_unit": (
                "free"
                if model == "FREE"
                else "dataset_item"
                if model == "PRICE_PER_DATASET_ITEM"
                else "event"
                if model == "PAY_PER_EVENT"
                else "unknown"
            ),
            "unit_price_min_usd": min(unit_prices) if unit_prices else None,
            "unit_price_max_usd": max(unit_prices) if unit_prices else None,
            "minimum_charge_usd": minimum_charge,
            "minimum_run_cap_usd": minimum_cap,
        },
        "last_canary_at": revision.get("canary_passed_at"),
        "can_canary": str(revision["lifecycle"])
        in {"static_valid", "probationary"},
        "can_activate": str(revision["lifecycle"])
        in {"probationary", "certified", "legacy_builtin"}
        or (
            str(revision["lifecycle"]) == "superseded"
            and str(revision.get("superseded_from_lifecycle") or "")
            in {"probationary", "certified"}
        ),
    }


def public_canary_plan(plan: dict[str, Any]) -> dict[str, Any]:
    result = {
        key: plan[key]
        for key in (
            "schema_version",
            "run_id",
            "route_id",
            "route_key",
            "platform",
            "target_type",
            "capability",
            "mode",
            "generation",
            "status",
            "ready",
            "activation_ready",
            "plan_hash",
            "max_candidates",
            "max_total_charge_usd",
            "per_candidate_cap_usd",
            "successful_actor_count",
            "successful_publisher_count",
            "attempts_used",
            "attempts_remaining",
            "budget_remaining_usd",
            "items",
        )
    }
    for key in (
        "goal",
        "operation_slot",
        "selection_mode",
        "target_slot_count",
        "base_pool_hash",
        "required_success_count",
        "route_validation_cap_usd",
        "source_validation_cap_usd",
        "source_count",
        "source_validation_count",
    ):
        if key in plan:
            result[key] = plan[key]
    return result


def public_canary_batch(batch: dict[str, Any]) -> dict[str, Any]:
    result = {
        "schema_version": 2,
        **{
            key: batch[key]
            for key in (
                "batch_id",
                "route_id",
                "discovery_run_id",
                "approved_generation",
                "plan_hash",
                "max_candidates",
                "max_total_charge_usd",
                "per_candidate_cap_usd",
                "goal",
                "pool_stage_id",
                "status",
                "planned_count",
                "success_count",
                "publisher_count",
                "actual_cost_usd",
                "cost_final",
                "stop_reason",
                "created_at",
                "started_at",
                "completed_at",
                "updated_at",
            )
        },
        "items": [
            {
                key: item[key]
                for key in (
                    "ordinal",
                    "revision_id",
                    "status",
                    "semantic_outcome",
                    "authorized_cap_usd",
                    "actual_cost_usd",
                    "cost_final",
                    "preflight_checked_at",
                    "started_at",
                    "completed_at",
                    "actor_id",
                    "publisher",
                    "build_id",
                    "build_number",
                    "lifecycle",
                    "pricing",
                )
            }
            for item in batch["items"]
        ],
    }
    if batch.get("pool_stage") is not None:
        result["pool_stage"] = batch["pool_stage"]
    if batch.get("route_validation_cap_usd") is not None:
        result["route_validation_cap_usd"] = batch[
            "route_validation_cap_usd"
        ]
    return result
