"""Current-state eligibility checks for claimed service jobs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..storage.service_store import ServiceStore
from .feed_schedule import SCHEDULED_REFRESH_REASON


@dataclass(frozen=True, slots=True)
class JobEligibilityDecision:
    allowed: bool
    reason: str | None = None


class JobIneligibleError(RuntimeError):
    """Raised immediately before an upstream attempt for an invalidated job."""

    retryable = False

    def __init__(self, reason: str):
        self.reason = str(reason or "job_invalidated")
        super().__init__(f"job is no longer eligible: {self.reason}")


class JobEligibilityService:
    """Reject jobs whose user/source/subscription is no longer runnable."""

    def __init__(self, store: ServiceStore) -> None:
        self.store = store

    def evaluate(self, job: dict[str, Any]) -> JobEligibilityDecision:
        user = self.store.get_user(str(job.get("user_id") or ""))
        if user is None or not user.get("enabled"):
            return JobEligibilityDecision(False, "user_disabled")
        if user.get("role") == "viewer":
            return JobEligibilityDecision(False, "user_read_only")

        source_id = str(job.get("source_id") or "")
        if source_id:
            source = self.store.get_source(source_id)
            if source is None or not source.get("enabled"):
                return JobEligibilityDecision(False, "source_disabled")

        if (
            job.get("job_type") == "user_feed_refresh"
            and (job.get("payload_json") or {}).get("reason")
            == SCHEDULED_REFRESH_REASON
            and not self.store.has_enabled_user_subscriptions(
                workspace_id=str(job.get("workspace_id") or ""),
                user_id=str(user["id"]),
                global_schedule_only=True,
            )
        ):
            return JobEligibilityDecision(False, "no_global_subscriptions")

        if job.get("job_type") != "source_fetch" or not source_id:
            return JobEligibilityDecision(True)

        subscription_id = str(job.get("subscription_id") or "")
        subscription = (
            self.store.get_subscription(subscription_id)
            if subscription_id
            else self.store.get_user_subscription_for_source(user["id"], source_id)
        )
        if subscription is None:
            return JobEligibilityDecision(False, "subscription_deleted")
        if (
            subscription.get("user_id") != user["id"]
            or subscription.get("source_id") != source_id
        ):
            return JobEligibilityDecision(False, "subscription_deleted")
        if not subscription.get("enabled"):
            return JobEligibilityDecision(False, "subscription_disabled")
        return JobEligibilityDecision(True)

    def evaluate_attempt(
        self,
        job: dict[str, Any],
        *,
        source_id: str | None = None,
    ) -> JobEligibilityDecision:
        """Evaluate the current job and, for full refreshes, the source about to call."""

        decision = self.evaluate(job)
        if not decision.allowed or not source_id:
            return decision
        if job.get("job_type") != "user_feed_refresh":
            return decision
        return self.evaluate(
            {
                **job,
                "job_type": "source_fetch",
                "source_id": source_id,
                "subscription_id": None,
            }
        )

    def evaluate_current_attempt(
        self,
        job_id: str,
        *,
        source_id: str | None = None,
    ) -> JobEligibilityDecision:
        current = self.store._job(
            self.store.connect().execute(
                "SELECT * FROM fetch_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        )
        if current is None:
            return JobEligibilityDecision(False, "job_missing")
        if current.get("status") != "running":
            return JobEligibilityDecision(False, "job_not_running")
        return self.evaluate_attempt(current, source_id=source_id)

    def require_current_attempt(
        self,
        job_id: str,
        *,
        source_id: str | None = None,
    ) -> None:
        decision = self.evaluate_current_attempt(job_id, source_id=source_id)
        if not decision.allowed:
            raise JobIneligibleError(str(decision.reason or "job_invalidated"))
