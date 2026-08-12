from __future__ import annotations

from typing import cast

import pytest

from src.services.job_queue import JobQueue
from src.services.secret_store import SecretStore
from src.services.worker import run_worker_once
from src.services.worker_migration_gate import (
    WORKER_STARTUP_MIGRATIONS,
    first_required_worker_startup_migration,
)
from src.storage.service_store import ServiceStore


EXPECTED_MIGRATION_ORDER = [
    "apify_actor_routing_v13",
    "webhook_providers_v14",
    "multichannel_notifications_v15",
    "notification_targets_v16",
    "apify_actor_ops_v15",
    "apify_discovery_limits_v16",
    "apify_actor_canary_batches_v17",
    "apify_actor_pool_staging_v18",
    "apify_actor_manual_pool_selection_v19",
    "apify_actor_validation_tuning_v20",
    "apify_actor_resilience_v21",
]


class _MigrationProbe:
    def __init__(self, required_at: int | None = None) -> None:
        self.required_at = required_at
        self.calls: list[int] = []

    def __getattr__(self, name: str):
        names = [check_name for _migration, check_name in WORKER_STARTUP_MIGRATIONS]
        if name not in names:
            raise AttributeError(name)
        index = names.index(name)

        def required() -> bool:
            self.calls.append(index)
            return index == self.required_at

        return required


def test_worker_startup_migration_gate_keeps_compatibility_order() -> None:
    assert [name for name, _check in WORKER_STARTUP_MIGRATIONS] == (
        EXPECTED_MIGRATION_ORDER
    )


@pytest.mark.parametrize("required_at", range(len(EXPECTED_MIGRATION_ORDER)))
def test_worker_startup_migration_gate_returns_first_required(
    required_at: int,
) -> None:
    probe = _MigrationProbe(required_at)

    assert first_required_worker_startup_migration(
        cast(ServiceStore, probe)
    ) == EXPECTED_MIGRATION_ORDER[required_at]
    assert probe.calls == list(range(required_at + 1))


def test_worker_startup_migration_gate_returns_none_when_current(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    try:
        assert first_required_worker_startup_migration(store) is None
    finally:
        store.close()


def test_worker_startup_migration_gate_propagates_checker_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = _MigrationProbe()
    first_check = WORKER_STARTUP_MIGRATIONS[0][1]
    monkeypatch.setattr(
        probe,
        first_check,
        lambda: (_ for _ in ()).throw(RuntimeError("migration probe failed")),
    )

    with pytest.raises(RuntimeError, match="migration probe failed"):
        first_required_worker_startup_migration(cast(ServiceStore, probe))


def test_worker_startup_migration_gate_stops_before_provider_or_claim(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_check = WORKER_STARTUP_MIGRATIONS[0][1]
    monkeypatch.setattr(ServiceStore, first_check, lambda _store: True)

    def unexpected(*_args, **_kwargs):
        raise AssertionError("post-migration startup work must not run")

    monkeypatch.setattr(SecretStore, "load_into_environ", unexpected)
    monkeypatch.setattr(
        "src.services.worker.reconcile_all_apify_pools_sync",
        unexpected,
    )
    monkeypatch.setattr(JobQueue, "claim_next_job", unexpected)

    result = run_worker_once(
        data_dir=str(tmp_path),
        worker_id="migration-gate-worker",
    )

    assert result == {
        "ok": False,
        "error_code": "migration_required",
        "migration": "apify_actor_routing_v13",
    }
    store = ServiceStore(tmp_path)
    store.initialize()
    try:
        heartbeat = store.get_worker_heartbeat("migration-gate-worker")
        assert heartbeat is not None
        assert heartbeat["state"] == "idle"
        assert heartbeat["last_error_code"] == "migration_required"
    finally:
        store.close()
