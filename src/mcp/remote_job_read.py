"""User-scoped Job reads for Remote MCP."""

from __future__ import annotations

from typing import Any

from ..services.job_queue import JobQueue
from ..storage.service_store import JOB_STATUSES, ServiceStore
from .remote_read_projection import (
    RemoteMCPNotFound,
    safe_job_result_summary,
    validate_pagination,
)


class RemoteMCPJobReadService:
    def __init__(self, store: ServiceStore) -> None:
        self.jobs = JobQueue(store)

    @staticmethod
    def safe_job(job: dict[str, Any]) -> dict[str, Any]:
        error = None
        if job.get("error_code"):
            error = {"code": job.get("error_code")}
        return {
            "id": job["id"],
            "job_type": job["job_type"],
            "status": job["status"],
            "source_id": job.get("source_id"),
            "subscription_id": job.get("subscription_id"),
            "priority": int(job.get("priority") or 0),
            "attempts": int(job.get("attempts") or 0),
            "max_attempts": int(job.get("max_attempts") or 0),
            "next_run_at": job.get("next_run_at"),
            "created_at": job.get("created_at"),
            "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at"),
            "cancelled_at": job.get("cancelled_at"),
            "updated_at": job.get("updated_at"),
            "error": error,
            "result_summary": safe_job_result_summary(job),
        }

    def list_jobs(
        self,
        *,
        workspace_id: str,
        user_id: str,
        status: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        limit, _ = validate_pagination(limit, 0)
        if status is not None and status not in JOB_STATUSES:
            raise ValueError("invalid job status")
        jobs = self.jobs.list_jobs(
            workspace_id=workspace_id,
            user_id=user_id,
            status=status,
            limit=limit,
        )
        return {"items": [self.safe_job(job) for job in jobs], "count": len(jobs)}

    def get_job(
        self,
        *,
        workspace_id: str,
        user_id: str,
        job_id: str,
    ) -> dict[str, Any]:
        job = self.jobs.get_job(str(job_id))
        if (
            job is None
            or job.get("workspace_id") != workspace_id
            or job.get("user_id") != user_id
        ):
            raise RemoteMCPNotFound("not_found")
        return self.safe_job(job)
