"""Private translation cache, idempotent job admission and safe public state."""

from datetime import datetime, timedelta, timezone

from ..storage.content_translation_schema import ready
from .content_translation_input import TranslationError, prepare_input
from .job_queue import JobQueue


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def prune_translations(store):
    conn = store.connect()
    if ready(conn):
        conn.execute("DELETE FROM content_translations WHERE expires_at <= ?", (now_iso(),))
        conn.commit()


class ContentTranslationService:
    def __init__(self, store):
        self.store = store

    def require_ready(self):
        if not ready(self.store.connect()):
            raise TranslationError("translation_migration_required", "翻译功能需要管理员完成数据库升级。", 503)

    def get(self, user, article_id):
        self.require_ready()
        source = prepare_input(self.store, user, article_id)
        row = self._row(source.cache_key)
        return self._public(row, source)

    def _row(self, key):
        row = self.store.connect().execute(
            "SELECT * FROM content_translations WHERE cache_key=? AND expires_at>?",
            (key, now_iso()),
        ).fetchone()
        return dict(row) if row else None

    def _public(self, row, source, *, job_id=None):
        selected_job = job_id or (row or {}).get("job_id")
        job = JobQueue(self.store).get_job(selected_job) if selected_job else None
        success = bool(row and row["translated_text"])
        status = "succeeded" if success else job["status"] if job else "idle"
        if status not in {"idle", "queued", "running", "succeeded"} or (status == "succeeded" and not success):
            status = "failed"
        error = None
        if status == "failed":
            error = {"code": "translation_failed", "message": "翻译未完成，请重试。", "retryable": True}
            messages = {
                "quota_exceeded": "AI 额度不足，请稍后重试。",
                "translation_model_unavailable": "请在 AI 设置中配置可用模型。",
                "translation_input_changed": "正文或模型配置已变化，请重新翻译。",
                "translation_provider_failed": "模型调用失败，请检查 AI 设置后重试。",
                "translation_invalid_output": "模型返回的译文无效，请重试。",
                "translation_incomplete": "模型未返回完整译文，请重试。",
                "lease_expired": "翻译任务已中断，请重试。",
            }
            code = (job or {}).get("error_code")
            if code in messages:
                error = {"code": code, "message": messages[code], "retryable": True}
        return {
            "status": status, "job_id": selected_job, "translation": row["translated_text"] if success else None,
            "scope": source.scope, "source_truncated": source.truncated, "cached": success,
            "expires_at": row["expires_at"] if success else None, "error": error,
        }

    def request(self, user, article_id, request_id):
        self.require_ready()
        source = prepare_input(self.store, user, article_id)
        conn = self.store.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM content_translations WHERE expires_at<=?", (now_iso(),))
            previous = conn.execute(
                "SELECT cache_key,job_id FROM content_translation_requests WHERE workspace_id=? AND user_id=? AND request_id=?",
                (user["workspace_id"], user["id"], request_id),
            ).fetchone()
            if previous and previous["cache_key"] != source.cache_key:
                raise TranslationError("translation_request_conflict", "正文或模型配置已变化，请重新发起翻译。")
            row = self._row(source.cache_key)
            state = self._public(row, source, job_id=previous["job_id"] if previous else None)
            if not previous and state["status"] not in {"succeeded", "queued", "running"}:
                row = self._enqueue(user, article_id, source)
                state = self._public(row, source)
            if not previous:
                conn.execute(
                    "INSERT INTO content_translation_requests VALUES(?,?,?,?,?)",
                    (user["workspace_id"], user["id"], request_id, source.cache_key, state["job_id"]),
                )
            conn.commit()
            return state
        except Exception:
            conn.rollback()
            raise

    def _enqueue(self, user, article_id, source):
        from .quota import QuotaService

        QuotaService(self.store).admit_ai_item(
            workspace_id=user["workspace_id"], user_id=user["id"], provider=source.config.provider.value,
        )
        job = JobQueue(self.store).create_job(
            workspace_id=user["workspace_id"], user_id=user["id"], job_type="content_translate",
            payload={"article_id": article_id, "cache_key": source.cache_key},
            max_attempts=1, retention_days=30, commit=False,
        )
        now = datetime.now(timezone.utc)
        self.store.connect().execute(
            """INSERT INTO content_translations VALUES(?,?,?,?,?,NULL,?,?,?,?)
            ON CONFLICT(cache_key) DO UPDATE SET job_id=excluded.job_id,
                translated_text=NULL,created_at=excluded.created_at,expires_at=excluded.expires_at""",
            (source.cache_key, user["workspace_id"], user["id"], article_id, job["id"], source.scope,
             int(source.truncated), now.isoformat(), (now + timedelta(days=30)).isoformat()),
        )
        return self._row(source.cache_key)
