"""Typed dependencies shared by Service API routers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..auth import AuthSettings
from ..mcp.remote_config import OpenClawChatSettings, RemoteMCPSettings
from ..services.feed_read import FeedReadService
from ..services.feed_schedule import FeedScheduleService
from ..services.job_queue import JobQueue
from ..services.media_cache import MediaCacheService
from ..services.notification_email_transport import WorkspaceEmailTransportService
from ..services.notification_targets import NotificationTargetService
from ..services.preferred_source_notifications import (
    PreferredSourceNotificationService,
)
from ..services.quota import QuotaService
from ..services.runtime_status import RuntimeStatusService
from ..services.source_schedule import SourceScheduleService
from ..services.storage_governance import StorageGovernanceService
from ..services.subscription_mutation import SubscriptionMutationService
from ..services.user_content_store import UserContentStore
from ..services.user_item_state import UserItemStateStore
from ..services.workspace_telegram_transport import WorkspaceTelegramTransportService
from ..storage.service_store import ServiceStore


ReadinessCheck = Callable[[], None]
FeedWindowDays = Callable[[], int]


@dataclass(frozen=True, slots=True)
class ApiContext:
    """Request-independent services owned by the API composition root."""

    store: ServiceStore
    job_queue: JobQueue
    feed_reader: FeedReadService
    feed_schedules: FeedScheduleService
    source_schedules: SourceScheduleService
    subscription_mutations: SubscriptionMutationService
    item_state: UserItemStateStore
    user_content: UserContentStore
    media_cache: MediaCacheService
    data_path: Path
    feed_window_days: FeedWindowDays
    quota: QuotaService
    runtime_status: RuntimeStatusService
    storage_governance: StorageGovernanceService
    preferred_source_notifications: PreferredSourceNotificationService
    notification_targets: NotificationTargetService
    workspace_email_transport: WorkspaceEmailTransportService
    workspace_telegram_transport: WorkspaceTelegramTransportService
    auth_settings: AuthSettings
    remote_mcp_settings: RemoteMCPSettings
    openclaw_chat_settings: OpenClawChatSettings
    require_webhook_providers: ReadinessCheck
    require_notification_channels: ReadinessCheck
    require_notification_targets: ReadinessCheck
    readiness_checks: tuple[ReadinessCheck, ...]
