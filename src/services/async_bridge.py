"""Small boundary for calling async transports from synchronous services."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from typing import Any


def run_coroutine_sync(coroutine: Coroutine[Any, Any, Any]) -> Any:
    """Run a coroutine even when the caller already owns an event loop."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)

    result: list[Any] = []
    failure: list[BaseException] = []

    def runner() -> None:
        try:
            result.append(asyncio.run(coroutine))
        except BaseException as exc:  # forwarded to the synchronous caller
            failure.append(exc)

    thread = threading.Thread(target=runner, name="sync-async-bridge", daemon=True)
    thread.start()
    thread.join()
    if failure:
        raise failure[0]
    return result[0] if result else None
