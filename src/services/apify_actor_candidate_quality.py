"""Public Apify Store quality evidence for already-safe Actor candidates."""

from __future__ import annotations

from dataclasses import replace
import math
from typing import Any, Mapping, TypeVar


_QUALITY_KEY = "inteliscope_store_quality"
T = TypeVar("T")


def _number(value: Any, *, integer: bool = False) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return int(number) if integer else round(number, 3)


def _lookup(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = row.get(name)
        if value is not None:
            return value
    stats = row.get("stats")
    if isinstance(stats, Mapping):
        for name in names:
            value = stats.get(name)
            if value is not None:
                return value
    return None


def store_actor_quality(store_row: Mapping[str, Any] | None) -> dict[str, float | int | None]:
    """Normalize only public Store rating, review count, and usage count."""

    row = store_row if isinstance(store_row, Mapping) else {}
    raw_rating = _lookup(
        row, "actorReviewRating", "reviewRating", "rating", "ratingAverage", "ratingScore"
    )
    if isinstance(raw_rating, Mapping):
        raw_rating = _lookup(raw_rating, "average", "value", "score")
    rating = _number(raw_rating)
    if rating is not None and rating > 5:
        rating = None
    return {
        "rating": rating,
        "rating_count": _number(
            _lookup(
                row,
                "actorReviewCount",
                "reviewCount",
                "rating_count",
                "ratingCount",
                "reviewsCount",
                "totalReviews",
            ),
            integer=True,
        ),
        "user_count": _number(
            _lookup(row, "user_count", "userCount", "usersCount", "totalUsers", "totalUserCount"),
            integer=True,
        ),
    }


def with_store_quality(candidate: T, store_row: Mapping[str, Any] | None) -> T:
    """Attach an immutable normalized Store snapshot to a discovery candidate.

    The Store search response uses ``responseFormat=agent``, which strips the
    rating fields and minimizes ``stats``.  The candidate's own Actor detail is
    fetched with the full format and carries ``stats.actorReviewRating``, so
    merge the search row beneath the detail: search-only provenance is kept
    while ratings are read from the full ``stats`` object.
    """

    actor = dict(getattr(candidate, "actor"))
    source = {**store_row, **actor} if isinstance(store_row, Mapping) else dict(actor)
    actor[_QUALITY_KEY] = store_actor_quality(source)
    return replace(candidate, actor=actor)


def actor_store_quality(actor: Mapping[str, Any] | None) -> dict[str, float | int | None]:
    raw = (
        actor.get(_QUALITY_KEY, actor.get("store_quality"))
        if isinstance(actor, Mapping)
        else None
    )
    if raw is None and isinstance(actor, Mapping) and any(
        key in actor for key in ("rating", "rating_count", "user_count")
    ):
        raw = actor
    return store_actor_quality(raw if isinstance(raw, Mapping) else None)


def store_quality_evidence(actor: Mapping[str, Any] | None) -> dict[str, dict[str, float | int | None]]:
    quality = actor_store_quality(actor)
    return {"store_quality": quality} if any(value is not None for value in quality.values()) else {}


def quality_sort_key(
    actor_id: str,
    quality: Mapping[str, Any] | None,
    *,
    preferred: bool,
) -> tuple[int, float, int, int, str]:
    """Keep explicit legacy upgrades first, then rank Store quality deterministically."""

    normalized = store_actor_quality(quality)
    return (
        0 if preferred else 1,
        -float(normalized["rating"] or 0),
        -int(normalized["rating_count"] or 0),
        -int(normalized["user_count"] or 0),
        actor_id,
    )


def discovery_candidate_sort_key(
    actor_id: str,
    quality: Mapping[str, Any] | None,
    *,
    preferred: bool,
    output_schema_proves_items: bool,
) -> tuple[int, int, float, int, int, str]:
    """Prioritize safe output contracts, then public Store quality."""

    rank = quality_sort_key(actor_id, quality, preferred=preferred)
    return (rank[0], 0 if output_schema_proves_items else 1, *rank[1:])


__all__ = [
    "actor_store_quality",
    "discovery_candidate_sort_key",
    "quality_sort_key",
    "store_quality_evidence",
    "store_actor_quality",
    "with_store_quality",
]
