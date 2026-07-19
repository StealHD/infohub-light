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
        max_workspace_ai_attempts_per_day: int = 1000,
        max_workspace_fetch_attempts_per_day: int = 100,
        max_provider_fetch_attempts_per_day: int = 100,
    ) -> None:
        self.store = store
        self.max_fetch_jobs_per_day = int(max_fetch_jobs_per_day)
        self.max_sources_per_user = int(max_sources_per_user)
        self.max_ai_items_per_day = int(max_ai_items_per_day)
        self.max_workspace_ai_attempts_per_day = int(
            max_workspace_ai_attempts_per_day
        )
        self.max_workspace_fetch_attempts_per_day = int(
            max_workspace_fetch_attempts_per_day
        )
        self.max_provider_fetch_attempts_per_day = int(
            max_provider_fetch_attempts_per_day
        )

    @staticmethod
    def _today_start(now: datetime | None = None) -> datetime:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        else:
            now = now.astimezone(timezone.utc)
        return datetime.combine(now.date(), time.min, tzinfo=timezone.utc)

    def ensure_job_allowed(
        self,
        *,
        workspace_id: str,
        user_id: str,
        now: datetime | None = None,
    ) -> None:
        used = self.store.count_usage_since(
            workspace_id=workspace_id,
            user_id=user_id,
            event_types=["source_test", "source_fetch", "user_feed_refresh"],
            since=self._today_start(now),
        )
        if used >= self.max_fetch_jobs_per_day:
            raise QuotaExceeded("daily fetch job quota exceeded")

    def ensure_source_allowed(
        self,
        *,
        workspace_id: str,
        user_id: str,
        source_id: str,
    ) -> None:
        final_state = self.store.connect().execute(
            """
            SELECT
                sc.enabled AS source_enabled,
                COALESCE(us.enabled, 0) AS subscription_enabled
            FROM source_catalog sc
            LEFT JOIN user_subscriptions us
              ON us.source_id = sc.id AND us.user_id = ?
            WHERE sc.id = ? AND sc.workspace_id = ?
            LIMIT 1
            """,
            (user_id, source_id, workspace_id),
        ).fetchone()
        # Admission is based on the final active pair, not the requested
        # subscription flag alone. A disabled source cannot consume active
        # capacity, and an already-enabled subscription is idempotent. Real
        # source false->true transitions use ensure_source_reenable_allowed().
        if final_state is not None and (
            not bool(final_state["source_enabled"])
            or bool(final_state["subscription_enabled"])
        ):
            return
        self._ensure_active_source_capacity(
            workspace_id=workspace_id,
            user_id=user_id,
        )

    def ensure_source_reenable_allowed(
        self,
        *,
        workspace_id: str,
        user_id: str,
        source_id: str,
    ) -> None:
        """Admit a real disabled-to-enabled source transition.

        Unlike ``ensure_source_allowed``, this helper deliberately has no
        enabled-subscription idempotence shortcut: its caller has established
        that enabling ``source_id`` will add one active source for the user.
        """

        del source_id  # the transition target is not part of the current count
        self._ensure_active_source_capacity(
            workspace_id=workspace_id,
            user_id=user_id,
        )

    def _ensure_active_source_capacity(
        self,
        *,
        workspace_id: str,
        user_id: str,
    ) -> None:
        row = self.store.connect().execute(
            """
            SELECT COUNT(*) AS total
            FROM user_subscriptions us
            JOIN source_catalog sc ON sc.id = us.source_id
            WHERE us.user_id = ?
              AND sc.workspace_id = ?
              AND us.enabled = 1
              AND sc.enabled = 1
            """,
            (user_id, workspace_id),
        ).fetchone()
        used = int(row["total"] if row is not None else 0)
        if used >= self.max_sources_per_user:
            raise QuotaExceeded("enabled source quota exceeded")

    def admit_ai_item(
        self,
        *,
        workspace_id: str,
        user_id: str,
        provider: str,
        now: datetime | None = None,
    ) -> None:
        conn = self.store.connect()
        owns_transaction = not conn.in_transaction
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            used = self.store.count_usage_since(
                workspace_id=workspace_id,
                user_id=user_id,
                event_types=["ai_item"],
                since=self._today_start(now),
            )
            if used >= self.max_ai_items_per_day:
                raise QuotaExceeded("daily AI item quota exceeded")
            self.store.record_usage_event(
                workspace_id=workspace_id,
                user_id=user_id,
                event_type="ai_item",
                provider=provider,
                commit=False,
            )
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise

    def admit_fetch_attempt(
        self,
        *,
        workspace_id: str,
        user_id: str,
        provider: str,
        source_id: str | None = None,
        now: datetime | None = None,
    ) -> None:
        conn = self.store.connect()
        owns_transaction = not conn.in_transaction
        since = self._today_start(now).isoformat()
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            workspace_row = conn.execute(
                """
                SELECT COALESCE(SUM(quantity), 0) AS total
                FROM usage_events
                WHERE workspace_id = ?
                  AND event_type = 'fetch_attempt'
                  AND created_at >= ?
                """,
                (workspace_id, since),
            ).fetchone()
            if int(workspace_row["total"] or 0) >= self.max_workspace_fetch_attempts_per_day:
                raise QuotaExceeded("workspace fetch attempt quota exceeded")
            provider_row = conn.execute(
                """
                SELECT COALESCE(SUM(quantity), 0) AS total
                FROM usage_events
                WHERE workspace_id = ?
                  AND event_type = 'fetch_attempt'
                  AND provider = ?
                  AND created_at >= ?
                """,
                (workspace_id, provider, since),
            ).fetchone()
            if int(provider_row["total"] or 0) >= self.max_provider_fetch_attempts_per_day:
                raise QuotaExceeded("provider fetch attempt quota exceeded")
            self.store.record_usage_event(
                workspace_id=workspace_id,
                user_id=user_id,
                event_type="fetch_attempt",
                provider=provider,
                metadata={"source_id": source_id} if source_id else None,
                commit=False,
            )
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise

    def admit_ai_attempt(
        self,
        *,
        workspace_id: str,
        user_id: str,
        provider: str,
        now: datetime | None = None,
    ) -> None:
        conn = self.store.connect()
        owns_transaction = not conn.in_transaction
        since = self._today_start(now).isoformat()
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT COALESCE(SUM(quantity), 0) AS total
                FROM usage_events
                WHERE workspace_id = ?
                  AND event_type = 'ai_attempt'
                  AND created_at >= ?
                """,
                (workspace_id, since),
            ).fetchone()
            if int(row["total"] or 0) >= self.max_workspace_ai_attempts_per_day:
                raise QuotaExceeded("workspace AI attempt quota exceeded")
            self.store.record_usage_event(
                workspace_id=workspace_id,
                user_id=user_id,
                event_type="ai_attempt",
                provider=provider,
                commit=False,
            )
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise

    def record_job_usage(
        self,
        *,
        workspace_id: str,
        user_id: str,
        event_type: str,
        commit: bool = True,
    ) -> None:
        self.store.record_usage_event(
            workspace_id=workspace_id,
            user_id=user_id,
            event_type=event_type,
            quantity=1,
            commit=commit,
        )

    def record_quota_reject(
        self,
        *,
        workspace_id: str,
        user_id: str,
        quota: str,
        provider: str | None = None,
        commit: bool = True,
    ) -> None:
        """Persist one safe aggregate rejection without sensitive request data."""

        self.store.record_usage_event(
            workspace_id=workspace_id,
            user_id=user_id,
            event_type="quota_reject",
            provider=provider,
            metadata={"quota": str(quota)[:64]},
            commit=commit,
        )
