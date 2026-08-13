"""Typed dependencies shared by Service API routers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..auth import AuthSettings
from ..mcp.remote_config import OpenClawChatSettings, RemoteMCPSettings
from ..services.feed_read import FeedReadService
from ..services.feed_schedule import FeedScheduleService
from ..services.job_queue import JobQueue
from ..services.apify_actor_resilience import ApifyActorResilienceService
from ..services.apify_key_pool import ApifyKeyPoolService
from ..services.media_cache import MediaCacheService
from ..services.notification_email_transport import WorkspaceEmailTransportService
from ..services.notification_targets import NotificationTargetService
from ..services.preferred_source_notifications import (
    PreferredSourceNotificationService,
)
from ..services.quota import QuotaService
from ..services.runtime_status import RuntimeStatusService
from ..services.secret_quota import ApifySecretQuotaService
from ..services.secret_store import SecretStore
from ..services.source_health import SourceHealthService
from ..services.source_schedule import SourceScheduleService
from ..services.storage_governance import StorageGovernanceService
from ..services.subscription_mutation import SubscriptionMutationService
from ..services.user_content_store import UserContentStore
from ..services.user_item_state import UserItemStateStore
from ..services.workspace_telegram_transport import WorkspaceTelegramTransportService
from ..storage.service_store import ServiceStore

if TYPE_CHECKING:
    from ..services.apify_actor_ops import ApifyActorOpsService


ReadinessCheck = Callable[[], None]
FeedWindowDays = Callable[[], int]
ApifyActorResilienceFactory = Callable[[str], ApifyActorResilienceService]
ApifyActorOpsFactory = Callable[[str], "ApifyActorOpsService"]
SourceSetupAvailability = Callable[
    [str], tuple[int, dict[str, tuple[str, str | None]]]
]
SecretProjection = Callable[[dict[str, Any]], dict[str, Any]]
SecretUsage = Callable[[dict[str, Any]], list[dict[str, str]]]
SecretMetadataValidator = Callable[[Any], tuple[str, str, str, str, str]]
BaseConfigReader = Callable[[], tuple[dict[str, Any], Any]]
BaseConfigWriter = Callable[[dict[str, Any]], None]
AiConnectionSynchronizer = Callable[[dict[str, Any], dict[str, Any]], None]
AiBaseUrlNormalizer = Callable[[str], str]


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
    apify_key_pool: ApifyKeyPoolService
    apify_actor_resilience_for: ApifyActorResilienceFactory
    apify_actor_ops_for: ApifyActorOpsFactory
    source_setup_availability: SourceSetupAvailability
    secret_values: SecretStore
    secret_quota: ApifySecretQuotaService
    source_health: SourceHealthService
    public_secret: SecretProjection
    secret_usage: SecretUsage
    validate_secret_metadata: SecretMetadataValidator
    read_base_config: BaseConfigReader
    write_base_config: BaseConfigWriter
    synchronize_ai_connection: AiConnectionSynchronizer
    normalize_ai_secret_base_url: AiBaseUrlNormalizer
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
    require_apify_actor_resilience: ReadinessCheck
    readiness_checks: tuple[ReadinessCheck, ...]
