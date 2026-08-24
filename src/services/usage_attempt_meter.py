"""Service-scoped admission hooks for upstream fetch attempts."""

from __future__ import annotations

from ..storage.service_store import ServiceStore
from .job_eligibility import JobEligibilityService
from .quota import QuotaExceeded, QuotaService


class UsageAttemptMeter:
    def __init__(
        self,
        store: ServiceStore,
        *,
        workspace_id: str,
        user_id: str,
        job_id: str | None = None,
    ) -> None:
        self.store = store
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.job_id = job_id
        self.quota = QuotaService(store)

    def before_fetch_attempt(self, *, provider: str, source_id: str) -> None:
        if self.job_id:
            JobEligibilityService(self.store).require_current_attempt(
                self.job_id,
                source_id=source_id or None,
            )
        try:
            self.quota.admit_fetch_attempt(
                workspace_id=self.workspace_id,
                user_id=self.user_id,
                provider=provider,
                source_id=source_id or None,
            )
        except QuotaExceeded:
            self.quota.record_quota_reject(
                workspace_id=self.workspace_id,
                user_id=self.user_id,
                quota="fetch_attempt",
                provider=provider,
            )
            raise
