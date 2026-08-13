"""Bounded Store-search evidence used by Actor discovery."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Mapping, TypeVar


T = TypeVar("T")


async def collect_store_candidates(
    metadata_client: Any,
    *,
    queries: Sequence[str],
    preferred_actor_ids: Sequence[str],
    actor_id_from_row: Callable[[Mapping[str, Any]], str | None],
    maybe_await: Callable[[T | Awaitable[T]], Awaitable[T]],
) -> tuple[dict[str, Mapping[str, Any]], set[str]]:
    """Return bounded direct candidates plus Store-search runnable provenance."""

    store_hits: dict[str, Mapping[str, Any]] = {
        actor_id: {"actorId": actor_id} for actor_id in preferred_actor_ids
    }
    store_search_actor_ids: set[str] = set()
    for query in queries:
        for row in await maybe_await(metadata_client.search_store(query)):
            actor_id = actor_id_from_row(row)
            if actor_id:
                # The Store request excludes unrunnable Actors. Its detail
                # response no longer reliably retains legacy runnable flags.
                store_search_actor_ids.add(actor_id)
                store_hits.setdefault(actor_id, row)
    return store_hits, store_search_actor_ids


def require_runnable_evidence(
    actor: Mapping[str, Any],
    *,
    allow_store_runnable_omission: bool,
    reject: Callable[[str], Exception],
) -> None:
    """Require a positive flag, or Store provenance that excludes unrunnable Actors."""

    if actor.get("isRunnable") is True or actor.get("canRun") is True:
        return
    if actor.get("isRunnable") is False or actor.get("canRun") is False:
        raise reject("actor_not_runnable")
    if not allow_store_runnable_omission:
        raise reject("actor_runnable_unverifiable")
