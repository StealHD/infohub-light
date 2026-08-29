"""Bounded quality ranking for public Actor Store search results."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from .ports import DiscoveryActorMatch


_MAX_SEARCH_ROWS = 80
DISCOVERY_SEARCH_STRATEGY = "multi-query-quality-v2"


def ranked_catalog_matches(
    groups: Iterable[Sequence[str | DiscoveryActorMatch]], *, limit: int
) -> tuple[DiscoveryActorMatch, ...]:
    """Merge all queries, deduplicate Actors, then rank by public quality."""

    matches: dict[str, DiscoveryActorMatch] = {}
    order: dict[str, int] = {}
    inspected = 0
    for group in groups:
        for raw in group:
            if inspected >= _MAX_SEARCH_ROWS:
                break
            inspected += 1
            match = _match(raw)
            if match is None:
                continue
            current = matches.get(match.actor_id)
            if current is None:
                order[match.actor_id] = len(order)
                matches[match.actor_id] = match
            else:
                matches[match.actor_id] = _merge(current, match)
        if inspected >= _MAX_SEARCH_ROWS:
            break
    ranked = sorted(
        matches.values(),
        key=lambda item: (
            -item.total_users,
            -item.rating,
            -item.review_count,
            -item.query_hits,
            -item.bookmark_count,
            order[item.actor_id],
        ),
    )
    return tuple(ranked[: max(0, int(limit))])


def cursor_match(value: object) -> DiscoveryActorMatch | None:
    if isinstance(value, str):
        return _match(value)
    if not isinstance(value, Mapping):
        return None
    actor_id = str(value.get("actor_id") or "").strip()
    if not actor_id:
        return None
    return DiscoveryActorMatch(
        actor_id=actor_id,
        total_users=_integer(value.get("total_users")),
        rating=_rating(value.get("rating")),
        review_count=_integer(value.get("review_count")),
        bookmark_count=_integer(value.get("bookmark_count")),
        query_hits=max(1, _integer(value.get("query_hits"))),
        display_name=_text(value.get("display_name"), 160),
        short_description=_text(value.get("short_description"), 240),
    )


def match_cursor(value: DiscoveryActorMatch, *, rank: int) -> dict[str, object]:
    return {
        "actor_id": value.actor_id,
        "total_users": value.total_users,
        "rating": value.rating,
        "review_count": value.review_count,
        "bookmark_count": value.bookmark_count,
        "query_hits": value.query_hits,
        "catalog_rank": int(rank),
        "display_name": value.display_name,
        "short_description": value.short_description,
    }


def candidate_quality_key(value: Mapping[str, object]) -> tuple[object, ...]:
    return (
        _integer(value.get("catalog_rank")),
        str(value.get("publisher") or ""),
        str(value.get("candidate_id") or ""),
    )


def _match(value: str | DiscoveryActorMatch) -> DiscoveryActorMatch | None:
    if isinstance(value, DiscoveryActorMatch):
        return value if value.actor_id.strip() else None
    actor_id = str(value).strip()
    return DiscoveryActorMatch(actor_id) if actor_id else None


def _merge(
    first: DiscoveryActorMatch, second: DiscoveryActorMatch
) -> DiscoveryActorMatch:
    return DiscoveryActorMatch(
        actor_id=first.actor_id,
        total_users=max(first.total_users, second.total_users),
        rating=max(first.rating, second.rating),
        review_count=max(first.review_count, second.review_count),
        bookmark_count=max(first.bookmark_count, second.bookmark_count),
        query_hits=first.query_hits + second.query_hits,
        display_name=first.display_name or second.display_name,
        short_description=first.short_description or second.short_description,
    )


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(value))


def _rating(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return min(5.0, max(0.0, float(value)))


def _text(value: object, limit: int) -> str:
    return str(value).strip()[:limit] if isinstance(value, str) else ""


__all__ = [
    "DISCOVERY_SEARCH_STRATEGY",
    "candidate_quality_key",
    "cursor_match",
    "match_cursor",
    "ranked_catalog_matches",
]
