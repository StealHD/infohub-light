"""Run schema mapping independently so one Actor cannot poison another."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from .discovery_search import candidate_quality_key
from .ports import (
    DiscoveryAiMapper,
    DiscoveryAiResult,
    DiscoveryMapping,
    DiscoveryRevision,
)


async def map_candidates_individually(
    mapper: DiscoveryAiMapper,
    route_key: object,
    revisions: Sequence[DiscoveryRevision],
) -> DiscoveryAiResult:
    mappings: dict[str, DiscoveryMapping] = {}
    results: list[DiscoveryAiResult] = []
    for revision in revisions:
        try:
            result = await mapper.map(route_key, (revision,))
        except Exception:
            mappings[revision.actor_id] = DiscoveryMapping(
                None, "actorops_discovery_ai_unavailable"
            )
            continue
        results.append(result)
        mappings[revision.actor_id] = result.mappings.get(
            revision.actor_id,
            DiscoveryMapping(None, "actorops_discovery_ai_mapping_missing"),
        )
    return DiscoveryAiResult(
        mappings=mappings,
        config_id=_first(results, "config_id"),
        input_tokens=_sum(results, "input_tokens"),
        completion_tokens=_sum(results, "completion_tokens"),
        reasoning_tokens=_sum(results, "reasoning_tokens"),
        finish_reason=_finish_reason(results),
        latency_ms=_sum(results, "latency_ms"),
        response_bytes=_sum(results, "response_bytes"),
    )


async def resolve_ranked_candidates(
    mapper: DiscoveryAiMapper | None,
    route_key: object,
    unresolved: Sequence[tuple[DiscoveryRevision, dict[str, object]]],
    descriptors: list[dict[str, object]],
    *,
    map_mapping: Callable[
        [dict[str, object], DiscoveryMapping, DiscoveryRevision],
        dict[str, object],
    ],
    pending: Callable[[dict[str, object], str], dict[str, object]],
    max_mappings: int,
    max_route_candidates: int,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Map only as far down the quality ordering as the Route needs."""

    pairs = tuple(unresolved[:max_mappings])
    results: list[DiscoveryAiResult] = []
    processed = 0
    if mapper is not None:
        for revision, ref in pairs:
            cutoff = _route_cutoff_rank(descriptors, max_route_candidates)
            if cutoff is not None and _rank(ref) > cutoff:
                break
            result = await map_candidates_individually(mapper, route_key, (revision,))
            results.append(result)
            processed += 1
            mapping = result.mappings.get(revision.actor_id)
            descriptors.append(
                map_mapping(ref, mapping, revision)
                if mapping and mapping.manifest_json
                else pending(
                    ref,
                    mapping.rejection_code
                    if mapping is not None
                    and mapping.rejection_code
                    else "actorops_discovery_ai_mapping_missing",
                )
            )
            cutoff = _route_cutoff_rank(descriptors, max_route_candidates)
            if cutoff is not None and _rank(ref) >= cutoff:
                break
    else:
        descriptors.extend(
            pending(ref, "actorops_discovery_mapping_pending") for _, ref in pairs
        )
        processed = len(pairs)

    cutoff = _route_cutoff_rank(descriptors, max_route_candidates)
    if cutoff is None:
        descriptors.extend(
            pending(ref, "actorops_discovery_mapping_pending")
            for _, ref in pairs[processed:]
        )
        descriptors.extend(
            pending(ref, "actorops_discovery_mapping_pending")
            for _, ref in unresolved[max_mappings:]
        )
    else:
        descriptors = [item for item in descriptors if _rank(item) <= cutoff]
    return descriptors, _ai_metrics(results)


def _sum(results: Sequence[DiscoveryAiResult], field: str) -> int | None:
    values = [getattr(result, field) for result in results]
    known = [int(value) for value in values if value is not None]
    return sum(known) if known else None


def _first(results: Sequence[DiscoveryAiResult], field: str) -> str | None:
    return next(
        (
            str(value)
            for result in results
            if (value := getattr(result, field)) is not None
        ),
        None,
    )


def _finish_reason(results: Sequence[DiscoveryAiResult]) -> str | None:
    reasons = tuple(
        str(result.finish_reason)
        for result in results
        if result.finish_reason is not None
    )
    return "length" if "length" in reasons else reasons[-1] if reasons else None


def _route_candidate(item: dict[str, object]) -> bool:
    return bool(
        item.get("status") == "accepted"
        or item.get("rejection_code")
        == "actorops_discovery_output_sample_required"
    )


def _rank(item: dict[str, object]) -> tuple[object, ...]:
    return candidate_quality_key(item)


def _route_cutoff_rank(
    items: Sequence[dict[str, object]], max_route_candidates: int
) -> tuple[object, ...] | None:
    ranks = sorted(_rank(item) for item in items if _route_candidate(item))
    return (
        ranks[max_route_candidates - 1]
        if len(ranks) >= max_route_candidates
        else None
    )


def _ai_metrics(results: Sequence[DiscoveryAiResult]) -> dict[str, object]:
    if not results:
        return {}
    values: dict[str, object] = {
        "input_tokens": _sum(results, "input_tokens"),
        "completion_tokens": _sum(results, "completion_tokens"),
        "reasoning_tokens": _sum(results, "reasoning_tokens"),
        "finish_reason": _finish_reason(results),
        "latency_ms": _sum(results, "latency_ms"),
        "response_bytes": _sum(results, "response_bytes"),
    }
    if (config_id := _first(results, "config_id")) is not None:
        values["config_id"] = config_id
    return values


__all__ = ["map_candidates_individually", "resolve_ranked_candidates"]
