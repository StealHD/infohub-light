"""Deterministic identity for one immutable Actor/Build/Manifest Candidate."""

from __future__ import annotations

import hashlib


def candidate_id(
    *, route_id: str, actor_id: str, build_id: str,
    build_number: str, manifest_identity: str,
) -> str:
    value = "\x1f".join((route_id, actor_id, build_id, build_number))
    digest = hashlib.sha256(
        f"{value}\x1f{manifest_identity}".encode("utf-8")
    ).hexdigest()
    return f"candidate_{digest[:24]}"


__all__ = ["candidate_id"]
