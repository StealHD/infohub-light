from __future__ import annotations

import logging

from src.services import apify_actor_auto_pool, apify_actor_ops
from src.services.worker_actor_auto_pool import (
    advance_auto_pool_after_canary,
    advance_auto_pool_after_discovery,
)


def _patch_ops(monkeypatch, sentinel):
    monkeypatch.setattr(
        apify_actor_ops,
        "ApifyActorOpsService",
        lambda _store, *, workspace_id: (sentinel, workspace_id),
    )


def test_worker_auto_pool_continuations_receive_validated_references(monkeypatch) -> None:
    sentinel = object()
    calls = []
    _patch_ops(monkeypatch, sentinel)
    monkeypatch.setattr(
        apify_actor_auto_pool,
        "advance_after_canary",
        lambda ops, reference_id, *, admin_user_id: calls.append(
            ("canary", ops, reference_id, admin_user_id)
        ),
    )
    monkeypatch.setattr(
        apify_actor_auto_pool,
        "advance_after_discovery",
        lambda ops, reference_id, *, admin_user_id: calls.append(
            ("discovery", ops, reference_id, admin_user_id)
        ),
    )
    job = {"id": "job-1", "workspace_id": "workspace-1", "user_id": "admin-1"}

    advance_auto_pool_after_canary(job, object(), "batch-1")
    advance_auto_pool_after_discovery(job, object(), "run-1")

    assert calls == [
        ("canary", (sentinel, "workspace-1"), "batch-1", "admin-1"),
        ("discovery", (sentinel, "workspace-1"), "run-1", "admin-1"),
    ]


def test_worker_auto_pool_continuation_failure_is_best_effort(
    monkeypatch,
    caplog,
) -> None:
    _patch_ops(monkeypatch, object())
    monkeypatch.setattr(
        apify_actor_auto_pool,
        "advance_after_canary",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("failed")),
    )

    with caplog.at_level(logging.WARNING):
        advance_auto_pool_after_canary(
            {"id": "job-2", "workspace_id": "workspace-1", "user_id": "admin-1"},
            object(),
            "batch-2",
        )

    assert "auto_pool_advance_after_canary_failed job_id=job-2" in caplog.text
