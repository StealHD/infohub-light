"""Deterministic, user-scoped diagnostics from bounded persisted evidence."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable

from ..security import (
    is_sensitive_credential_key,
    public_data_contains_credentials,
)
from ..services.job_queue import JobQueue
from ..services.runtime_status import RuntimeStatusService
from ..services.source_health import SourceHealthService, sanitize_issue_message
from ..services.subscription_mutation import SubscriptionActor
from ..storage.service_store import JOB_STATUSES, ServiceStore
from .remote_service import (
    RemoteMCPNotFound,
    safe_job_result_summary,
)


_CODE_RULES = (
    (
        "auth_missing",
        ("unauthorized", "forbidden", "auth", "credential", "tokenmissing"),
    ),
    ("rate_limited", ("429", "ratelimit", "rate_limit", "quotaexceeded")),
    (
        "network_timeout",
        ("timeout", "timedout", "connection", "dns", "network"),
    ),
    (
        "invalid_source_config",
        ("sourceconfig", "invalidconfig", "validationerror"),
    ),
    (
        "upstream_rejected",
        ("httperror", "fetchfailed", "upstream", "rejected"),
    ),
)

_CAUSE_COPY = {
    "auth_missing": (
        "认证信息缺失或无效",
        "来源认证未通过，请在 Web 中检查密钥配置",
        False,
    ),
    "rate_limited": (
        "上游请求受限",
        "上游限制了请求频率，请稍后再试",
        True,
    ),
    "network_timeout": (
        "上游连接超时",
        "连接上游时超时或网络不可用",
        True,
    ),
    "upstream_rejected": (
        "上游拒绝请求",
        "上游未接受本次请求",
        True,
    ),
    "invalid_source_config": (
        "来源配置无效",
        "来源配置未通过校验",
        False,
    ),
    "source_disabled": (
        "来源已停用",
        "该来源当前处于停用状态",
        False,
    ),
    "subscription_disabled": (
        "订阅已停用",
        "该订阅当前处于停用状态",
        False,
    ),
    "schedule_blocked": (
        "自动计划受阻",
        "自动抓取计划当前未能继续执行",
        False,
    ),
    "worker_unavailable": (
        "Worker 当前不可用",
        "没有可用的 Worker 处理该任务",
        True,
    ),
    "no_items": (
        "本次未获取到条目",
        "最近一次成功尝试没有获取到新条目",
        True,
    ),
    "unknown": (
        "原因未知",
        "现有记录不足以确定原因",
        False,
    ),
}

_ACTION_BY_CATEGORY = {
    "auth_missing": {
        "code": "check_secret_in_web",
        "mode": "web",
        "label": "在 Web 中检查密钥配置",
    },
    "rate_limited": {
        "code": "wait_for_rate_limit",
        "mode": "wait",
        "label": "等待上游限流窗口恢复",
    },
    "network_timeout": {
        "code": "wait_and_review_target",
        "mode": "wait",
        "label": "稍后重试并检查来源可达性",
    },
    "upstream_rejected": {
        "code": "review_upstream_response",
        "mode": "wait",
        "label": "稍后重试或检查上游状态",
    },
    "invalid_source_config": {
        "code": "review_source_config",
        "mode": "prepare_change",
        "label": "检查来源配置并准备变更",
    },
    "source_disabled": {
        "code": "review_source_enabled",
        "mode": "prepare_change",
        "label": "检查是否需要启用来源",
    },
    "subscription_disabled": {
        "code": "review_subscription_enabled",
        "mode": "prepare_change",
        "label": "检查是否需要启用订阅",
    },
    "schedule_blocked": {
        "code": "review_schedule",
        "mode": "prepare_change",
        "label": "检查自动抓取计划",
    },
    "worker_unavailable": {
        "code": "contact_worker_admin",
        "mode": "contact_admin",
        "label": "联系管理员检查 Worker 状态",
    },
    "no_items": {
        "code": "wait_for_new_items",
        "mode": "wait",
        "label": "等待来源发布新条目",
    },
    "unknown": {
        "code": "contact_admin_for_evidence",
        "mode": "contact_admin",
        "label": "联系管理员获取更多运行证据",
    },
}

_SAFE_CODE_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,63}\Z")
_SECRET_SHAPED_CODE_RE = re.compile(
    r"(?:sk[-_]|gh[pousr]_|xox[a-z]-|AIza|xai-|gsk_|hf_|tp-)",
    re.IGNORECASE,
)
_SAFE_RESULT_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_ACTIVE_JOB_STATUSES = {"queued", "running"}
_HEALTH_STATUSES = {"healthy", "degraded", "failing"}
_WORKER_STATUSES = {"ready", "stale", "missing"}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _safe_code(value: Any) -> str | None:
    code = str(value or "").strip()
    if (
        not _SAFE_CODE_RE.fullmatch(code)
        or _SECRET_SHAPED_CODE_RE.search(code)
        or is_sensitive_credential_key(code)
        or public_data_contains_credentials(code)
    ):
        return None
    return code


def _mapped_category(value: Any) -> tuple[str | None, str | None]:
    code = _safe_code(value)
    if code is None:
        return None, None
    normalized = _compact(code)
    for category, markers in _CODE_RULES:
        if any(_compact(marker) in normalized for marker in markers):
            return category, code
    return None, code


def _message_category(value: Any) -> str | None:
    sanitized = sanitize_issue_message(str(value or ""))
    if not sanitized:
        return None
    normalized = _compact(sanitized)
    for category, markers in _CODE_RULES:
        if any(_compact(marker) in normalized for marker in markers):
            return category
    return None


def _safe_name(value: Any, *, fallback: str) -> str:
    candidate = " ".join(str(value or "").split())[:120]
    if (
        not candidate
        or "://" in candidate
        or "?" in candidate
        or re.search(r"\b(?:authorization|bearer|basic)\b", candidate, re.I)
        or is_sensitive_credential_key(candidate)
        or public_data_contains_credentials(candidate)
    ):
        return fallback
    return candidate


def _safe_timestamp(value: Any) -> str | None:
    try:
        return _utc(datetime.fromisoformat(str(value))).isoformat()
    except (TypeError, ValueError):
        return None


def _strict_result_summary(job: dict[str, Any] | None) -> dict[str, Any]:
    if not job:
        return {}
    selected = safe_job_result_summary(job)
    safe: dict[str, Any] = {}
    for field in ("fetched_count", "item_count", "issue_count"):
        if field not in selected or isinstance(selected[field], bool):
            continue
        try:
            safe[field] = max(int(selected[field]), 0)
        except (TypeError, ValueError):
            continue
    if isinstance(selected.get("partial"), bool):
        safe["partial"] = selected["partial"]
    for field in ("snapshot_id", "run_status"):
        value = str(selected.get(field) or "").strip()
        if (
            value
            and _SAFE_RESULT_IDENTIFIER_RE.fullmatch(value)
            and not is_sensitive_credential_key(value)
            and not public_data_contains_credentials(value)
        ):
            safe[field] = value
    return safe


class RemoteMCPDiagnostics:
    """Explain owned source and job states without returning raw internals."""

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

    def diagnose_source(
        self,
        *,
        actor: SubscriptionActor,
        subscription_id: str,
    ) -> dict[str, Any]:
        checked_at = _utc(self.now())
        subject = self._owned_subscription(actor, subscription_id)
        health = self._owned_health(actor, subject)
        schedule = self._owned_schedule(actor, subject)
        related_job = self._related_source_job(
            actor,
            subject,
            health=health,
            schedule=schedule,
        )
        worker_status = self._worker_status(actor, checked_at=checked_at)
        category, code, confidence = self._classify(
            subject=subject,
            schedule=schedule,
            health=health,
            job=related_job,
            worker_status=worker_status,
            prefer_job=False,
            checked_at=checked_at,
        )
        status = self._source_status(
            subject=subject,
            schedule=schedule,
            health=health,
            job=related_job,
            category=category,
        )
        secret_configured = self._secret_configured(subject.get("secret_env"))
        evidence = self._source_evidence(
            subject=subject,
            schedule=schedule,
            health=health,
            job=related_job,
            worker_status=worker_status,
            secret_configured=secret_configured,
            checked_at=checked_at,
        )
        return self._response(
            kind="source",
            target_id=str(subscription_id),
            name=_safe_name(subject.get("display_name"), fallback="来源"),
            status=status,
            category=category,
            code=code,
            confidence=confidence,
            evidence=evidence,
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
        checked_at = _utc(self.now())
        job = self._owned_job(actor, job_id)
        subject = self._job_subject(actor, job)
        schedule = self._owned_schedule(actor, subject) if subject else None
        health = self._owned_health(actor, subject) if subject else None
        worker_status = self._worker_status(actor, checked_at=checked_at)
        category, code, confidence = self._classify(
            subject=subject,
            schedule=schedule,
            health=health,
            job=job,
            worker_status=worker_status,
            prefer_job=True,
            checked_at=checked_at,
        )
        fallback_name = {
            "source_fetch": "来源抓取任务",
            "source_test": "来源测试任务",
            "user_feed_refresh": "Feed 刷新任务",
        }.get(str(job.get("job_type")), "任务")
        return self._response(
            kind="job",
            target_id=str(job_id),
            name=_safe_name(
                (subject or {}).get("display_name"),
                fallback=fallback_name,
            ),
            status=self._job_status(job),
            category=category,
            code=code,
            confidence=confidence,
            evidence=self._job_evidence(job, worker_status=worker_status),
            related_job_id=None,
        )

    def _owned_subscription(
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

    def _owned_job(
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

    def _owned_health(
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

    def _owned_schedule(
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

    def _job_subject(
        self,
        actor: SubscriptionActor,
        job: dict[str, Any],
    ) -> dict[str, Any] | None:
        subscription_id = job.get("subscription_id")
        if subscription_id:
            try:
                subject = self._owned_subscription(actor, str(subscription_id))
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

    def _related_source_job(
        self,
        actor: SubscriptionActor,
        subject: dict[str, Any],
        *,
        health: dict[str, Any] | None,
        schedule: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        explicit_candidates: list[tuple[str, dict[str, Any]]] = []
        for link_kind, candidate_id in (
            ("health", (health or {}).get("last_job_id")),
            ("schedule", (schedule or {}).get("last_job_id")),
        ):
            if not candidate_id:
                continue
            job = self.jobs.get_job(str(candidate_id))
            if self._explicit_job_matches_subject(actor, subject, job):
                explicit_candidates.append((link_kind, job))
        if explicit_candidates:
            active_schedule_jobs = [
                job
                for link_kind, job in explicit_candidates
                if link_kind == "schedule"
                and self._job_status(job) in _ACTIVE_JOB_STATUSES
            ]
            candidates = active_schedule_jobs or [
                job for _link_kind, job in explicit_candidates
            ]
            return max(
                candidates,
                key=lambda job: (
                    str(job.get("created_at") or ""),
                    str(job.get("id") or ""),
                ),
            )
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
        return job if self._job_matches_subject(actor, subject, job) else None

    @staticmethod
    def _explicit_job_matches_subject(
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
        return RemoteMCPDiagnostics._job_matches_subject(actor, subject, job)

    @staticmethod
    def _job_matches_subject(
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
            and job.get("subscription_id") in {
                None,
                subject["subscription_id"],
            }
        )

    def _worker_status(
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
        return status if status in _WORKER_STATUSES else "unknown"

    def _secret_configured(self, secret_env: Any) -> bool:
        if not secret_env:
            return False
        try:
            return bool(self.secret_is_set(str(secret_env)))
        except Exception:
            return False

    @staticmethod
    def _schedule_state(
        schedule: dict[str, Any] | None,
        *,
        checked_at: datetime,
    ) -> str:
        if schedule is None:
            return "not_configured"
        if not bool(schedule.get("enabled")):
            return "disabled"
        if schedule.get("last_skip_reason"):
            return "blocked"
        next_run_at = _safe_timestamp(schedule.get("next_run_at"))
        if next_run_at and datetime.fromisoformat(next_run_at) <= checked_at:
            return "overdue"
        return "ready"

    def _classify(
        self,
        *,
        subject: dict[str, Any] | None,
        schedule: dict[str, Any] | None,
        health: dict[str, Any] | None,
        job: dict[str, Any] | None,
        worker_status: str,
        prefer_job: bool,
        checked_at: datetime,
    ) -> tuple[str, str | None, str]:
        if subject is not None and not bool(subject.get("source_enabled")):
            return "source_disabled", "source_disabled", "confirmed"
        if subject is not None and not bool(subject.get("subscription_enabled")):
            return "subscription_disabled", "subscription_disabled", "confirmed"
        schedule_state = self._schedule_state(schedule, checked_at=checked_at)
        if schedule is not None and schedule_state in {"disabled", "blocked", "overdue"}:
            return "schedule_blocked", "schedule_blocked", "confirmed"
        if (
            job is not None
            and self._job_status(job) in _ACTIVE_JOB_STATUSES
            and worker_status in {"missing", "stale"}
        ):
            return "worker_unavailable", f"worker_{worker_status}", "confirmed"

        evidence_order = (job, health) if prefer_job else (health, job)
        retained_code: str | None = None
        for evidence in evidence_order:
            if not evidence:
                continue
            raw_code = (
                evidence.get("error_code")
                if "error_code" in evidence
                else evidence.get("last_issue_code")
            )
            category, safe_code = _mapped_category(raw_code)
            retained_code = retained_code or safe_code
            if category:
                return category, safe_code, "confirmed"
        for evidence in evidence_order:
            if not evidence:
                continue
            raw_message = (
                evidence.get("error_message")
                if "error_message" in evidence
                else evidence.get("last_issue_message")
            )
            category = _message_category(raw_message)
            if category:
                return category, retained_code, "likely"
        if self._successful_zero_item_attempt(
            health=health,
            job=job,
            job_only=prefer_job,
        ):
            return "no_items", retained_code, "confirmed"
        return "unknown", retained_code, "unknown"

    @staticmethod
    def _successful_zero_item_attempt(
        *,
        health: dict[str, Any] | None,
        job: dict[str, Any] | None,
        job_only: bool,
    ) -> bool:
        if (
            not job_only
            and health
            and health.get("status") == "healthy"
            and health.get("last_attempt_at")
            and int(health.get("last_fetched_count") or 0) == 0
        ):
            return True
        if not job or job.get("status") != "succeeded":
            return False
        result = _strict_result_summary(job)
        return "fetched_count" in result and result["fetched_count"] == 0

    def _source_status(
        self,
        *,
        subject: dict[str, Any],
        schedule: dict[str, Any] | None,
        health: dict[str, Any] | None,
        job: dict[str, Any] | None,
        category: str,
    ) -> str:
        if category in {"source_disabled", "subscription_disabled"}:
            return "disabled"
        if category == "schedule_blocked":
            return "blocked"
        health_status = str((health or {}).get("status") or "")
        if health_status in _HEALTH_STATUSES:
            return health_status
        if job is not None:
            return self._job_status(job)
        return "unknown"

    @staticmethod
    def _job_status(job: dict[str, Any]) -> str:
        status = str(job.get("status") or "")
        return status if status in JOB_STATUSES else "unknown"

    def _source_evidence(
        self,
        *,
        subject: dict[str, Any],
        schedule: dict[str, Any] | None,
        health: dict[str, Any] | None,
        job: dict[str, Any] | None,
        worker_status: str,
        secret_configured: bool,
        checked_at: datetime,
    ) -> list[dict[str, Any]]:
        evidence = [
            {"kind": "source_enabled", "value": bool(subject["source_enabled"])},
            {
                "kind": "subscription_enabled",
                "value": bool(subject["subscription_enabled"]),
            },
            {
                "kind": "schedule_status",
                "value": self._schedule_state(schedule, checked_at=checked_at),
            },
            {"kind": "secret_configured", "value": bool(secret_configured)},
        ]
        if schedule and schedule.get("last_skip_reason"):
            skip_code = _safe_code(schedule.get("last_skip_reason"))
            if skip_code:
                evidence.append({"kind": "schedule_skip_reason", "value": skip_code})
        if health:
            evidence.extend(
                [
                    {"kind": "health_status", "value": str(health["status"])},
                    {
                        "kind": "consecutive_failures",
                        "value": max(int(health.get("consecutive_failures") or 0), 0),
                    },
                    {
                        "kind": "last_fetched_count",
                        "value": max(int(health.get("last_fetched_count") or 0), 0),
                    },
                ]
            )
            issue_code = _safe_code(health.get("last_issue_code"))
            if issue_code:
                evidence.append({"kind": "error_code", "value": issue_code})
            for field in ("last_attempt_at", "last_failure_at", "last_success_at"):
                timestamp = _safe_timestamp(health.get(field))
                if timestamp:
                    evidence.append({"kind": field, "value": timestamp})
        if job:
            evidence.extend(self._job_evidence(job, worker_status=worker_status))
        else:
            evidence.append({"kind": "worker_status", "value": worker_status})
        return evidence

    @staticmethod
    def _job_evidence(
        job: dict[str, Any],
        *,
        worker_status: str,
    ) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = [
            {"kind": "job_status", "value": RemoteMCPDiagnostics._job_status(job)},
            {"kind": "attempts", "value": max(int(job.get("attempts") or 0), 0)},
            {
                "kind": "max_attempts",
                "value": max(int(job.get("max_attempts") or 0), 0),
            },
            {"kind": "worker_status", "value": worker_status},
        ]
        code = _safe_code(job.get("error_code"))
        if code:
            evidence.append({"kind": "error_code", "value": code})
        for field in ("created_at", "started_at", "finished_at", "updated_at"):
            timestamp = _safe_timestamp(job.get(field))
            if timestamp:
                evidence.append({"kind": field, "value": timestamp})
        result = _strict_result_summary(job)
        if result:
            evidence.append({"kind": "result_summary", "value": result})
        return evidence

    @staticmethod
    def _response(
        *,
        kind: str,
        target_id: str,
        name: str,
        status: str,
        category: str,
        code: str | None,
        confidence: str,
        evidence: list[dict[str, Any]],
        related_job_id: str | None,
    ) -> dict[str, Any]:
        title, message, retryable = _CAUSE_COPY[category]
        return {
            "target": {"kind": kind, "id": target_id, "name": name},
            "status": status,
            "cause": {
                "category": category,
                "code": code,
                "title": title,
                "message": message,
                "confidence": confidence,
                "retryable": retryable,
            },
            "evidence": evidence,
            "suggested_actions": [dict(_ACTION_BY_CATEGORY[category])],
            "related_job_id": related_job_id,
        }
