"""Persist user-scoped source outcomes without exposing source configuration."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

from ..storage.service_store import ServiceStore
from .content_timeline import DEFAULT_FEED_WINDOW_DAYS, feed_window
from .feed_run import SourceOutcome
from .user_content_store import UserContentStore


MAX_ISSUE_MESSAGE_LENGTH = 240
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_BEARER_RE = re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_BASIC_AUTH_RE = re.compile(
    r"(?P<prefix>\bauthorization\s*:\s*)?\bbasic\s+[A-Za-z0-9+/=]{8,}",
    re.IGNORECASE,
)
_RAW_SECRET_RE = re.compile(
    r"""
    (?<![A-Za-z0-9])
    (?:
        sk-[A-Za-z0-9_-]{8,}
        |gh[pousr]_[A-Za-z0-9_]{8,}
        |xox[a-z]-[A-Za-z0-9-]{8,}
    )
    (?![A-Za-z0-9])
    """,
    re.IGNORECASE | re.VERBOSE,
)
_SENSITIVE_VALUE_RE = re.compile(
    r"""
    (?P<prefix>
        ["']?
        (?:[A-Za-z0-9_-]*token|api[-_ ]?key|password|secret|payload|config|stack)
        ["']?
        (?:\s*[:=]\s*|\s+)
    )
    (?P<value>
        \{[^{}]*\}
        |\[[^\[\]]*\]
        |"[^"]*"
        |'[^']*'
        |[^\s,;]+
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
_SENSITIVE_TAIL_RE = re.compile(
    r"""
    (?<![A-Za-z0-9])
    (?P<label>
        (?:[A-Za-z0-9]+[_-])*
        (?:payload|config|stack|traceback)
        (?:[_-][A-Za-z0-9]+)*
    )
    (?![A-Za-z0-9])
    .*$
    """,
    re.IGNORECASE | re.VERBOSE,
)
_TRACEBACK_RE = re.compile(r"\btraceback\b.*", re.IGNORECASE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    trailing = ""
    while raw and raw[-1] in ".,;)]}":
        trailing = raw[-1] + trailing
        raw = raw[:-1]
    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname
        if not hostname:
            return "[REDACTED_URL]" + trailing
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        try:
            port = f":{parsed.port}" if parsed.port is not None else ""
        except ValueError:
            port = ""
        safe = urlunsplit((parsed.scheme, f"{hostname}{port}", parsed.path, "", ""))
        return safe + trailing
    except ValueError:
        return "[REDACTED_URL]" + trailing


def sanitize_issue_message(message: str | None) -> str:
    """Return a bounded single-line diagnostic with common secret shapes removed."""
    text = " ".join(str(message or "").split())
    text = _SENSITIVE_TAIL_RE.sub(
        lambda match: f"{match.group('label')}=[REDACTED]",
        text,
    )
    text = _URL_RE.sub(_redact_url, text)
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _BASIC_AUTH_RE.sub(
        lambda match: f"{match.group('prefix') or ''}Basic [REDACTED]",
        text,
    )
    text = _RAW_SECRET_RE.sub("[REDACTED]", text)
    text = _SENSITIVE_VALUE_RE.sub(
        lambda match: f"{match.group('prefix')}[REDACTED]",
        text,
    )
    text = _TRACEBACK_RE.sub("traceback=[REDACTED]", text)
    text = " ".join(text.split())
    return text[:MAX_ISSUE_MESSAGE_LENGTH]


class SourceHealthService:
    """Read and apply production source outcomes for one user subscription."""

    def __init__(self, store: ServiceStore):
        self.store = store

    @staticmethod
    def _health(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        if data.get("last_issue_retryable") is not None:
            data["last_issue_retryable"] = bool(data["last_issue_retryable"])
        return data

    def get_health(self, subscription_id: str) -> dict[str, Any] | None:
        """Return persisted health, or None when the subscription is still unknown."""
        row = self.store.connect().execute(
            "SELECT * FROM user_source_health WHERE subscription_id = ?",
            (subscription_id,),
        ).fetchone()
        return self._health(row)

    def reset_source(
        self,
        *,
        workspace_id: str,
        source_id: str,
        commit: bool = True,
    ) -> int:
        """Reset subscriber health after a source's fetch identity changes."""
        conn = self.store.connect()
        try:
            deleted = conn.execute(
                """
                DELETE FROM user_source_health
                WHERE workspace_id = ? AND source_id = ?
                """,
                (workspace_id, source_id),
            )
            if commit:
                conn.commit()
            return deleted.rowcount
        except Exception:
            if commit and conn.in_transaction:
                conn.rollback()
            raise

    def user_projection(
        self,
        *,
        workspace_id: str,
        user_id: str,
        feed_window_days: int = DEFAULT_FEED_WINDOW_DAYS,
    ) -> dict[str, Any]:
        """Return the sanitized health projection for one authenticated user."""
        window = feed_window(feed_window_days)
        rows = self.store.connect().execute(
            """
            SELECT
                us.id AS subscription_id,
                us.source_id,
                sc.display_name AS source_display_name,
                sc.type AS source_type,
                health.status,
                health.last_attempt_at,
                health.last_success_at,
                health.last_failure_at,
                health.consecutive_failures,
                health.last_fetched_count,
                health.last_issue_stage,
                health.last_issue_code,
                health.last_issue_message,
                health.last_issue_retryable,
                health.last_job_id
            FROM user_subscriptions AS us
            JOIN users
              ON users.id = us.user_id
             AND users.workspace_id = ?
            JOIN source_catalog AS sc
              ON sc.id = us.source_id
             AND sc.workspace_id = ?
            LEFT JOIN user_source_health AS health
              ON health.subscription_id = us.id
             AND health.workspace_id = users.workspace_id
             AND health.user_id = us.user_id
             AND health.source_id = us.source_id
            WHERE us.user_id = ?
            ORDER BY us.priority DESC, us.created_at
            """,
            (workspace_id, workspace_id, user_id),
        ).fetchall()
        summary = {
            "total": 0,
            "unknown": 0,
            "healthy": 0,
            "degraded": 0,
            "failing": 0,
        }
        items: list[dict[str, Any]] = []
        source_counts = UserContentStore(self.store).source_item_counts(
            workspace_id=workspace_id,
            user_id=user_id,
            window=window,
        )
        for row in rows:
            status = str(row["status"] or "unknown")
            issue_values = (
                row["last_issue_stage"],
                row["last_issue_code"],
                row["last_issue_message"],
                row["last_issue_retryable"],
            )
            last_issue = None
            if any(value is not None for value in issue_values):
                last_issue = {
                    "stage": row["last_issue_stage"],
                    "code": row["last_issue_code"],
                    "message": row["last_issue_message"],
                    "retryable": bool(row["last_issue_retryable"]),
                }
            items.append(
                {
                    "subscription_id": row["subscription_id"],
                    "source_id": row["source_id"],
                    "source_display_name": row["source_display_name"],
                    "source_type": row["source_type"],
                    "status": status,
                    "last_attempt_at": row["last_attempt_at"],
                    "last_success_at": row["last_success_at"],
                    "last_failure_at": row["last_failure_at"],
                    "consecutive_failures": int(row["consecutive_failures"] or 0),
                    "last_fetched_count": int(row["last_fetched_count"] or 0),
                    "today_item_count": source_counts.get(
                        str(row["source_id"]), {}
                    ).get("today_item_count", 0),
                    "feed_item_count": source_counts.get(
                        str(row["source_id"]), {}
                    ).get("feed_item_count", 0),
                    "current_item_count": source_counts.get(
                        str(row["source_id"]), {}
                    ).get("current_item_count", 0),
                    "history_item_count": source_counts.get(
                        str(row["source_id"]), {}
                    ).get("history_item_count", 0),
                    "last_issue": last_issue,
                    "last_job_id": row["last_job_id"],
                }
            )
            summary["total"] += 1
            summary[status] += 1
        return {
            "schema_version": 1,
            "scope": "user",
            "summary": summary,
            "items": items,
            "window": window.as_dict(),
        }

    def apply_outcomes(
        self,
        *,
        workspace_id: str,
        user_id: str,
        job_id: str,
        attempted_at: str,
        outcomes: Iterable[SourceOutcome],
        commit: bool = True,
    ) -> list[dict[str, Any]]:
        """Apply source outcomes atomically after validating subscription ownership."""
        conn = self.store.connect()
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        applied_subscription_ids: list[str] = []
        try:
            job = conn.execute(
                """
                SELECT workspace_id, user_id, source_id, subscription_id, job_type
                FROM fetch_jobs
                WHERE id = ?
                """,
                (job_id,),
            ).fetchone()
            if (
                job is None
                or job["workspace_id"] != workspace_id
                or job["user_id"] != user_id
                or job["job_type"] not in {"user_feed_refresh", "source_fetch"}
            ):
                raise PermissionError("source health job scope or ownership mismatch")

            for outcome in outcomes:
                subscription_id = outcome.subscription_id
                if not subscription_id:
                    continue
                if job["job_type"] == "source_fetch" and (
                    not job["source_id"]
                    or job["source_id"] != outcome.source_id
                    or (
                        job["subscription_id"]
                        and job["subscription_id"] != subscription_id
                    )
                ):
                    raise PermissionError("source health job scope or ownership mismatch")
                ownership = conn.execute(
                    """
                    SELECT
                        us.id,
                        us.user_id,
                        us.source_id,
                        users.workspace_id AS user_workspace_id,
                        source_catalog.workspace_id AS source_workspace_id
                    FROM user_subscriptions AS us
                    JOIN users ON users.id = us.user_id
                    JOIN source_catalog ON source_catalog.id = us.source_id
                    WHERE us.id = ?
                    """,
                    (subscription_id,),
                ).fetchone()
                if ownership is None:
                    raise PermissionError("source outcome ownership mismatch")
                if (
                    ownership["user_id"] != user_id
                    or ownership["source_id"] != outcome.source_id
                    or ownership["user_workspace_id"] != workspace_id
                    or ownership["source_workspace_id"] != workspace_id
                ):
                    raise PermissionError("source outcome ownership mismatch")

                now = _now_iso()
                application = conn.execute(
                    """
                    INSERT OR IGNORE INTO user_source_health_applications (
                        subscription_id, job_id, applied_at
                    ) VALUES (?, ?, ?)
                    """,
                    (subscription_id, job_id, now),
                )
                if application.rowcount == 0:
                    applied_subscription_ids.append(subscription_id)
                    continue

                current = conn.execute(
                    "SELECT * FROM user_source_health WHERE subscription_id = ?",
                    (subscription_id,),
                ).fetchone()
                if current is not None and current["last_job_id"] == job_id:
                    applied_subscription_ids.append(subscription_id)
                    continue

                fetched_count = max(int(outcome.fetched_count), 0)
                if outcome.status == "succeeded":
                    status = "healthy"
                    consecutive_failures = 0
                    last_success_at = attempted_at
                    last_failure_at = current["last_failure_at"] if current is not None else None
                    issue_stage = None
                    issue_code = None
                    issue_message = None
                    issue_retryable = None
                elif outcome.status == "failed":
                    consecutive_failures = (
                        int(current["consecutive_failures"] or 0) + 1
                        if current is not None
                        else 1
                    )
                    status = "degraded" if consecutive_failures == 1 else "failing"
                    last_success_at = current["last_success_at"] if current is not None else None
                    last_failure_at = attempted_at
                    issue_stage = outcome.issue.stage if outcome.issue else None
                    issue_code = outcome.issue.code if outcome.issue else None
                    issue_message = (
                        sanitize_issue_message(outcome.issue.message)
                        if outcome.issue
                        else None
                    )
                    issue_retryable = (
                        None if outcome.issue is None else int(outcome.issue.retryable)
                    )
                else:
                    raise ValueError(f"unsupported source outcome status: {outcome.status}")

                created_at = current["created_at"] if current is not None else now
                conn.execute(
                    """
                    INSERT INTO user_source_health (
                        subscription_id, workspace_id, user_id, source_id, status,
                        last_attempt_at, last_success_at, last_failure_at,
                        consecutive_failures, last_fetched_count,
                        last_issue_stage, last_issue_code, last_issue_message,
                        last_issue_retryable, last_job_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(subscription_id) DO UPDATE SET
                        workspace_id = excluded.workspace_id,
                        user_id = excluded.user_id,
                        source_id = excluded.source_id,
                        status = excluded.status,
                        last_attempt_at = excluded.last_attempt_at,
                        last_success_at = excluded.last_success_at,
                        last_failure_at = excluded.last_failure_at,
                        consecutive_failures = excluded.consecutive_failures,
                        last_fetched_count = excluded.last_fetched_count,
                        last_issue_stage = excluded.last_issue_stage,
                        last_issue_code = excluded.last_issue_code,
                        last_issue_message = excluded.last_issue_message,
                        last_issue_retryable = excluded.last_issue_retryable,
                        last_job_id = excluded.last_job_id,
                        updated_at = excluded.updated_at
                    """,
                    (
                        subscription_id,
                        workspace_id,
                        user_id,
                        outcome.source_id,
                        status,
                        attempted_at,
                        last_success_at,
                        last_failure_at,
                        consecutive_failures,
                        fetched_count,
                        issue_stage,
                        issue_code,
                        issue_message,
                        issue_retryable,
                        job_id,
                        created_at,
                        now,
                    ),
                )
                applied_subscription_ids.append(subscription_id)
            if commit:
                conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise

        rows: list[dict[str, Any]] = []
        for subscription_id in dict.fromkeys(applied_subscription_ids):
            health = self.get_health(subscription_id)
            if health is not None:
                rows.append(health)
        return rows
