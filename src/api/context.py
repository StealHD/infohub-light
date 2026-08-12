"""Typed dependencies shared by Service API routers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..auth import AuthSettings
from ..mcp.remote_config import OpenClawChatSettings, RemoteMCPSettings
from ..services.job_queue import JobQueue
from ..services.feed_read import FeedReadService
from ..services.media_cache import MediaCacheService
from ..services.quota import QuotaService
from ..services.runtime_status import RuntimeStatusService
from ..services.storage_governance import StorageGovernanceService
from ..services.user_content_store import UserContentStore
from ..services.user_item_state import UserItemStateStore
from ..storage.service_store import ServiceStore


ReadinessCheck = Callable[[], None]
FeedWindowDays = Callable[[], int]


@dataclass(frozen=True, slots=True)
class ApiContext:
    """Request-independent services owned by the API composition root."""

    store: ServiceStore
    job_queue: JobQueue
    feed_reader: FeedReadService
    item_state: UserItemStateStore
    user_content: UserContentStore
    media_cache: MediaCacheService
    data_path: Path
    feed_window_days: FeedWindowDays
    quota: QuotaService
    runtime_status: RuntimeStatusService
    storage_governance: StorageGovernanceService
    auth_settings: AuthSettings
    remote_mcp_settings: RemoteMCPSettings
    openclaw_chat_settings: OpenClawChatSettings
    readiness_checks: tuple[ReadinessCheck, ...]
