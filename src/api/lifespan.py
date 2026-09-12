"""Application resource lifecycle helpers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncContextManager, Callable, Protocol


class ClosableStore(Protocol):
    def close(self) -> None: ...


class SessionManager(Protocol):
    def run(self) -> AsyncContextManager[Any]: ...


def build_service_lifespan(
    store: ClosableStore,
    session_manager: SessionManager | None,
) -> Callable[[Any], AsyncContextManager[None]]:
    """Close SQLite resources after optional Remote MCP shutdown."""

    @asynccontextmanager
    async def app_lifespan(_app: Any):
        from ..services.agent_connections.permission_upgrade import run_existing
        import threading
        import asyncio
        context = getattr(_app.state, 'api_context', None)
        upgrade = threading.Thread(target=run_existing, args=(context,), daemon=True, name='agent-permission-upgrade') if context else None
        if upgrade:
            upgrade.start()
        try:
            if session_manager is None:
                yield
            else:
                async with session_manager.run():
                    yield
        finally:
            if upgrade:
                await asyncio.to_thread(upgrade.join)
            store.close()

    return app_lifespan
