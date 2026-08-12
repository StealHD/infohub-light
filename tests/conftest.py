from __future__ import annotations

import sys
from threading import Lock
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def close_service_stores(monkeypatch):
    """Keep every per-test store alive, then close all SQLite connections."""

    from src.storage.service_store import ServiceStore

    instances: list[ServiceStore] = []
    lock = Lock()
    original_init = ServiceStore.__init__

    def tracked_init(instance, *args, **kwargs):
        original_init(instance, *args, **kwargs)
        with lock:
            instances.append(instance)

    monkeypatch.setattr(ServiceStore, "__init__", tracked_init)
    yield
    with lock:
        tracked = list(reversed(instances))
    for instance in tracked:
        instance.close()
