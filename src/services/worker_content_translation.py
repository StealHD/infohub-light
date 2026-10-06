"""One-attempt translation jobs, with authorization and configuration rechecks."""

import asyncio
from datetime import datetime, timedelta, timezone

from ..ai.client import create_ai_client
from ..ai.translation import translate
from .content_translation import ContentTranslationService
from .content_translation_input import TranslationError, prepare_input
from .job_eligibility import JobEligibilityService
from .quota import QuotaExceeded, QuotaService


def current_input(store, job):
    JobEligibilityService(store).require_current_attempt(job["id"])
    current = store.connect().execute(
        "SELECT claim_token FROM fetch_jobs WHERE id=?", (job["id"],)
    ).fetchone()
    if not current or current["claim_token"] != job["claim_token"]:
        raise TranslationError("translation_claim_lost", "翻译任务已失效。")
    user = store.get_user(job["user_id"])
    if not user or user["workspace_id"] != job["workspace_id"]:
        raise TranslationError("translation_access_lost", "无法继续访问内容。")
    source = prepare_input(store, user, job["payload_json"]["article_id"])
    if source.cache_key != job["payload_json"]["cache_key"]:
        raise TranslationError("translation_input_changed", "正文或模型配置已变化，请重新翻译。")
    binding = store.connect().execute(
        "SELECT job_id,translated_text FROM content_translations WHERE cache_key=? AND expires_at>?",
        (source.cache_key, datetime.now(timezone.utc).isoformat()),
    ).fetchone()
    if not binding or binding["job_id"] != job["id"] or binding["translated_text"]:
        raise TranslationError("translation_claim_lost", "翻译任务已失效。")
    return source


async def _generate(store, job, source, factory):
    client = factory(source.config, single_attempt=True, timeout_seconds=60)

    def before_attempt():
        current_input(store, job)
        QuotaService(store).admit_ai_attempt(
            workspace_id=job["workspace_id"], user_id=job["user_id"], provider=source.config.provider.value,
        )

    try:
        return await translate(client, source.text, before_attempt)
    finally:
        await client.aclose()


def run_content_translation(job, *, data_dir, store, client_factory=None):
    ContentTranslationService(store).require_ready()
    try:
        source = current_input(store, job)
        text = asyncio.run(_generate(store, job, source, client_factory or create_ai_client))
        conn = store.connect()
        conn.execute("BEGIN IMMEDIATE")
        current_input(store, job)
        updated = conn.execute(
            "UPDATE content_translations SET translated_text=?,expires_at=? WHERE cache_key=? AND job_id=?",
            (text, (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(), source.cache_key, job["id"]),
        )
        if updated.rowcount != 1:
            raise TranslationError("translation_claim_lost", "翻译任务已失效。")
        # Worker commits the cache and terminal job together; no model I/O in this transaction.
        return {"translation_cached": True}
    except (TranslationError, QuotaExceeded):
        raise
    except Exception:
        # Never let provider exceptions leak prompt, translated body or credentials
        # through Worker exception logging / public job errors.
        raise TranslationError("translation_provider_failed", "模型调用失败，请检查 AI 设置后重试。") from None
