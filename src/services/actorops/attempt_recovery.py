"""Deterministic ActorOps v2 Attempt identity and frozen-request helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Mapping

from .ports import FetchWindow


def stable_digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def attempt_identity(
    workspace_id: str,
    logical_job_id: str,
    source_id: str | None,
    binding_version: int | None,
    candidate_id: str,
    *,
    kind: str,
) -> str:
    return stable_digest({
        "workspace_id": workspace_id,
        "logical_job_id": logical_job_id,
        "source_id": source_id or "",
        "binding_version": binding_version or 0,
        "candidate_id": candidate_id,
        "kind": kind,
    })


def attempt_group_identity(
    workspace_id: str,
    logical_job_id: str,
    source_id: str | None,
    binding_version: int | None,
    *,
    kind: str,
) -> str:
    return stable_digest({
        "workspace_id": workspace_id,
        "logical_job_id": logical_job_id,
        "source_id": source_id or "",
        "binding_version": binding_version or 0,
        "kind": kind,
    })


def request_fingerprint(
    *,
    target_fingerprint: str,
    candidate: object,
    route_cap_usd: float,
    window: FetchWindow,
) -> str:
    return stable_digest({
        "target_fingerprint": target_fingerprint,
        "actor_id": getattr(candidate, "actor_id"),
        "build_id": getattr(candidate, "build_id"),
        "build_number": getattr(candidate, "build_number"),
        "manifest_hash": getattr(candidate, "manifest_hash"),
        "route_cap_usd": float(route_cap_usd),
        "window_since": window.since.isoformat(),
        "window_until": window.until.isoformat() if window.until else None,
        "max_items": window.max_items,
    })


def frozen_window(row: Mapping[str, object]) -> FetchWindow:
    since = datetime.fromisoformat(str(row["window_since"]))
    raw_until = row["window_until"]
    until = datetime.fromisoformat(str(raw_until)) if raw_until else None
    return FetchWindow(max_items=int(row["max_items"]), since=since, until=until)


__all__ = [
    "attempt_group_identity",
    "attempt_identity",
    "frozen_window",
    "request_fingerprint",
    "stable_digest",
]
