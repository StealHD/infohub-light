"""Small-group quota checks for job creation and usage tracking."""

from __future__ import annotations

from datetime import datetime, time, timezone

from ..storage.service_store import ServiceStore


class QuotaExceeded(ValueError):
    """Raised when a user exceeds a configured service quota."""

    code = "quota_exceeded"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class QuotaService:
    """Enforces simple per-user daily limits for the MVP service API."""

    def __init__(
        self,
        store: ServiceStore,
        *,
        max_fetch_jobs_per_day: int = 100,
        max_sources_per_user: int = 100,
        max_ai_items_per_day: int = 1000,
    ) -> None:
        self.store = store
        self.max_fetch_jobs_per_day = int(max_fetch_jobs_per_day)
        self.max_sources_per_user = int(max_sources_per_user)
        self.max_ai_items_per_day = int(max_ai_items_per_day)

    @staticmethod
    def _today_start() -> datetime:
        now = datetime.now(timezone.utc)
        return datetime.combine(now.date(), time.min, tzinfo=timezone.utc)

    def ensure_job_allowed(self, *, workspace_id: str, user_id: str) -> None:
        used = self.store.count_usage_since(
            workspace_id=workspace_id,
            user_id=user_id,
            event_types=["source_test", "source_fetch", "user_feed_refresh"],
            since=self._today_start(),
        )
        if used >= self.max_fetch_jobs_per_day:
            raise QuotaExceeded("daily fetch job quota exceeded")

    def record_job_usage(
        self,
        *,
        workspace_id: str,
        user_id: str,
        event_type: str,
    ) -> None:
        self.store.record_usage_event(
            workspace_id=workspace_id,
            user_id=user_id,
            event_type=event_type,
            quantity=1,
        )
