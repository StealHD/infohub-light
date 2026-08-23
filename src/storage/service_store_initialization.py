"""Cross-process serialization for ServiceStore schema initialization."""

from __future__ import annotations

import fcntl
import os
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable


_LOCK_TIMEOUT_SECONDS = 30.0


def serialized_store_initialization(
    method: Callable[..., Any],
) -> Callable[..., Any]:
    """Keep concurrent API/Worker bootstrap from observing a partial schema."""

    @wraps(method)
    def wrapped(store: Any, *args: Any, **kwargs: Any) -> Any:
        lock_path = _lock_path(Path(store.db_path))
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            _acquire(descriptor)
            return method(store, *args, **kwargs)
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    return wrapped


def _lock_path(database_path: Path) -> Path:
    return database_path.with_name(f".{database_path.name}.initialize.lock")


def _acquire(descriptor: int) -> None:
    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
    while True:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise TimeoutError("service database initialization lock timed out")
            time.sleep(0.05)


__all__ = ["serialized_store_initialization"]
