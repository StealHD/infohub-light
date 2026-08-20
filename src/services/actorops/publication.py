"""Safe publication proof transport across the shared acquisition cache."""

from __future__ import annotations

from typing import Any

from .ports import PublicationProof
from .repository import ActorOpsRepository


class ActorOpsV2RoutedList(list):
    def __init__(self, items: list[Any], proof: dict[str, Any]) -> None:
        super().__init__(items)
        self._actorops_v2_publication_proof = dict(proof)


def v2_proof_payload(
    proof: PublicationProof,
    *,
    latest_published_at: str | None,
    latest_item_id_hash: str | None,
) -> dict[str, Any]:
    return {
        "version": 2,
        "workspace_id": proof.workspace_id,
        "route_id": proof.route_id,
        "source_id": proof.source_id,
        "target_fingerprint": proof.target_fingerprint,
        "binding_version": proof.binding_version,
        "candidate_id": proof.candidate_id,
        "candidate_generation": proof.candidate_generation,
        "latest_published_at": latest_published_at,
        "latest_item_id_hash": latest_item_id_hash,
    }


def proof_from_items(items: Any) -> dict[str, Any] | None:
    v2 = getattr(items, "_actorops_v2_publication_proof", None)
    if isinstance(v2, dict) and _valid_v2(v2):
        return dict(v2)
    if str(getattr(items, "_apify_actor_semantic_outcome", "") or "") != "advanced":
        return None
    route_generation = getattr(items, "_apify_actor_route_generation", None)
    proof = {
        "workspace_id": getattr(items, "_apify_actor_workspace_id", None),
        "source_id": getattr(items, "_apify_actor_source_id", None),
        "candidate_id": getattr(items, "_apify_actor_candidate_id", None),
        "latest_published_at": getattr(items, "_apify_actor_latest_published_at", None),
        "latest_item_id_hash": getattr(items, "_apify_actor_latest_item_id_hash", None),
        "route_generation": route_generation,
        "semantic_outcome": "advanced",
    }
    required = ("workspace_id", "source_id", "candidate_id", "latest_published_at", "latest_item_id_hash")
    if (
        not isinstance(route_generation, int)
        or any(not isinstance(proof[key], str) or not str(proof[key]).strip() for key in required)
        or len(str(proof["latest_item_id_hash"])) != 64
    ):
        return None
    return proof


def with_publication_proof(items: list[Any], proof: dict[str, Any] | None) -> list[Any]:
    if proof is None:
        return items
    if proof.get("version") == 2 and _valid_v2(proof):
        return ActorOpsV2RoutedList(items, proof)
    from ..apify_actor_route import ApifyActorRoutedList

    return ApifyActorRoutedList(
        items,
        route_generation=int(proof["route_generation"]),
        workspace_id=str(proof["workspace_id"]),
        source_id=str(proof["source_id"]),
        candidate_id=str(proof["candidate_id"]),
        latest_published_at=str(proof["latest_published_at"]),
        latest_item_id_hash=str(proof["latest_item_id_hash"]),
        semantic_outcome="advanced",
    )


def assert_cached_v2_proof(store: Any, proof: dict[str, Any]) -> None:
    if not _valid_v2(proof):
        raise ValueError("invalid ActorOps v2 publication proof")
    repository = ActorOpsRepository(store.connect(), str(proof["workspace_id"]))
    repository.assert_publishable(publication_proof(proof))


def capture_result(service: Any, items: Any) -> None:
    capture = getattr(service, "capture_publication_result", None)
    if callable(capture):
        capture(items)


def publish_pending_watermarks(
    actor_ops: Any,
    actor_route: Any,
    proofs: list[dict[str, str]],
    *,
    connection: Any,
) -> None:
    actor_service = actor_ops if actor_ops is not None else actor_route
    publish_v2 = getattr(actor_service, "publish_pending_successes", None)
    if callable(publish_v2):
        publish_v2(connection=connection)
    if not proofs:
        return
    if actor_service is None:
        raise RuntimeError("Actor watermark proof is missing its runtime")
    from ..apify_actor_resilience import ApifyActorResilienceService

    for proof in proofs:
        ApifyActorResilienceService(
            actor_service.store, workspace_id=proof["workspace_id"]
        ).publish_source_advance(
            proof["source_id"],
            candidate_id=proof["candidate_id"],
            latest_published_at=proof["latest_published_at"],
            latest_item_id_hash=proof["latest_item_id_hash"],
            connection=connection,
        )


def publication_proof(value: dict[str, Any]) -> PublicationProof:
    if not _valid_v2(value):
        raise ValueError("invalid ActorOps v2 publication proof")
    return PublicationProof(
        workspace_id=str(value["workspace_id"]),
        route_id=str(value["route_id"]),
        source_id=str(value["source_id"]),
        target_fingerprint=str(value["target_fingerprint"]),
        binding_version=int(value["binding_version"]),
        candidate_id=(str(value["candidate_id"]) if value.get("candidate_id") else None),
        candidate_generation=(
            int(value["candidate_generation"])
            if value.get("candidate_generation") is not None
            else None
        ),
    )


def _valid_v2(value: dict[str, Any]) -> bool:
    required = ("workspace_id", "route_id", "source_id", "target_fingerprint")
    latest_at = value.get("latest_published_at")
    latest_hash = value.get("latest_item_id_hash")
    return bool(
        value.get("version") == 2
        and all(isinstance(value.get(key), str) and str(value[key]).strip() for key in required)
        and len(str(value["target_fingerprint"])) == 64
        and isinstance(value.get("binding_version"), int)
        and int(value["binding_version"]) >= 1
        and (
            (latest_at is None and latest_hash is None)
            or (
                isinstance(latest_at, str)
                and bool(latest_at.strip())
                and isinstance(latest_hash, str)
                and len(latest_hash) == 64
            )
        )
    )


__all__ = [
    "ActorOpsV2RoutedList",
    "assert_cached_v2_proof",
    "capture_result",
    "proof_from_items",
    "publication_proof",
    "publish_pending_watermarks",
    "v2_proof_payload",
    "with_publication_proof",
]
