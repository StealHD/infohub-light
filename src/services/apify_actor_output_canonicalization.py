"""Deterministic finalization for bounded Actor Dataset content rows."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from typing import Protocol, TypeVar


class ActorOutputItem(Protocol):
    """The content identity and values required for Dataset canonicalization."""

    native_id: str
    published_at: datetime

    def model_dump(self, *, mode: str) -> dict[str, object]: ...


Item = TypeVar("Item", bound=ActorOutputItem)


def canonicalize_actor_output(
    items: Iterable[Item], *, max_items: int
) -> tuple[tuple[Item, ...], int]:
    """Deduplicate exact content identities and keep a newest-first bounded batch."""

    unique: dict[str, Item] = {}
    duplicate_rows = 0
    for item in items:
        existing = unique.get(item.native_id)
        if existing is not None:
            duplicate_rows += 1
            if _preference(item) <= _preference(existing):
                continue
        unique[item.native_id] = item
    return (
        tuple(
            sorted(
                unique.values(),
                key=lambda item: (item.published_at, item.native_id),
                reverse=True,
            )[:max_items]
        ),
        duplicate_rows,
    )


def _preference(item: ActorOutputItem) -> tuple[datetime, str]:
    return (
        item.published_at,
        json.dumps(
            item.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


__all__ = ["canonicalize_actor_output"]
