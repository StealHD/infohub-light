"""Explicit read-only facade for composed Remote MCP diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from ..services.job_queue import JobQueue
from ..services.runtime_status import RuntimeStatusService
from ..services.source_health import SourceHealthService
from ..services.subscription_mutation import SubscriptionActor
from ..storage.service_store import ServiceStore
from .remote_diagnostic_classification import (
    classify_job,
    classify_source,
    job_status,
    selected_job_overrides_health,
    source_status,
)
from .remote_diagnostic_evidence import job_evidence, source_evidence
from .remote_diagnostic_projection import diagnostic_response
from .remote_diagnostic_records import RemoteMCPDiagnosticRecords
from .remote_diagnostic_sanitization import safe_name, utc


__all__ = ["RemoteMCPDiagnostics"]


class RemoteMCPDiagnostics:
    """Compose safe record reads, classification, evidence, and projection."""

    def __init__(
        self,
        store: ServiceStore,
        *,
        health: SourceHealthService | None = None,
        jobs: JobQueue | None = None,
        runtime_status: RuntimeStatusService | None = None,
        secret_is_set: Callable[[str], bool] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.health = health or SourceHealthService(store)
        self.jobs = jobs or JobQueue(store)
        self.runtime_status = runtime_status or RuntimeStatusService(store)
        self.secret_is_set = secret_is_set or (lambda _env_name: False)
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.records = RemoteMCPDiagnosticRecords(
            store,
            health=self.health,
            jobs=self.jobs,
            runtime_status=self.runtime_status,
            secret_is_set=self.secret_is_set,
        )

    def diagnose_source(
        self,
        *,
        actor: SubscriptionActor,
        subscription_id: str,
    ) -> dict[str, Any]:
        checked_at = utc(self.now())
        subject = self.records.owned_subscription(actor, subscription_id)
        health = self.records.owned_health(actor, subject)
        schedule = self.records.owned_schedule(actor, subject)
        related = self.records.related_source_job(
            actor,
            subject,
            health=health,
            schedule=schedule,
        )
        related_job = related.job if related is not None else None
        related_provenance = related.provenance if related is not None else None
        job_overrides_health = selected_job_overrides_health(
            health=health,
            related_job=related_job,
            related_provenance=related_provenance,
        )
        worker_status = self.records.worker_status(actor, checked_at=checked_at)
        category, code, confidence = classify_source(
            subject=subject,
            schedule=schedule,
            health=health,
            job=related_job,
            worker_status=worker_status,
            job_overrides_health=job_overrides_health,
            checked_at=checked_at,
        )
        return diagnostic_response(
            kind="source",
            target_id=str(subscription_id),
            name=safe_name(subject.get("display_name"), fallback="来源"),
            status=source_status(
                health=health,
                job=related_job,
                category=category,
                job_overrides_health=job_overrides_health,
            ),
            category=category,
            code=code,
            confidence=confidence,
            evidence=source_evidence(
                subject=subject,
                schedule=schedule,
                health=health,
                job=related_job,
                related_provenance=related_provenance,
                health_is_historical=job_overrides_health,
                worker_status=worker_status,
                secret_configured=self.records.secret_configured(
                    subject.get("secret_env")
                ),
                checked_at=checked_at,
            ),
            related_job_id=(
                str(related_job["id"]) if related_job is not None else None
            ),
        )

    def diagnose_job(
        self,
        *,
        actor: SubscriptionActor,
        job_id: str,
    ) -> dict[str, Any]:
        checked_at = utc(self.now())
        job = self.records.owned_job(actor, job_id)
        subject = self.records.job_subject(actor, job)
        worker_status = self.records.worker_status(actor, checked_at=checked_at)
        category, code, confidence = classify_job(
            job=job,
            worker_status=worker_status,
        )
        fallback_name = {
            "source_fetch": "来源抓取任务",
            "source_test": "来源测试任务",
            "user_feed_refresh": "Feed 刷新任务",
        }.get(str(job.get("job_type")), "任务")
        return diagnostic_response(
            kind="job",
            target_id=str(job_id),
            name=safe_name(
                (subject or {}).get("display_name"),
                fallback=fallback_name,
            ),
            status=job_status(job),
            category=category,
            code=code,
            confidence=confidence,
            evidence=job_evidence(job, worker_status=worker_status),
            related_job_id=None,
        )
