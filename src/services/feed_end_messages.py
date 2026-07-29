"""Safe workspace-scoped terminal copy for Feed collection pages."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ..ai.client import AIClient, create_ai_client
from ..models import Config
from ..storage.manager import StorageManager
from ..storage.service_store import ServiceStore
from .quota import QuotaService


logger = logging.getLogger(__name__)

FEED_END_MESSAGE_SCENES = ("empty", "first_end", "repeat_end")
FEED_END_MESSAGE_RETRY_HOURS = 6
FEED_END_MESSAGE_TIMEOUT_SECONDS = 60
FEED_END_MESSAGE_LEASE_SECONDS = 75
FEED_END_MESSAGE_CONTRACT_VERSION = 2
FEED_END_MESSAGE_DECORATIONS = (
    "🙂",
    "😊",
    "🌿",
    "☕️",
    "☕",
    "✨",
    "📚",
    "🍵",
    "🌙",
    "🫧",
    "^_^",
    ":)",
    ":-)",
    "(・ω・)",
    "(´▽｀)",
    "(｡･ω･｡)",
)

BUILTIN_FEED_END_MESSAGES: dict[str, list[str]] = {
    "empty": [
        "这里暂时很安静。🌿",
        "这一页目前没有可显示的内容。",
        "先留一点空白，换个条件再看看。",
    ],
    "first_end": [
        "这一轮内容先到这里。☕",
        "当前列表已经走到末尾。",
        "先停在这里，让信息沉淀一下。",
    ],
    "repeat_end": [
        "又到末尾了。^_^",
        "还是这里，当前列表没有更多内容。",
        "这次也到底了，先去别处看看。",
    ],
}

_SAFE_ERROR_CODE_RE = re.compile(r"^[a-z0-9_]{1,96}$")
_ALLOWED_MESSAGE_RE = re.compile(
    r"^[\u3400-\u4dbf\u4e00-\u9fffA-Za-z0-9"
    r"，。！？、；：…—（）《》“”‘’·％%+\-/ ]+$"
)
_URL_RE = re.compile(r"(?:https?://|www\.|[A-Za-z0-9-]+\.(?:com|cn|net|org)\b)", re.I)
_MARKUP_RE = re.compile(r"[<>{}\[\]#*_~`|\\]")
_MARKDOWN_PREFIX_RE = re.compile(r"^\s*[-+]\s")
_DECORATION_RE = re.compile(
    "|".join(
        re.escape(decoration)
        for decoration in sorted(
            FEED_END_MESSAGE_DECORATIONS,
            key=len,
            reverse=True,
        )
    )
)
_TRADITIONAL_ONLY_RE = re.compile(
    r"[這裡還讓與為個們來時會後於過麼說開關現見頁條終餘讀]"
)
_UNSAFE_TONE_RE = re.compile(
    r"(赶紧|快点|抓紧|马上去|立即去|别偷懒|不要偷懒|别再拖|"
    r"落后|羞耻|懒惰|焦虑|错过|拖延|"
    r"完成|搞定|办妥|处理完毕|操作成功)"
)


class FeedEndMessagesDisabled(ValueError):
    """Raised when a manual refresh is requested while generation is disabled."""

    code = "feed_end_messages_disabled"


class FeedEndMessagesOutputError(ValueError):
    """Raised when a model response violates the terminal-copy contract."""

    code = "feed_end_messages_invalid_output"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime:
    current = value or _utc_now()
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc(parsed)


def _safe_error_code(value: Any) -> str | None:
    candidate = str(value or "").strip().lower()
    return candidate if _SAFE_ERROR_CODE_RE.fullmatch(candidate) else None


def feed_end_messages_config_fingerprint(config: Config) -> str:
    """Hash only model identity and non-secret terminal-copy inputs."""

    payload = {
        "contract_version": FEED_END_MESSAGE_CONTRACT_VERSION,
        "provider": config.ai.provider.value,
        "model": config.ai.model,
        "feed_end_messages": config.feed_end_messages.model_dump(mode="json"),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_feed_end_message_lists(
    value: Any,
    *,
    expected_count: int | None,
) -> dict[str, list[str]]:
    """Validate exact scenes, count, uniqueness, plain text, and safe tone."""

    if not isinstance(value, dict) or set(value) != set(FEED_END_MESSAGE_SCENES):
        raise FeedEndMessagesOutputError(
            "output must contain exactly empty, first_end, and repeat_end"
        )
    normalized: dict[str, list[str]] = {}
    seen: set[str] = set()
    for scene in FEED_END_MESSAGE_SCENES:
        messages = value.get(scene)
        if not isinstance(messages, list):
            raise FeedEndMessagesOutputError(f"{scene} must be an array")
        if expected_count is not None and len(messages) != expected_count:
            raise FeedEndMessagesOutputError(
                f"{scene} must contain exactly {expected_count} messages"
            )
        if expected_count is None and not 3 <= len(messages) <= 30:
            raise FeedEndMessagesOutputError(
                f"{scene} must contain between 3 and 30 messages"
            )
        normalized[scene] = []
        for raw_message in messages:
            if not isinstance(raw_message, str):
                raise FeedEndMessagesOutputError("every message must be text")
            message = raw_message.strip()
            if message != raw_message or "\n" in message or "\r" in message or "\t" in message:
                raise FeedEndMessagesOutputError(
                    "messages must be trimmed single-line text"
                )
            if not 4 <= len(message) <= 40:
                raise FeedEndMessagesOutputError(
                    "messages must contain between 4 and 40 characters"
                )
            if not re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", message):
                raise FeedEndMessagesOutputError(
                    "messages must contain Simplified Chinese"
                )
            decorations = _DECORATION_RE.findall(message)
            plain_message = _DECORATION_RE.sub("", message)
            if (
                len(decorations) > 1
                or not _ALLOWED_MESSAGE_RE.fullmatch(plain_message)
                or _URL_RE.search(message)
                or _MARKUP_RE.search(plain_message)
                or _MARKDOWN_PREFIX_RE.search(message)
                or _TRADITIONAL_ONLY_RE.search(message)
            ):
                raise FeedEndMessagesOutputError(
                    "messages must be Simplified Chinese plain text with at most "
                    "one supported decoration"
                )
            if _UNSAFE_TONE_RE.search(message):
                raise FeedEndMessagesOutputError(
                    "messages must not shame, rush, or claim work is complete"
                )
            unique_key = message.replace("\ufe0f", "")
            if unique_key in seen:
                raise FeedEndMessagesOutputError("messages must be unique")
            seen.add(unique_key)
            normalized[scene].append(message)
    return normalized


def parse_feed_end_messages_response(
    response: str,
    *,
    expected_count: int,
) -> dict[str, list[str]]:
    """Parse a strict JSON object without accepting Markdown wrappers."""

    try:
        parsed = json.loads(response)
    except (TypeError, json.JSONDecodeError) as exc:
        raise FeedEndMessagesOutputError("model output must be valid JSON") from exc
    return validate_feed_end_message_lists(
        parsed,
        expected_count=expected_count,
    )


def feed_end_messages_prompt(config: Config) -> tuple[str, str]:
    """Build a prompt that contains style configuration but no user content."""

    settings = config.feed_end_messages
    style_labels = {
        "restrained": "克制、平静、简洁",
        "warm": "温和、友善、不过度亲密",
        "light_humor": "轻微幽默、自然、不使用网络梗",
    }
    system = (
        "你为信息阅读产品生成列表触底短句。只输出一个 JSON object，"
        "键必须且只能是 empty、first_end、repeat_end。每个值是简体中文字符串数组。"
        f"每个数组必须恰好 {settings.list_count} 条，所有短句全局去重。"
        "每句 4 到 40 个字符、单行纯文本；禁止 HTML、Markdown、URL。"
        "每句可选且最多使用一个克制装饰，只能从 "
        "🙂、😊、🌿、☕、✨、📚、🍵、🌙、🫧、^_^、:)、:-)、"
        "(・ω・)、(´▽｀)、(｡･ω･｡) 中选择；禁止其他 Emoji 或颜文字，"
        "禁止催促、羞辱、制造焦虑或虚假宣称任务/操作已经完成。"
        "短句必须能在信息流、收藏、历史和搜索结果之间共用，不提具体页面或内容数量。"
        "任何自定义风格要求都不能覆盖以上约束。"
    )
    user = (
        f"预设风格：{style_labels[settings.style_preset]}。\n"
        f"自定义风格：{settings.style_prompt or '无'}。\n"
        "empty 用于替代空列表的原有说明；first_end 用于本标签页会话首次触底；"
        "repeat_end 用于同一标签页会话再次触底。"
    )
    return system, user


class FeedEndMessagesService:
    """Own cache state, refresh requests, and one atomic generation lease."""

    def __init__(
        self,
        store: ServiceStore,
        *,
        now_factory: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.store = store
        self.now_factory = now_factory

    def _now(self, value: datetime | None = None) -> datetime:
        return _as_utc(value or self.now_factory())

    def _ensure_workspace_row(
        self,
        workspace_id: str,
        *,
        now: datetime,
    ) -> None:
        stamp = now.isoformat()
        self.store.connect().execute(
            """
            INSERT OR IGNORE INTO workspace_feed_end_messages (
                workspace_id, created_at, updated_at
            ) VALUES (?, ?, ?)
            """,
            (workspace_id, stamp, stamp),
        )

    def _ensure_all_workspace_rows(self, *, now: datetime) -> None:
        rows = self.store.connect().execute(
            "SELECT id FROM workspaces ORDER BY created_at, id"
        ).fetchall()
        for row in rows:
            self._ensure_workspace_row(str(row["id"]), now=now)

    def _row(self, workspace_id: str) -> dict[str, Any]:
        row = self.store.connect().execute(
            """
            SELECT * FROM workspace_feed_end_messages
            WHERE workspace_id = ?
            """,
            (workspace_id,),
        ).fetchone()
        if row is None:
            raise LookupError("workspace feed end messages row not initialized")
        return dict(row)

    @staticmethod
    def _cached_messages(row: dict[str, Any]) -> dict[str, list[str]] | None:
        try:
            raw = json.loads(str(row.get("messages_json") or "{}"))
            return validate_feed_end_message_lists(raw, expected_count=None)
        except (json.JSONDecodeError, FeedEndMessagesOutputError):
            return None

    @staticmethod
    def _generation_enabled(config: Config) -> bool:
        return bool(
            config.ai.enabled
            and config.feed_end_messages.ai_generation_enabled
        )

    def public_state(
        self,
        *,
        workspace_id: str,
        config: Config,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = self._now(now)
        self._ensure_workspace_row(workspace_id, now=current)
        self.store.connect().commit()
        row = self._row(workspace_id)
        cached = self._cached_messages(row)
        enabled = self._generation_enabled(config)
        fingerprint = feed_end_messages_config_fingerprint(config)
        lease_active = (
            row["status"] == "refreshing"
            and (_parse_time(row.get("lease_expires_at")) or current) > current
        )
        retry_at = _parse_time(row.get("retry_at"))
        next_refresh_at = _parse_time(row.get("next_refresh_at"))
        stale_config = str(row.get("config_fingerprint") or "") != fingerprint

        if not enabled:
            status = "disabled"
            source = "builtin"
            scenes = BUILTIN_FEED_END_MESSAGES
        else:
            source = "ai" if cached is not None else "builtin"
            scenes = cached or BUILTIN_FEED_END_MESSAGES
            if lease_active:
                status = "refreshing"
            elif (
                stale_config
                or bool(row.get("force_refresh"))
                or row["status"] == "pending"
                or (row["status"] == "refreshing" and not lease_active)
                or (next_refresh_at is not None and next_refresh_at <= current)
                or (cached is None and not retry_at)
            ):
                status = "pending"
            elif row["status"] == "failed" or (
                retry_at is not None and retry_at > current
            ):
                status = "degraded"
            elif cached is not None:
                status = "ready"
            else:
                status = "pending"

        return {
            "schema_version": 1,
            "source": source,
            "status": status,
            "generation": int(row.get("generation") or 0),
            "generated_at": row.get("last_success_at"),
            "last_attempt_at": row.get("last_attempt_at"),
            "next_refresh_at": (
                row.get("next_refresh_at") if enabled else None
            ),
            "retry_at": row.get("retry_at") if enabled else None,
            "last_error_code": (
                _safe_error_code(row.get("last_error_code")) if enabled else None
            ),
            "scenes": {scene: list(scenes[scene]) for scene in FEED_END_MESSAGE_SCENES},
        }

    def request_refresh(
        self,
        *,
        workspace_id: str,
        requested_by_user_id: str,
        config: Config,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not self._generation_enabled(config):
            raise FeedEndMessagesDisabled(
                "enable global AI and feed end message generation first"
            )
        current = self._now(now)
        conn = self.store.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._ensure_workspace_row(workspace_id, now=current)
            row = self._row(workspace_id)
            lease_active = (
                row["status"] == "refreshing"
                and (_parse_time(row.get("lease_expires_at")) or current) > current
            )
            if not lease_active and row["status"] != "pending":
                conn.execute(
                    """
                    UPDATE workspace_feed_end_messages
                    SET status = 'pending',
                        requested_by_user_id = ?,
                        force_refresh = 1,
                        retry_at = NULL,
                        last_error_code = NULL,
                        updated_at = ?
                    WHERE workspace_id = ?
                    """,
                    (
                        requested_by_user_id,
                        current.isoformat(),
                        workspace_id,
                    ),
                )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        return self.public_state(
            workspace_id=workspace_id,
            config=config,
            now=current,
        )

    def claim_due(
        self,
        *,
        config: Config,
        worker_id: str,
        now: datetime | None = None,
        lease_seconds: int = FEED_END_MESSAGE_LEASE_SECONDS,
    ) -> dict[str, Any] | None:
        if not self._generation_enabled(config):
            return None
        current = self._now(now)
        fingerprint = feed_end_messages_config_fingerprint(config)
        conn = self.store.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._ensure_all_workspace_rows(now=current)
            rows = conn.execute(
                """
                SELECT * FROM workspace_feed_end_messages
                ORDER BY updated_at, workspace_id
                """
            ).fetchall()
            for raw_row in rows:
                row = dict(raw_row)
                lease_expires_at = _parse_time(row.get("lease_expires_at"))
                if (
                    row["status"] == "refreshing"
                    and lease_expires_at is not None
                    and lease_expires_at > current
                ):
                    continue
                cached = self._cached_messages(row)
                retry_at = _parse_time(row.get("retry_at"))
                next_refresh_at = _parse_time(row.get("next_refresh_at"))
                fingerprint_changed = (
                    str(row.get("config_fingerprint") or "") != fingerprint
                )
                forced = bool(row.get("force_refresh"))
                retry_blocked = (
                    row["status"] == "failed"
                    and retry_at is not None
                    and retry_at > current
                    and not forced
                    and not fingerprint_changed
                )
                due = (
                    fingerprint_changed
                    or forced
                    or row["status"] in {"empty", "pending"}
                    or (row["status"] == "refreshing" and not lease_expires_at)
                    or (lease_expires_at is not None and lease_expires_at <= current)
                    or (retry_at is not None and retry_at <= current)
                    or (next_refresh_at is not None and next_refresh_at <= current)
                    or (cached is None and retry_at is None)
                )
                if retry_blocked or not due:
                    continue

                requested_user = None
                requested_by = str(row.get("requested_by_user_id") or "")
                if requested_by:
                    requested_user = conn.execute(
                        """
                        SELECT id FROM users
                        WHERE id = ? AND workspace_id = ? AND enabled = 1
                          AND role IN ('owner', 'admin')
                        """,
                        (requested_by, row["workspace_id"]),
                    ).fetchone()
                if requested_user is None:
                    requested_user = conn.execute(
                        """
                        SELECT id FROM users
                        WHERE workspace_id = ? AND enabled = 1
                          AND role IN ('owner', 'admin')
                        ORDER BY CASE role WHEN 'owner' THEN 0 ELSE 1 END,
                                 created_at, id
                        LIMIT 1
                        """,
                        (row["workspace_id"],),
                    ).fetchone()
                if requested_user is None:
                    retry = current + timedelta(
                        hours=FEED_END_MESSAGE_RETRY_HOURS
                    )
                    conn.execute(
                        """
                        UPDATE workspace_feed_end_messages
                        SET status = 'failed',
                            config_fingerprint = ?,
                            force_refresh = 0,
                            retry_at = ?,
                            last_attempt_at = ?,
                            last_error_code = 'feed_end_messages_no_admin',
                            updated_at = ?
                        WHERE workspace_id = ?
                        """,
                        (
                            fingerprint,
                            retry.isoformat(),
                            current.isoformat(),
                            current.isoformat(),
                            row["workspace_id"],
                        ),
                    )
                    continue

                claim_token = uuid.uuid4().hex
                lease_expires = current + timedelta(seconds=max(1, lease_seconds))
                conn.execute(
                    """
                    UPDATE workspace_feed_end_messages
                    SET status = 'refreshing',
                        config_fingerprint = ?,
                        requested_by_user_id = ?,
                        claim_token = ?,
                        claimed_by = ?,
                        lease_expires_at = ?,
                        last_attempt_at = ?,
                        updated_at = ?
                    WHERE workspace_id = ?
                    """,
                    (
                        fingerprint,
                        str(requested_user["id"]),
                        claim_token,
                        worker_id,
                        lease_expires.isoformat(),
                        current.isoformat(),
                        current.isoformat(),
                        row["workspace_id"],
                    ),
                )
                conn.commit()
                return {
                    "workspace_id": str(row["workspace_id"]),
                    "user_id": str(requested_user["id"]),
                    "claim_token": claim_token,
                    "config_fingerprint": fingerprint,
                }
            conn.commit()
            return None
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise

    def complete_success(
        self,
        claim: dict[str, Any],
        *,
        config: Config,
        messages: dict[str, list[str]],
        now: datetime | None = None,
    ) -> bool:
        validated = validate_feed_end_message_lists(
            messages,
            expected_count=config.feed_end_messages.list_count,
        )
        current = self._now(now)
        next_refresh = current + timedelta(
            days=config.feed_end_messages.refresh_days
        )
        cursor = self.store.connect().execute(
            """
            UPDATE workspace_feed_end_messages
            SET messages_json = ?,
                config_fingerprint = ?,
                generation = generation + 1,
                status = 'ready',
                force_refresh = 0,
                claim_token = NULL,
                claimed_by = NULL,
                lease_expires_at = NULL,
                last_attempt_at = ?,
                last_success_at = ?,
                next_refresh_at = ?,
                retry_at = NULL,
                last_error_code = NULL,
                updated_at = ?
            WHERE workspace_id = ?
              AND status = 'refreshing'
              AND claim_token = ?
            """,
            (
                json.dumps(
                    validated,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                claim["config_fingerprint"],
                current.isoformat(),
                current.isoformat(),
                next_refresh.isoformat(),
                current.isoformat(),
                claim["workspace_id"],
                claim["claim_token"],
            ),
        )
        self.store.connect().commit()
        return cursor.rowcount == 1

    def complete_failure(
        self,
        claim: dict[str, Any],
        *,
        error_code: str,
        now: datetime | None = None,
    ) -> bool:
        current = self._now(now)
        retry = current + timedelta(hours=FEED_END_MESSAGE_RETRY_HOURS)
        safe_code = _safe_error_code(error_code) or "feed_end_messages_generation_failed"
        cursor = self.store.connect().execute(
            """
            UPDATE workspace_feed_end_messages
            SET status = 'failed',
                force_refresh = 0,
                claim_token = NULL,
                claimed_by = NULL,
                lease_expires_at = NULL,
                last_attempt_at = ?,
                retry_at = ?,
                last_error_code = ?,
                updated_at = ?
            WHERE workspace_id = ?
              AND status = 'refreshing'
              AND claim_token = ?
            """,
            (
                current.isoformat(),
                retry.isoformat(),
                safe_code,
                current.isoformat(),
                claim["workspace_id"],
                claim["claim_token"],
            ),
        )
        self.store.connect().commit()
        return cursor.rowcount == 1


def _generation_error_code(exc: Exception) -> str:
    candidate = _safe_error_code(getattr(exc, "code", None))
    if candidate:
        return candidate
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "feed_end_messages_timeout"
    if isinstance(exc, FeedEndMessagesOutputError):
        return exc.code
    return "feed_end_messages_generation_failed"


def run_due_feed_end_messages_generation(
    *,
    data_dir: str,
    store: ServiceStore,
    worker_id: str,
    client_factory: Callable[[Any], AIClient] | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Run at most one bounded model call after the normal queue is empty."""

    try:
        config = StorageManager(data_dir=data_dir).load_config()
    except (FileNotFoundError, ValueError):
        return None
    service = FeedEndMessagesService(store)
    claim = service.claim_due(config=config, worker_id=worker_id, now=now)
    if claim is None:
        return None

    provider = config.ai.provider.value
    try:
        QuotaService(
            store,
            max_workspace_ai_attempts_per_day=int(
                os.getenv("INFOHUB_MAX_WORKSPACE_AI_ATTEMPTS_PER_DAY", "1000")
            ),
        ).admit_ai_attempt(
            workspace_id=claim["workspace_id"],
            user_id=claim["user_id"],
            provider=provider,
            now=now,
        )
        factory = client_factory or (
            lambda ai_config: create_ai_client(
                ai_config,
                single_attempt=True,
                timeout_seconds=FEED_END_MESSAGE_TIMEOUT_SECONDS,
            )
        )
        client = factory(config.ai)
        system, user = feed_end_messages_prompt(config)
        response = asyncio.run(
            asyncio.wait_for(
                client.complete(
                    system,
                    user,
                    temperature=0.4,
                    max_tokens=min(
                        int(config.ai.max_tokens),
                        max(1024, config.feed_end_messages.list_count * 150),
                    ),
                ),
                timeout=FEED_END_MESSAGE_TIMEOUT_SECONDS,
            )
        )
        messages = parse_feed_end_messages_response(
            response,
            expected_count=config.feed_end_messages.list_count,
        )
        accepted = service.complete_success(
            claim,
            config=config,
            messages=messages,
            now=now,
        )
        if not accepted:
            return {
                "ok": False,
                "job_type": "feed_end_messages_generation",
                "workspace_id": claim["workspace_id"],
                "error_code": "feed_end_messages_lease_lost",
            }
    except Exception as exc:
        if store.connect().in_transaction:
            store.connect().rollback()
        error_code = _generation_error_code(exc)
        service.complete_failure(claim, error_code=error_code, now=now)
        logger.warning(
            "feed end message generation failed workspace_id=%s code=%s",
            claim["workspace_id"],
            error_code,
        )
        return {
            "ok": False,
            "job_type": "feed_end_messages_generation",
            "workspace_id": claim["workspace_id"],
            "error_code": error_code,
        }

    logger.info(
        "feed end message generation succeeded workspace_id=%s count=%s",
        claim["workspace_id"],
        config.feed_end_messages.list_count,
    )
    return {
        "ok": True,
        "job_type": "feed_end_messages_generation",
        "workspace_id": claim["workspace_id"],
        "message_count": config.feed_end_messages.list_count,
    }
