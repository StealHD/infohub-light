"""Safe public Apify Store metadata normalization for exact v2 Candidates."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


_SPACE = re.compile(r"\s+")
_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~/-]{0,159}$")
_PRICE_KEYS = (
    "pricingModel", "unitName", "pricePerUnitUsd", "minimumChargeUsd",
    "pricePerRunUsd", "trialMinutes", "pricingPeriod",
)


@dataclass(frozen=True, slots=True)
class StoreMetadata:
    actor_slug: str
    display_name: str
    short_description: str | None
    developer_name: str | None
    maintained_by_apify: bool
    rating: float | None
    review_count: int | None
    bookmark_count: int | None
    total_users: int | None
    monthly_active_users: int | None
    pricing: tuple[dict[str, object], ...]
    last_modified_at: str | None


def normalize_store_metadata(
    value: Mapping[str, Any], *, fallback_slug: str, fallback_name: str = ""
) -> StoreMetadata:
    """Allowlist public summary facts; raw Store JSON never reaches storage."""

    stats = value.get("stats") if isinstance(value.get("stats"), Mapping) else {}
    username = _text(value.get("username") or value.get("userUsername"), 80)
    name = _text(value.get("name") or value.get("actorName"), 80)
    supplied_slug = _text(value.get("actorId") or value.get("id"), 160)
    slug = supplied_slug.replace("~", "/") if supplied_slug else "/".join(part for part in (username, name) if part)
    if not _SLUG.fullmatch(slug or ""):
        slug = _safe_slug(fallback_slug)
    if not slug:
        raise ValueError("actorops_store_metadata_slug_invalid")
    display = _text(value.get("title") or value.get("displayName") or name or fallback_name, 160)
    if not display:
        display = slug.rsplit("/", 1)[-1]
    developer = _text(value.get("userFullName") or value.get("developerName") or username, 120)
    pricing = _pricing(value.get("pricingInfos"))
    return StoreMetadata(
        actor_slug=slug,
        display_name=display,
        short_description=_text(value.get("description"), 600),
        developer_name=developer or None,
        maintained_by_apify=bool(value.get("isApifyMaintained") or value.get("isMaintainedByApify") or username.casefold() == "apify"),
        rating=_rating(_value(value, stats, "actorReviewRating", "reviewRating", "rating", "ratingAverage")),
        review_count=_integer(_value(value, stats, "actorReviewCount", "reviewCount", "ratingCount", "reviewsCount")),
        bookmark_count=_integer(_value(value, stats, "bookmarkCount", "bookmarksCount", "bookmarkedCount")),
        total_users=_integer(_value(value, stats, "totalUsers", "userCount", "usersCount")),
        monthly_active_users=_integer(_value(value, stats, "monthlyActiveUsers", "monthlyUsers", "monthlyActiveUserCount")),
        pricing=pricing,
        last_modified_at=_text(value.get("modifiedAt") or value.get("lastModifiedAt"), 64) or None,
    )


def pricing_json(metadata: StoreMetadata) -> str:
    return json.dumps(list(metadata.pricing), separators=(",", ":"), sort_keys=True)


def _safe_slug(value: str) -> str:
    return value.strip().replace("~", "/") if _SLUG.fullmatch(value.strip().replace("~", "/")) else ""


def _text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return _SPACE.sub(" ", value.replace("\x00", " ").strip())[:limit]


def _value(first: Mapping[str, Any], second: Mapping[str, Any], *keys: str) -> object:
    for key in keys:
        if first.get(key) is not None:
            return first[key]
        if second.get(key) is not None:
            return second[key]
    return None


def _integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    number = int(value)
    return number if 0 <= number <= 9_223_372_036_854_775_807 else None


def _rating(value: object) -> float | None:
    if isinstance(value, Mapping):
        value = value.get("average") or value.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    number = round(float(value), 3)
    return number if 0 <= number <= 5 else None


def _pricing(value: object) -> tuple[dict[str, object], ...]:
    rows = value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()
    result: list[dict[str, object]] = []
    for row in rows[:8]:
        if not isinstance(row, Mapping):
            continue
        item: dict[str, object] = {}
        for key in _PRICE_KEYS:
            raw = row.get(key)
            if key in {"pricingModel", "unitName", "pricingPeriod"}:
                normalized = _text(raw, 80)
                if normalized:
                    item[key] = normalized
            elif isinstance(raw, (int, float)) and not isinstance(raw, bool) and math.isfinite(float(raw)) and float(raw) >= 0:
                item[key] = round(float(raw), 6)
        if item:
            result.append(item)
    return tuple(result)


__all__ = ["StoreMetadata", "normalize_store_metadata", "pricing_json"]
