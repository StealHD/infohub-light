"""Typed dependencies shared by Service API routers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..auth import AuthSettings
from ..mcp.remote_config import OpenClawChatSettings, RemoteMCPSettings
from ..services.job_queue import JobQueue
from ..services.quota import QuotaService
from ..services.runtime_status import RuntimeStatusService
from ..services.storage_governance import StorageGovernanceService
from ..storage.service_store import ServiceStore


ReadinessCheck = Callable[[], None]


@dataclass(frozen=True, slots=True)
class ApiContext:
    """Request-independent services owned by the API composition root."""

    store: ServiceStore
    job_queue: JobQueue
    quota: QuotaService
    runtime_status: RuntimeStatusService
    storage_governance: StorageGovernanceService
    auth_settings: AuthSettings
    remote_mcp_settings: RemoteMCPSettings
    openclaw_chat_settings: OpenClawChatSettings
    readiness_checks: tuple[ReadinessCheck, ...]
