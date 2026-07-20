"""User-scoped SQLite cache for successful AI analysis results."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from ..ai.analysis_cache import (
    ANALYSIS_PROMPT_VERSION,
    AnalysisCache,
    apply_analysis_result,
    safe_analysis_result,
)
from ..models import ContentItem
from ..storage.service_store import ServiceStore
from .job_eligibility import JobEligibilityService
from .quota import QuotaExceeded, QuotaService


class UserAnalysisCache:
    """AnalysisCache-compatible adapter that never reuses data across users."""

    def __init__(
        self,
        store: ServiceStore,
        *,
        workspace_id: str,
        user_id: str,
        job_id: str | None = None,
    ):
        self.service_store = ServiceStore(store.data_dir, db_path=store.db_path)
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.job_id = job_id

    @staticmethod
    def content_hash(item: ContentItem) -> str:
        return AnalysisCache.content_hash(item)

    @staticmethod
    def _safe_stored_result(item_json: str) -> dict[str, object] | None:
        try:
            stored = json.loads(item_json)
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(stored, dict):
            return None
        presentation = stored.get("presentation")
        analysis = presentation.get("analysis") if isinstance(presentation, dict) else {}
        taxonomy = presentation.get("taxonomy") if isinstance(presentation, dict) else {}
        content = presentation.get("content") if isinstance(presentation, dict) else {}
        if not isinstance(analysis, dict):
            analysis = {}
        if not isinstance(taxonomy, dict):
            taxonomy = {}
        if not isinstance(content, dict):
            content = {}
        # Stable content may contain source excerpts and fallback projections;
        # only a positively identified prior AI projection is reusable.
        if analysis.get("status") != "ai":
            return None
        summary = analysis.get("summary_zh") or stored.get("summary_zh")
        score = analysis.get("score") if analysis.get("score") is not None else stored.get("score")
        if not summary or score is None:
            return None
        topics = taxonomy.get("topics") or stored.get("topics") or stored.get("tags") or []
        entities = taxonomy.get("entities") or stored.get("entities") or []
        result = {
            "score": score,
            "summary": summary,
            "summary_zh": summary,
            "channel": taxonomy.get("channel") or stored.get("channel") or stored.get("category") or "",
            "topics": topics if isinstance(topics, list) else [],
            "tags": topics if isinstance(topics, list) else [],
            "entities": entities if isinstance(entities, list) else [],
            "signal_strength": analysis.get("signal_strength") or stored.get("signal_strength") or "",
            "signal_type": analysis.get("signal_type") or stored.get("signal_type") or "",
            "is_featured": bool(stored.get("is_featured")),
        }
        if content.get("format_origin") == "ai":
            result["content_format"] = content.get("format")
        return result

    def apply(
        self,
        item: ContentItem,
        *,
        model: str,
        prompt_version: str = ANALYSIS_PROMPT_VERSION,
    ) -> bool:
        input_hash = self.content_hash(item)
        row = self.service_store.connect().execute(
            """
            SELECT result_json, model
            FROM user_analysis_cache
            WHERE workspace_id = ? AND user_id = ? AND article_id = ?
              AND input_hash = ? AND model = ? AND prompt_version = ?
            """,
            (
                self.workspace_id,
                self.user_id,
                item.id,
                input_hash,
                model,
                prompt_version,
            ),
        ).fetchone()
        reused_across_model = False
        if row is None:
            row = self.service_store.connect().execute(
                """
                SELECT result_json, model
                FROM user_analysis_cache
                WHERE workspace_id = ? AND user_id = ? AND article_id = ?
                  AND input_hash = ? AND prompt_version = ?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (
                    self.workspace_id,
                    self.user_id,
                    item.id,
                    input_hash,
                    prompt_version,
                ),
            ).fetchone()
            reused_across_model = row is not None
        source_model = str(row["model"]) if row is not None else ""
        if row is None:
            stored = self.service_store.connect().execute(
                """
                SELECT item_json
                FROM user_content_items
                WHERE workspace_id = ? AND user_id = ? AND article_id = ?
                  AND analysis_input_hash = ?
                LIMIT 1
                """,
                (self.workspace_id, self.user_id, item.id, input_hash),
            ).fetchone()
            if stored is None:
                return False
            result = self._safe_stored_result(str(stored["item_json"] or ""))
            if result is None:
                return False
            reused_across_model = True
            source_model = "stored-content"
        else:
            try:
                result = json.loads(row["result_json"])
            except (TypeError, json.JSONDecodeError):
                return False
        if not isinstance(result, dict):
            return False
        apply_analysis_result(item, result)
        item.metadata["analysis_cache_hit"] = True
        if reused_across_model:
            item.metadata["analysis_reused_across_model"] = True
            item.metadata["analysis_source_model"] = source_model
        return True

    def store(
        self,
        item: ContentItem,
        *,
        model: str,
        prompt_version: str = ANALYSIS_PROMPT_VERSION,
    ) -> None:
        if item.ai_score is None or item.metadata.get("analysis_status") != "ai":
            return
        now = datetime.now(timezone.utc).isoformat()
        connection = self.service_store.connect()
        connection.execute(
            """
            INSERT INTO user_analysis_cache (
                workspace_id, user_id, article_id, input_hash, model,
                prompt_version, result_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, article_id, input_hash, model, prompt_version)
            DO UPDATE SET result_json = excluded.result_json, updated_at = excluded.updated_at
            """,
            (
                self.workspace_id,
                self.user_id,
                item.id,
                self.content_hash(item),
                model,
                prompt_version,
                json.dumps(safe_analysis_result(item), ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        connection.commit()

    def _quota(self) -> QuotaService:
        return QuotaService(
            self.service_store,
            max_ai_items_per_day=int(
                os.getenv("INFOHUB_MAX_AI_ITEMS_PER_DAY", "1000")
            ),
            max_workspace_ai_attempts_per_day=int(
                os.getenv("INFOHUB_MAX_WORKSPACE_AI_ATTEMPTS_PER_DAY", "1000")
            ),
        )

    def before_ai_item(self, *, provider: str) -> None:
        """Admit one logical cache-miss item before any provider retries."""

        quota = self._quota()
        try:
            quota.admit_ai_item(
                workspace_id=self.workspace_id,
                user_id=self.user_id,
                provider=provider,
            )
        except QuotaExceeded:
            quota.record_quota_reject(
                workspace_id=self.workspace_id,
                user_id=self.user_id,
                quota="ai_item",
                provider=provider,
            )
            raise

    def before_ai_attempt(self, *, provider: str) -> None:
        """Admit and meter one actual provider network attempt."""

        quota = self._quota()
        try:
            quota.admit_ai_attempt(
                workspace_id=self.workspace_id,
                user_id=self.user_id,
                provider=provider,
            )
        except QuotaExceeded:
            quota.record_quota_reject(
                workspace_id=self.workspace_id,
                user_id=self.user_id,
                quota="ai_attempt",
                provider=provider,
            )
            raise

    def _require_job_attempt(self, *, source_id: str | None = None) -> None:
        if self.job_id:
            JobEligibilityService(self.service_store).require_current_attempt(
                self.job_id,
                source_id=source_id or None,
            )

    def before_ai_item_for_source(
        self,
        *,
        provider: str,
        source_id: str | None,
    ) -> None:
        """Check current source eligibility before charging a logical AI miss."""

        self._require_job_attempt(source_id=source_id)
        self.before_ai_item(provider=provider)

    def before_ai_network_attempt(
        self,
        *,
        provider: str,
        source_id: str | None,
    ) -> None:
        """Check current source eligibility before each real provider retry."""

        self._require_job_attempt(source_id=source_id)
        self.before_ai_attempt(provider=provider)

    def prune(self, *, retention_days: int = 30) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(retention_days, 1))).isoformat()
        cursor = self.service_store.connect().execute(
            "DELETE FROM user_analysis_cache WHERE user_id = ? AND updated_at < ?",
            (self.user_id, cutoff),
        )
        self.service_store.connect().commit()
        return max(int(cursor.rowcount), 0)

    def close(self) -> None:
        self.service_store.close()
