"""Read-only, actor-scoped persisted records for Remote MCP diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, NamedTuple

from ..services.job_queue import JobQueue
from ..services.runtime_status import RuntimeStatusService
from ..services.source_health import SourceHealthService
from ..services.subscription_mutation import SubscriptionActor
from ..storage.service_store import ServiceStore
from .remote_diagnostic_classification import (
    ACTIVE_JOB_STATUSES,
    WORKER_STATUSES,
    job_status,
)
from .remote_read_projection import RemoteMCPNotFound


class RelatedSourceJob(NamedTuple):
    job: dict[str, Any]
    provenance: str


class RemoteMCPDiagnosticRecords:
    def __init__(
        self,
        store: ServiceStore,
        *,
        health: SourceHealthService,
        jobs: JobQueue,
        runtime_status: RuntimeStatusService,
        secret_is_set: Callable[[str], bool],
    ) -> None:
        self.store = store
        self.health = health
        self.jobs = jobs
        self.runtime_status = runtime_status
        self.secret_is_set = secret_is_set

    def owned_subscription(
        self,
        actor: SubscriptionActor,
        subscription_id: str,
    ) -> dict[str, Any]:
        row = self.store.connect().execute(
            """
            SELECT
                subscriptions.id AS subscription_id,
                subscriptions.user_id,
                subscriptions.source_id,
                subscriptions.enabled AS subscription_enabled,
                sources.workspace_id,
                sources.scope,
                sources.owner_user_id,
                sources.display_name,
                sources.enabled AS source_enabled,
                sources.secret_env
            FROM user_subscriptions AS subscriptions
            JOIN source_catalog AS sources
              ON sources.id = subscriptions.source_id
            JOIN users
              ON users.id = subscriptions.user_id
             AND users.workspace_id = sources.workspace_id
            WHERE subscriptions.id = ?
              AND subscriptions.user_id = ?
              AND sources.workspace_id = ?
            """,
            (str(subscription_id), actor.user_id, actor.workspace_id),
        ).fetchone()
        if row is None:
            raise RemoteMCPNotFound("not_found")
        subject = dict(row)
        subject["subscription_enabled"] = bool(subject["subscription_enabled"])
        subject["source_enabled"] = bool(subject["source_enabled"])
        return subject

    def owned_job(
        self,
        actor: SubscriptionActor,
        job_id: str,
    ) -> dict[str, Any]:
        job = self.jobs.get_job(str(job_id))
        if (
            job is None
            or job.get("workspace_id") != actor.workspace_id
            or job.get("user_id") != actor.user_id
        ):
            raise RemoteMCPNotFound("not_found")
        return job

    def owned_health(
        self,
        actor: SubscriptionActor,
        subject: dict[str, Any],
    ) -> dict[str, Any] | None:
        health = self.health.get_health(str(subject["subscription_id"]))
        if not health:
            return None
        if (
            health.get("workspace_id") != actor.workspace_id
            or health.get("user_id") != actor.user_id
            or health.get("source_id") != subject["source_id"]
        ):
            return None
        return health

    def owned_schedule(
        self,
        actor: SubscriptionActor,
        subject: dict[str, Any],
    ) -> dict[str, Any] | None:
        schedule = self.store.get_source_schedule(str(subject["subscription_id"]))
        if not schedule:
            return None
        if (
            schedule.get("workspace_id") != actor.workspace_id
            or schedule.get("user_id") != actor.user_id
            or schedule.get("source_id") != subject["source_id"]
        ):
            return None
        return schedule

    def job_subject(
        self,
        actor: SubscriptionActor,
        job: dict[str, Any],
    ) -> dict[str, Any] | None:
        subscription_id = job.get("subscription_id")
        if subscription_id:
            try:
                subject = self.owned_subscription(actor, str(subscription_id))
            except RemoteMCPNotFound:
                return None
            if job.get("source_id") and job.get("source_id") != subject["source_id"]:
                return None
            return subject
        source_id = str(job.get("source_id") or "")
        if not source_id:
            return None
        source = self.store.get_source(source_id)
        if source is None or source.get("workspace_id") != actor.workspace_id:
            return None
        if source.get("scope") == "private" and source.get("owner_user_id") != actor.user_id:
            return None
        return {
            "subscription_id": None,
            "user_id": actor.user_id,
            "source_id": source_id,
            "subscription_enabled": True,
            "workspace_id": actor.workspace_id,
            "scope": source.get("scope"),
            "owner_user_id": source.get("owner_user_id"),
            "display_name": source.get("display_name"),
            "source_enabled": bool(source.get("enabled")),
            "secret_env": source.get("secret_env"),
        }

    def related_source_job(
        self,
        actor: SubscriptionActor,
        subject: dict[str, Any],
        *,
        health: dict[str, Any] | None,
        schedule: dict[str, Any] | None,
    ) -> RelatedSourceJob | None:
        explicit_candidates: list[tuple[str, dict[str, Any]]] = []
        for link_kind, candidate_id in (
            ("health", (health or {}).get("last_job_id")),
            ("schedule", (schedule or {}).get("last_job_id")),
        ):
            if not candidate_id:
                continue
            job = self.jobs.get_job(str(candidate_id))
            if self.explicit_job_matches_subject(actor, subject, job):
                explicit_candidates.append((link_kind, job))
        if explicit_candidates:
            active_schedule_jobs = [
                job
                for link_kind, job in explicit_candidates
                if link_kind == "schedule" and job_status(job) in ACTIVE_JOB_STATUSES
            ]
            candidates = active_schedule_jobs or [
                job for _link_kind, job in explicit_candidates
            ]
            selected = max(
                candidates,
                key=lambda job: (
                    str(job.get("created_at") or ""),
                    str(job.get("id") or ""),
                ),
            )
            selected_links = {
                link_kind
                for link_kind, candidate in explicit_candidates
                if candidate.get("id") == selected.get("id")
            }
            provenance = (
                "health_and_schedule"
                if selected_links == {"health", "schedule"}
                else next(iter(selected_links))
            )
            return RelatedSourceJob(selected, provenance)
        row = self.store.connect().execute(
            """
            SELECT id
            FROM fetch_jobs
            WHERE workspace_id = ?
              AND user_id = ?
              AND (
                subscription_id = ?
                OR (subscription_id IS NULL AND source_id = ?)
              )
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (
                actor.workspace_id,
                actor.user_id,
                subject["subscription_id"],
                subject["source_id"],
            ),
        ).fetchone()
        job = self.jobs.get_job(str(row["id"])) if row is not None else None
        if not self.job_matches_subject(actor, subject, job):
            return None
        return RelatedSourceJob(job, "fallback")

    @staticmethod
    def explicit_job_matches_subject(
        actor: SubscriptionActor,
        subject: dict[str, Any],
        job: dict[str, Any] | None,
    ) -> bool:
        if not job:
            return False
        if (
            job.get("workspace_id") != actor.workspace_id
            or job.get("user_id") != actor.user_id
        ):
            return False
        if job.get("job_type") == "user_feed_refresh":
            return True
        return RemoteMCPDiagnosticRecords.job_matches_subject(actor, subject, job)

    @staticmethod
    def job_matches_subject(
        actor: SubscriptionActor,
        subject: dict[str, Any],
        job: dict[str, Any] | None,
    ) -> bool:
        if not job:
            return False
        return bool(
            job.get("workspace_id") == actor.workspace_id
            and job.get("user_id") == actor.user_id
            and job.get("source_id") == subject["source_id"]
            and job.get("subscription_id") in {None, subject["subscription_id"]}
        )

    def worker_status(
        self,
        actor: SubscriptionActor,
        *,
        checked_at: datetime,
    ) -> str:
        try:
            status = str(
                self.runtime_status.summary(
                    workspace_id=actor.workspace_id,
                    user_id=actor.user_id,
                    now=checked_at,
                ).get("worker_status")
                or ""
            )
        except Exception:
            return "unknown"
        return status if status in WORKER_STATUSES else "unknown"

    def secret_configured(self, secret_env: Any) -> bool:
        if not secret_env:
            return False
        try:
            return bool(self.secret_is_set(str(secret_env)))
        except Exception:
            return False
