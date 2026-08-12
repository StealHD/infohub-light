"""Typed dependencies shared by Service API routers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..auth import AuthSettings
from ..services.runtime_status import RuntimeStatusService
from ..services.storage_governance import StorageGovernanceService
from ..storage.service_store import ServiceStore


ReadinessCheck = Callable[[], None]


@dataclass(frozen=True, slots=True)
class ApiContext:
    """Request-independent services owned by the API composition root."""

    store: ServiceStore
    runtime_status: RuntimeStatusService
    storage_governance: StorageGovernanceService
    auth_settings: AuthSettings
    readiness_checks: tuple[ReadinessCheck, ...]
