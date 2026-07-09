"""FastAPI entrypoint for the small-group InfoHub service API."""

from __future__ import annotations

import argparse
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..services.feed_archive import FeedArchiveService
from ..services.job_queue import JobQueue
from ..services.quota import QuotaExceeded, QuotaService
from ..services.user_item_state import UserItemStateStore
from ..services.source_type_registry import (
    SourceConfigError,
    list_source_types,
    source_key as build_source_key,
    validate_secret_env_name,
    validate_source_config,
)
from ..storage.service_store import ROLES, SOURCE_SCOPES, ServiceStore
from ..ui.auth import COOKIE_NAME
from ..config_migration import migrate_config_tag_layers
from ..ui.server import STATIC_DIR, _read_json, _write_json, apply_config_action, build_env_status, validate_config_data


_ENV_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_PREFIXES = ("sk-", "sk_", "AIza", "xai-", "gsk_", "hf_", "tp-")


class ApiError(Exception):
    """Structured API error converted to the public error envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        retryable: bool = False,
        action: str = "",
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.action = action


def ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def error_response(exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "ok": False,
            "error": {
                "code": exc.code,
                "message": exc.message,
                "retryable": exc.retryable,
                "action": exc.action,
            },
        },
    )


def _validate_secret_env(value: str | None) -> str | None:
    try:
        return validate_secret_env_name(value)
    except SourceConfigError as exc:
        raise ApiError(
            "invalid_secret_env",
            str(exc),
            status_code=400,
            action="Store the real secret in .env or the deployment environment.",
        ) from exc


def _is_admin(user: dict[str, Any]) -> bool:
    return user.get("role") in {"owner", "admin"}


def _sanitize_user(user: dict[str, Any]) -> dict[str, Any]:
    return ServiceStore.sanitize_user(user)


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreateRequest(BaseModel):
    username: str
    password: str
    role: str = "member"
    display_name: str | None = None
    enabled: bool = True


class UserPatchRequest(BaseModel):
    role: str | None = None
    display_name: str | None = None
    enabled: bool | None = None


class SourceCreateRequest(BaseModel):
    scope: str | None = None
    type: str
    display_name: str
    description: str = ""
    default_channel: str | None = None
    default_topics: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    secret_env: str | None = None
    enabled: bool = True


class SourcePatchRequest(BaseModel):
    display_name: str | None = None
    description: str | None = None
    default_channel: str | None = None
    default_topics: list[str] | None = None
    config: dict[str, Any] | None = None
    secret_env: str | None = None
    enabled: bool | None = None


class SubscriptionRequest(BaseModel):
    source_id: str
    enabled: bool = True
    override_channel: str | None = None
    override_topics: list[str] = Field(default_factory=list)
    personal_tags: list[str] = Field(default_factory=list)
    analysis_mode: str = "full"
    priority: int = 0


class SubscriptionPatchRequest(BaseModel):
    enabled: bool | None = None
    override_channel: str | None = None
    override_topics: list[str] | None = None
    personal_tags: list[str] | None = None
    analysis_mode: str | None = None
    priority: int | None = None


class JobCreateRequest(BaseModel):
    source_id: str | None = None
    subscription_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = 0


class ItemStatePatchRequest(BaseModel):
    is_read: bool | None = None
    is_saved: bool | None = None
    is_later: bool | None = None
    dismissed: bool | None = None


class ItemFeedbackRequest(BaseModel):
    feedback_type: str
    value: int | None = None
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConfigImportSourcesRequest(BaseModel):
    dry_run: bool = False
    subscribe_current_user: bool = True


class ConfigActionRequest(BaseModel):
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)


SOURCE_UPSERT_ACTIONS = {
    "upsert_rss": "rss",
    "upsert_github_release": "github_release",
    "upsert_github_user": "github_user",
    "upsert_reddit_subreddit": "reddit_subreddit",
    "upsert_telegram_channel": "telegram_channel",
    "upsert_apify_social_subscription": "apify_social",
}

SOURCE_DELETE_ACTIONS = {
    "delete_rss",
    "delete_github",
    "delete_reddit_subreddit",
    "delete_telegram_channel",
    "delete_apify_social_subscription",
}

SOURCE_META_KEYS = {
    "source_id",
    "subscription_id",
    "scope",
    "source_enabled",
    "subscription_enabled",
    "source_display_name",
}


def create_app(
    *,
    data_dir: Path | str = "data",
    static_dir: Path | str = STATIC_DIR,
) -> FastAPI:
    """Create the FastAPI app with a local SQLite-backed service store."""

    data_path = Path(data_dir)
    static_path = Path(static_dir)
    store = ServiceStore(data_path)
    store.initialize()
    queue = JobQueue(store)
    quota = QuotaService(
        store,
        max_fetch_jobs_per_day=int(os.getenv("INFOHUB_MAX_FETCH_JOBS_PER_DAY", "100")),
        max_sources_per_user=int(os.getenv("INFOHUB_MAX_SOURCES_PER_USER", "100")),
        max_ai_items_per_day=int(os.getenv("INFOHUB_MAX_AI_ITEMS_PER_DAY", "1000")),
    )
    feed_archive = FeedArchiveService(data_path, store=store)
    item_state = UserItemStateStore(store)

    app = FastAPI(title="InfoHub Light Service API")

    @app.exception_handler(ApiError)
    async def _api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc)

    @app.exception_handler(QuotaExceeded)
    async def _quota_error_handler(_request: Request, exc: QuotaExceeded) -> JSONResponse:
        return error_response(
            ApiError(
                exc.code,
                exc.message,
                status_code=429,
                action="Reduce job frequency or increase the workspace quota.",
            )
        )

    @app.exception_handler(ValueError)
    async def _value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
        return error_response(ApiError("invalid_request", str(exc), status_code=400))

    @app.exception_handler(RequestValidationError)
    async def _request_validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        message = "invalid request"
        if errors:
            first = errors[0]
            location = ".".join(str(part) for part in first.get("loc", []) if part != "body")
            detail = str(first.get("msg") or "invalid value")
            message = f"{location}: {detail}" if location else detail
        return error_response(
            ApiError(
                "invalid_request",
                message,
                status_code=400,
                action="Fix the request payload or query parameters.",
            )
        )

    def current_user(request: Request) -> dict[str, Any]:
        token = request.cookies.get(COOKIE_NAME)
        user = store.get_session_user(token)
        if not user:
            raise ApiError("unauthorized", "login required", status_code=401, action="Log in and retry.")
        return user

    def current_admin(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        if not _is_admin(user):
            raise ApiError("forbidden", "admin role required", status_code=403)
        return user

    def require_mutating_member(user: dict[str, Any]) -> None:
        if user.get("role") == "viewer":
            raise ApiError(
                "forbidden",
                "viewer users cannot change sources, subscriptions, or jobs",
                status_code=403,
            )

    def visible_source_or_404(source_id: str, user: dict[str, Any]) -> dict[str, Any]:
        for source in store.list_visible_sources(user):
            if source["id"] == source_id:
                return source
        raise ApiError("not_found", "source not found", status_code=404)

    def read_base_config() -> tuple[dict[str, Any], Any]:
        config_path = data_path / "config.json"
        if not config_path.exists():
            raise ApiError("config_not_found", "data/config.json not found", status_code=404)
        data = migrate_config_tag_layers(_read_json(config_path))
        config = validate_config_data(data)
        return data, config

    def write_base_config(data: dict[str, Any]) -> None:
        validate_config_data(data)
        _write_json(data_path / "config.json", migrate_config_tag_layers(data))

    def reset_service_sources(data: dict[str, Any]) -> dict[str, Any]:
        sources = data.setdefault("sources", {})
        sources["rss"] = []
        sources["github"] = []
        sources.setdefault("hackernews", {"enabled": False})
        sources["reddit"] = {
            **sources.get("reddit", {}),
            "enabled": False,
            "subreddits": [],
            "users": [],
        }
        sources["telegram"] = {
            **sources.get("telegram", {}),
            "enabled": False,
            "channels": [],
        }
        sources["apify_social"] = {
            **sources.get("apify_social", {}),
            "enabled": False,
            "subscriptions": [],
        }
        return sources

    def entry_from_record(record: dict[str, Any]) -> dict[str, Any]:
        entry = deepcopy(record.get("config") or {})
        entry["enabled"] = bool(record.get("subscription_enabled"))
        entry["source_id"] = record["source_id"]
        entry["subscription_id"] = record["subscription_id"]
        entry["scope"] = record["scope"]
        entry["source_enabled"] = bool(record.get("source_enabled"))
        entry["subscription_enabled"] = bool(record.get("subscription_enabled"))
        entry["source_display_name"] = record.get("display_name") or ""
        channel = record.get("override_channel") or record.get("default_channel")
        if channel:
            entry["channel"] = channel
            entry["category"] = channel
            if record.get("type") == "telegram_channel":
                entry["hub_channel"] = channel
        topics = record.get("override_topics") or record.get("default_topics") or []
        if topics:
            entry["topics"] = list(topics)
            entry["tags"] = list(topics)
        personal_tags = record.get("personal_tags") or []
        if personal_tags:
            entry["personal_tags"] = list(personal_tags)
        if record.get("analysis_mode"):
            entry["analysis_mode"] = record["analysis_mode"]
        if record.get("secret_env") and not entry.get("token_env"):
            entry["token_env"] = record["secret_env"]
        return entry

    def append_record_source(sources: dict[str, Any], record: dict[str, Any]) -> None:
        source_type = str(record.get("type") or "")
        entry = entry_from_record(record)
        if source_type == "rss":
            entry.setdefault("name", record.get("display_name") or "")
            sources["rss"].append(entry)
            return
        if source_type in {"github", "github_release", "github_user"}:
            if source_type == "github_release":
                entry.setdefault("type", "repo_releases")
            elif source_type == "github_user":
                entry.setdefault("type", "user_events")
            sources["github"].append(entry)
            return
        if source_type == "reddit_subreddit":
            sources["reddit"]["enabled"] = True
            sources["reddit"].setdefault("subreddits", []).append(entry)
            return
        if source_type == "telegram_channel":
            sources["telegram"]["enabled"] = True
            sources["telegram"].setdefault("channels", []).append(entry)
            return
        if source_type == "apify_social":
            sources["apify_social"]["enabled"] = True
            sources["apify_social"].setdefault("subscriptions", []).append(entry)
            return
        if source_type == "hackernews":
            sources["hackernews"] = {**entry, "enabled": bool(record.get("subscription_enabled"))}

    def build_config_data_for_user(base_data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
        data = deepcopy(base_data)
        sources = reset_service_sources(data)
        records = store.list_user_subscriptions_with_sources(
            workspace_id=user["workspace_id"],
            user_id=user["id"],
        )
        for record in records:
            append_record_source(sources, record)
        return data

    def config_response(user: dict[str, Any]) -> dict[str, Any]:
        base_data, _base_config = read_base_config()
        data = build_config_data_for_user(base_data, user)
        config = validate_config_data(data)
        return {
            "path": str(data_path / "config.json"),
            "config": data,
            "env_status": build_env_status(config),
            "service": {
                "current_user": _sanitize_user(user),
                "sources": store.list_visible_sources(user),
                "subscriptions": store.list_user_subscriptions(user["id"]),
            },
        }

    def source_entries_for_action(data: dict[str, Any], action: str) -> list[dict[str, Any]]:
        sources = data.setdefault("sources", {})
        if action == "upsert_rss":
            return sources.setdefault("rss", [])
        if action in {"upsert_github_release", "upsert_github_user"}:
            return sources.setdefault("github", [])
        if action == "upsert_reddit_subreddit":
            return sources.setdefault("reddit", {}).setdefault("subreddits", [])
        if action == "upsert_telegram_channel":
            return sources.setdefault("telegram", {}).setdefault("channels", [])
        if action == "upsert_apify_social_subscription":
            return sources.setdefault("apify_social", {}).setdefault("subscriptions", [])
        raise ApiError("unsupported_source_action", f"unsupported source action: {action}", status_code=400)

    def payload_index(payload: dict[str, Any]) -> int | None:
        raw = payload.get("index")
        if raw is None or raw == "":
            return None
        try:
            return int(raw)
        except (TypeError, ValueError) as exc:
            raise ApiError("invalid_index", "index must be an integer", status_code=400) from exc

    def source_item_for_upsert(data: dict[str, Any], action: str, payload: dict[str, Any]) -> dict[str, Any]:
        entries = source_entries_for_action(data, action)
        if not entries:
            raise ApiError("invalid_source_action", "source action did not produce an entry", status_code=400)
        idx = payload_index(payload)
        if idx is None:
            return entries[-1]
        if idx >= len(entries):
            raise ApiError("invalid_index", "index is out of range", status_code=400)
        return entries[idx]

    def source_display_name(source_type: str, item: dict[str, Any]) -> str:
        if source_type == "rss":
            return str(item.get("name") or item.get("url") or "RSS Source")
        if source_type == "github_release":
            return f"{item.get('owner')}/{item.get('repo')} releases"
        if source_type == "github_user":
            return str(item.get("username") or "GitHub User")
        if source_type == "reddit_subreddit":
            return f"r/{item.get('subreddit')}"
        if source_type == "telegram_channel":
            return f"@{item.get('channel')}"
        if source_type == "apify_social":
            return f"{item.get('platform')}:{item.get('target')}"
        return source_type

    def source_channel(item: dict[str, Any]) -> str | None:
        return item.get("channel") or item.get("category") or item.get("hub_channel")

    def source_default_channel(source_type: str, item: dict[str, Any]) -> str | None:
        if source_type == "telegram_channel":
            return item.get("hub_channel") or item.get("category")
        return source_channel(item)

    def source_topics(item: dict[str, Any]) -> list[str]:
        value = item.get("topics") or item.get("tags") or []
        return list(value) if isinstance(value, list) else []

    def source_personal_tags(item: dict[str, Any]) -> list[str]:
        value = item.get("personal_tags") or []
        return list(value) if isinstance(value, list) else []

    def source_secret_env(item: dict[str, Any]) -> str | None:
        return _validate_secret_env(item.get("secret_env") or item.get("token_env"))

    def catalog_config_from_item(item: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in item.items()
            if key not in SOURCE_META_KEYS
            and key
            not in {
                "enabled",
                "channel",
                "category",
                "hub_channel",
                "topics",
                "tags",
                "personal_tags",
                "analysis_mode",
                "token_env",
                "secret_env",
            }
        }

    def catalog_config_for_source_type(source_type: str, item: dict[str, Any]) -> dict[str, Any]:
        config = catalog_config_from_item(item)
        if source_type == "telegram_channel" and item.get("channel"):
            config["channel"] = item["channel"]
        return config

    def can_update_catalog_source(source: dict[str, Any], user: dict[str, Any]) -> bool:
        if source["scope"] != "private":
            return _is_admin(user)
        return source["owner_user_id"] == user["id"]

    def default_source_scope(user: dict[str, Any]) -> str:
        if user.get("role") == "viewer":
            raise ApiError("forbidden", "viewer cannot create sources", status_code=403)
        return "public" if _is_admin(user) else "private"

    def validate_catalog_source_config(source_type: str, config: dict[str, Any]) -> tuple[dict[str, Any], str]:
        try:
            normalized = validate_source_config(source_type, config)
            return normalized, build_source_key(source_type, normalized)
        except SourceConfigError as exc:
            raise ApiError("invalid_source_config", str(exc), status_code=400) from exc

    def source_import_candidates(data: dict[str, Any]) -> list[dict[str, Any]]:
        sources = data.get("sources") or {}
        candidates: list[dict[str, Any]] = []

        def add(source_type: str, item: dict[str, Any], *, secret_env: str | None = None) -> None:
            config = catalog_config_for_source_type(source_type, item)
            try:
                normalized, key = validate_catalog_source_config(source_type, config)
                env_name = _validate_secret_env(secret_env or item.get("secret_env") or item.get("token_env"))
            except ApiError as exc:
                candidates.append(
                    {
                        "source_type": source_type,
                        "display_name": source_display_name(source_type, item),
                        "error": {"code": exc.code, "message": exc.message},
                    }
                )
                return
            candidates.append(
                {
                    "source_type": source_type,
                    "display_name": source_display_name(source_type, item),
                    "description": str(item.get("description") or ""),
                    "default_channel": source_default_channel(source_type, item),
                    "default_topics": source_topics(item),
                    "config": normalized,
                    "secret_env": env_name,
                    "enabled": bool(item.get("enabled", True)),
                    "source_key": key,
                }
            )

        for item in sources.get("rss") or []:
            if isinstance(item, dict):
                add("rss", item)

        for item in sources.get("github") or []:
            if not isinstance(item, dict):
                continue
            github_type = "github_user" if item.get("type") == "user_events" else "github_release"
            add(github_type, item)

        hackernews = sources.get("hackernews") or {}
        if isinstance(hackernews, dict) and hackernews.get("enabled"):
            add("hackernews", hackernews)

        reddit = sources.get("reddit") or {}
        if isinstance(reddit, dict):
            for item in reddit.get("subreddits") or []:
                if isinstance(item, dict):
                    add("reddit_subreddit", item)
            for item in reddit.get("users") or []:
                if isinstance(item, dict):
                    add("reddit_user", item)

        telegram = sources.get("telegram") or {}
        if isinstance(telegram, dict):
            for item in telegram.get("channels") or []:
                if isinstance(item, dict):
                    add("telegram_channel", item)

        apify = sources.get("apify_social") or {}
        if isinstance(apify, dict):
            default_secret = apify.get("token_env")
            for item in apify.get("subscriptions") or []:
                if isinstance(item, dict):
                    add("apify_social", item, secret_env=item.get("token_env") or default_secret)

        return candidates

    def import_config_sources(payload: ConfigImportSourcesRequest, user: dict[str, Any]) -> dict[str, Any]:
        base_data, _base_config = read_base_config()
        candidates = source_import_candidates(base_data)
        result: dict[str, Any] = {
            "dry_run": payload.dry_run,
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [],
            "candidates": candidates,
        }
        if payload.dry_run:
            result["skipped"] = len([item for item in candidates if item.get("error")])
            result["errors"] = [item["error"] for item in candidates if item.get("error")]
            return result

        for candidate in candidates:
            if candidate.get("error"):
                result["skipped"] += 1
                result["errors"].append(candidate["error"])
                continue
            existing = store.get_source_by_key(
                workspace_id=user["workspace_id"],
                source_key=candidate["source_key"],
            )
            if existing:
                source = store.update_source(
                    existing["id"],
                    display_name=candidate["display_name"],
                    description=candidate["description"],
                    default_channel=candidate["default_channel"],
                    default_topics=candidate["default_topics"],
                    config=candidate["config"],
                    source_key=candidate["source_key"],
                    secret_env=candidate["secret_env"],
                    enabled=candidate["enabled"],
                )
                result["updated"] += 1
            else:
                source_id = store.create_source(
                    workspace_id=user["workspace_id"],
                    scope="public",
                    owner_user_id=user["id"],
                    source_type=candidate["source_type"],
                    display_name=candidate["display_name"],
                    description=candidate["description"],
                    default_channel=candidate["default_channel"],
                    default_topics=candidate["default_topics"],
                    config=candidate["config"],
                    source_key=candidate["source_key"],
                    secret_env=candidate["secret_env"],
                    enabled=candidate["enabled"],
                )
                source = store.get_source(source_id)
                result["created"] += 1
            if payload.subscribe_current_user and source:
                store.create_subscription(user_id=user["id"], source_id=source["id"], enabled=True)
        return result

    def apply_service_source_upsert(
        action: str,
        payload: dict[str, Any],
        user: dict[str, Any],
    ) -> dict[str, Any]:
        if user.get("role") == "viewer":
            raise ApiError("forbidden", "viewer cannot create or update sources", status_code=403)
        base_data, _base_config = read_base_config()
        working_data = build_config_data_for_user(base_data, user)
        updated_working = apply_config_action(working_data, action, payload)
        item = source_item_for_upsert(updated_working, action, payload)
        base_data["tags"] = updated_working.get("tags", base_data.get("tags", []))
        base_data["personal_tags"] = updated_working.get(
            "personal_tags",
            base_data.get("personal_tags", []),
        )
        write_base_config(base_data)

        source_type = SOURCE_UPSERT_ACTIONS[action]
        source_id = str(payload.get("source_id") or "").strip() or None
        source = visible_source_or_404(source_id, user) if source_id else None
        channel = source_default_channel(source_type, item)
        topics = source_topics(item)
        personal_tags = source_personal_tags(item)
        analysis_mode = str(item.get("analysis_mode") or "full")
        enabled = bool(item.get("enabled", True))
        secret_env = source_secret_env(item)
        normalized_config, key = validate_catalog_source_config(
            source_type,
            catalog_config_for_source_type(source_type, item),
        )
        mutable_source = True
        if source:
            mutable_source = can_update_catalog_source(source, user)
            if not mutable_source and source["scope"] == "private":
                raise ApiError("forbidden", "cannot update another user's private source", status_code=403)
            if mutable_source:
                updated_source = store.update_source(
                    source["id"],
                    display_name=source_display_name(source_type, item),
                    default_channel=channel,
                    default_topics=topics,
                    config=normalized_config,
                    source_key=key,
                    secret_env=secret_env,
                    enabled=True,
                )
                source_id = updated_source["id"]
        else:
            source_id = store.create_source(
                workspace_id=user["workspace_id"],
                scope=default_source_scope(user),
                owner_user_id=user["id"],
                source_type=source_type,
                display_name=source_display_name(source_type, item),
                default_channel=channel,
                default_topics=topics,
                config=normalized_config,
                source_key=key,
                secret_env=secret_env,
                enabled=True,
            )

        subscription = store.create_subscription(
            user_id=user["id"],
            source_id=source_id,
            enabled=enabled,
            override_channel=None if mutable_source else channel,
            override_topics=[] if mutable_source else topics,
            personal_tags=personal_tags,
            analysis_mode=analysis_mode,
        )
        return subscription

    def apply_service_source_delete(payload: dict[str, Any], user: dict[str, Any]) -> None:
        source_id = str(payload.get("source_id") or "").strip()
        if not source_id:
            raise ApiError("source_id_required", "source_id is required for service source deletion", status_code=400)
        source = visible_source_or_404(source_id, user)
        if source["scope"] != "private" and not _is_admin(user):
            subscription_id = str(payload.get("subscription_id") or "").strip()
            if subscription_id:
                store.delete_subscription(subscription_id, user_id=user["id"])
                return
            for subscription in store.list_user_subscriptions(user["id"]):
                if subscription["source_id"] == source_id:
                    store.delete_subscription(subscription["id"], user_id=user["id"])
                    return
            return
        if source["scope"] == "private" and source["owner_user_id"] != user["id"]:
            raise ApiError("forbidden", "cannot delete another user's private source", status_code=403)
        store.update_source(source_id, enabled=False)

    def compatibility_job_payload(raw_payload: dict[str, Any]) -> JobCreateRequest:
        source_id = str(raw_payload.get("source_id") or "").strip() or None
        subscription_id = str(raw_payload.get("subscription_id") or "").strip() or None
        priority = int(raw_payload.get("priority") or 0)
        payload = {
            key: value
            for key, value in raw_payload.items()
            if key not in {"source_id", "subscription_id", "priority"}
        }
        return JobCreateRequest(
            source_id=source_id,
            subscription_id=subscription_id,
            payload=payload,
            priority=priority,
        )

    def queued_job_response(job: dict[str, Any], message: str) -> dict[str, Any]:
        return {**job, "message": message}

    def job_or_404(job_id: str, user: dict[str, Any]) -> dict[str, Any]:
        job = queue.get_job(job_id)
        if not job or job["workspace_id"] != user["workspace_id"]:
            raise ApiError("not_found", "job not found", status_code=404)
        if job["user_id"] != user["id"] and not _is_admin(user):
            raise ApiError("forbidden", "cannot access another user's job", status_code=403)
        return job

    def visible_item_or_404(article_id: str, user: dict[str, Any]) -> None:
        if not item_state.is_visible(
            workspace_id=user["workspace_id"],
            user_id=user["id"],
            article_id=article_id,
        ):
            raise ApiError("not_found", "item not found", status_code=404)

    def target_user_for_scope(requested_user_id: str | None, user: dict[str, Any]) -> dict[str, Any]:
        if not requested_user_id or requested_user_id == user["id"]:
            return user
        if not _is_admin(user):
            raise ApiError(
                "forbidden",
                "current user cannot inspect another user's feed or archive",
                status_code=403,
                action="Use your own user scope or ask an admin.",
            )
        target = store.get_user(requested_user_id)
        if not target or target["workspace_id"] != user["workspace_id"]:
            raise ApiError("not_found", "target user not found", status_code=404)
        return target

    def validate_archive_params(
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        sort: str = "published_at",
        order: str = "desc",
        group_by: str | None = None,
        bucket: str = "none",
    ) -> None:
        if sort not in {"published_at", "score", "source", "channel", "id"}:
            raise ApiError("invalid_sort", "sort must be published_at, score, source, channel, or id", status_code=400)
        if order not in {"asc", "desc"}:
            raise ApiError("invalid_order", "order must be asc or desc", status_code=400)
        if date_from and date_to and date_from > date_to:
            raise ApiError("invalid_date_range", "date_from must be before date_to", status_code=400)
        if group_by is not None and group_by not in {"channel", "topic", "entity", "source"}:
            raise ApiError("invalid_group_by", "group_by must be channel, topic, entity, or source", status_code=400)
        if bucket not in {"none", "day", "week"}:
            raise ApiError("invalid_bucket", "bucket must be none, day, or week", status_code=400)

    @app.get("/api/auth/status")
    async def auth_status(request: Request) -> dict[str, Any]:
        user = store.get_session_user(request.cookies.get(COOKIE_NAME))
        return ok(
            {
                "authenticated": bool(user),
                "user": _sanitize_user(user) if user else None,
            }
        )

    @app.post("/api/auth/login")
    async def auth_login(payload: LoginRequest, response: Response) -> dict[str, Any]:
        user = store.authenticate_user(payload.username, payload.password)
        if not user:
            raise ApiError("invalid_credentials", "username or password is incorrect", status_code=401)
        token = store.create_session(user["id"])
        response.set_cookie(
            COOKIE_NAME,
            token,
            httponly=True,
            samesite="lax",
            max_age=7 * 24 * 60 * 60,
        )
        return ok({"authenticated": True, "user": _sanitize_user(user)})

    @app.post("/api/auth/logout")
    async def auth_logout(request: Request, response: Response) -> dict[str, Any]:
        store.delete_session(request.cookies.get(COOKIE_NAME))
        response.delete_cookie(COOKIE_NAME)
        return ok({"authenticated": False, "user": None})

    @app.get("/api/config")
    async def config_get(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        return ok(config_response(user))

    @app.post("/api/config/action")
    async def config_action(
        request_payload: ConfigActionRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        action = request_payload.action
        payload = request_payload.payload
        if action in SOURCE_UPSERT_ACTIONS:
            apply_service_source_upsert(action, payload, user)
            return ok(config_response(user))
        if action in SOURCE_DELETE_ACTIONS:
            apply_service_source_delete(payload, user)
            return ok(config_response(user))

        base_data, _base_config = read_base_config()
        updated = apply_config_action(base_data, action, payload)
        write_base_config(updated)
        return ok(config_response(user))

    @app.get("/api/users")
    async def users_list(user: dict[str, Any] = Depends(current_admin)) -> dict[str, Any]:
        users = store.list_users(workspace_id=user["workspace_id"])
        return ok({"users": [_sanitize_user(item) for item in users]})

    @app.post("/api/users")
    async def users_create(
        payload: UserCreateRequest,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        if payload.role not in ROLES:
            raise ApiError("invalid_role", "role must be owner, admin, member, or viewer")
        created = store.create_user(
            workspace_id=user["workspace_id"],
            username=payload.username,
            password=payload.password,
            role=payload.role,
            display_name=payload.display_name,
            enabled=payload.enabled,
        )
        return ok(_sanitize_user(created))

    @app.patch("/api/users/{user_id}")
    async def users_patch(
        user_id: str,
        payload: UserPatchRequest,
        _admin: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        updated = store.update_user(
            user_id,
            role=payload.role,
            enabled=payload.enabled,
            display_name=payload.display_name,
        )
        return ok(_sanitize_user(updated))

    @app.get("/api/catalog/sources")
    async def catalog_sources(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        return ok({"sources": store.list_visible_sources(user)})

    @app.get("/api/catalog/source-types")
    async def catalog_source_types(_user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        return ok({"source_types": list_source_types()})

    @app.post("/api/catalog/import-config-sources")
    async def catalog_import_config_sources(
        payload: ConfigImportSourcesRequest,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        return ok(import_config_sources(payload, user))

    @app.post("/api/catalog/sources")
    async def catalog_create(
        payload: SourceCreateRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        scope = payload.scope or default_source_scope(user)
        if scope not in SOURCE_SCOPES:
            raise ApiError("invalid_scope", "scope must be public, workspace, or private")
        if scope != "private" and not _is_admin(user):
            raise ApiError("forbidden", "only admins can create public or workspace sources", status_code=403)
        normalized_config, key = validate_catalog_source_config(payload.type, payload.config)
        source_id = store.create_source(
            workspace_id=user["workspace_id"],
            scope=scope,
            owner_user_id=user["id"],
            source_type=payload.type,
            display_name=payload.display_name,
            description=payload.description,
            default_channel=payload.default_channel,
            default_topics=payload.default_topics,
            config=normalized_config,
            source_key=key,
            secret_env=_validate_secret_env(payload.secret_env),
            enabled=payload.enabled,
        )
        source = store.get_source(source_id)
        if source is None:
            raise ApiError("not_found", "created source not found", status_code=500)
        return ok(source)

    @app.patch("/api/catalog/sources/{source_id}")
    async def catalog_patch(
        source_id: str,
        payload: SourcePatchRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        source = visible_source_or_404(source_id, user)
        if source["scope"] != "private" and not _is_admin(user):
            raise ApiError("forbidden", "only admins can update shared sources", status_code=403)
        if source["scope"] == "private" and source["owner_user_id"] != user["id"]:
            raise ApiError("forbidden", "cannot update another user's private source", status_code=403)
        normalized_config = None
        key = None
        if payload.config is not None:
            normalized_config, key = validate_catalog_source_config(source["type"], payload.config)
        updated = store.update_source(
            source_id,
            display_name=payload.display_name,
            description=payload.description,
            default_channel=payload.default_channel,
            default_topics=payload.default_topics,
            config=normalized_config,
            source_key=key,
            secret_env=_validate_secret_env(payload.secret_env),
            enabled=payload.enabled,
        )
        return ok(updated)

    @app.delete("/api/catalog/sources/{source_id}")
    async def catalog_delete(
        source_id: str,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        source = visible_source_or_404(source_id, user)
        if source["scope"] != "private" and not _is_admin(user):
            raise ApiError("forbidden", "only admins can delete shared sources", status_code=403)
        if source["scope"] == "private" and source["owner_user_id"] != user["id"]:
            raise ApiError("forbidden", "cannot delete another user's private source", status_code=403)
        return ok(store.update_source(source_id, enabled=False))

    @app.post("/api/catalog/sources/{source_id}/subscribe")
    async def catalog_subscribe(
        source_id: str,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        visible_source_or_404(source_id, user)
        subscription = store.create_subscription(user_id=user["id"], source_id=source_id)
        return ok({"subscription": subscription})

    @app.delete("/api/catalog/sources/{source_id}/subscription")
    async def catalog_unsubscribe(
        source_id: str,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        visible_source_or_404(source_id, user)
        subscription = store.get_user_subscription_for_source(user["id"], source_id)
        if not subscription:
            raise ApiError("not_found", "subscription not found", status_code=404)
        return ok({"deleted": store.delete_subscription(subscription["id"], user_id=user["id"])})

    @app.get("/api/me/subscriptions")
    async def subscriptions_list(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        return ok({"subscriptions": store.list_user_subscriptions(user["id"])})

    @app.post("/api/me/subscriptions")
    async def subscriptions_create(
        payload: SubscriptionRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        visible_source_or_404(payload.source_id, user)
        subscription = store.create_subscription(
            user_id=user["id"],
            source_id=payload.source_id,
            enabled=payload.enabled,
            override_channel=payload.override_channel,
            override_topics=payload.override_topics,
            personal_tags=payload.personal_tags,
            analysis_mode=payload.analysis_mode,
            priority=payload.priority,
        )
        return ok(subscription)

    @app.patch("/api/me/subscriptions/{subscription_id}")
    async def subscriptions_patch(
        subscription_id: str,
        payload: SubscriptionPatchRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        current = store.get_subscription(subscription_id)
        if not current or current["user_id"] != user["id"]:
            raise ApiError("not_found", "subscription not found", status_code=404)
        updated = store.update_subscription(
            subscription_id,
            enabled=payload.enabled,
            override_channel=payload.override_channel,
            override_topics=payload.override_topics,
            personal_tags=payload.personal_tags,
            analysis_mode=payload.analysis_mode,
            priority=payload.priority,
        )
        return ok(updated)

    @app.delete("/api/me/subscriptions/{subscription_id}")
    async def subscriptions_delete(
        subscription_id: str,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        deleted = store.delete_subscription(subscription_id, user_id=user["id"])
        if not deleted:
            raise ApiError("not_found", "subscription not found", status_code=404)
        return ok({"deleted": True})

    @app.get("/api/me/item-state")
    async def me_item_state(
        article_ids: str = "",
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        ids = [part.strip() for part in str(article_ids or "").split(",") if part.strip()]
        return ok(
            {
                "states": item_state.get_states(
                    workspace_id=user["workspace_id"],
                    user_id=user["id"],
                    article_ids=ids,
                )
            }
        )

    @app.patch("/api/me/items/{article_id}/state")
    async def me_item_state_update(
        article_id: str,
        payload: ItemStatePatchRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        visible_item_or_404(article_id, user)
        return ok(
            item_state.update_state(
                workspace_id=user["workspace_id"],
                user_id=user["id"],
                article_id=article_id,
                is_read=payload.is_read,
                is_saved=payload.is_saved,
                is_later=payload.is_later,
                dismissed=payload.dismissed,
            )
        )

    @app.post("/api/me/items/{article_id}/feedback")
    async def me_item_feedback(
        article_id: str,
        payload: ItemFeedbackRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        visible_item_or_404(article_id, user)
        try:
            return ok(
                item_state.record_feedback(
                    workspace_id=user["workspace_id"],
                    user_id=user["id"],
                    article_id=article_id,
                    feedback_type=payload.feedback_type,
                    value=payload.value,
                    reason=payload.reason,
                    metadata=payload.metadata,
                )
            )
        except ValueError as exc:
            raise ApiError("invalid_feedback_type", str(exc), status_code=400) from exc

    def create_job(payload: JobCreateRequest, job_type: str, user: dict[str, Any]) -> dict[str, Any]:
        require_mutating_member(user)
        if payload.source_id:
            visible_source_or_404(payload.source_id, user)
        quota.ensure_job_allowed(workspace_id=user["workspace_id"], user_id=user["id"])
        job = queue.create_job(
            workspace_id=user["workspace_id"],
            user_id=user["id"],
            source_id=payload.source_id,
            subscription_id=payload.subscription_id,
            job_type=job_type,
            payload=payload.payload,
            priority=payload.priority,
            max_attempts=int(os.getenv("HORIZON_JOB_MAX_ATTEMPTS", "3")),
            retention_days=int(os.getenv("HORIZON_JOB_RETENTION_DAYS", "14")),
        )
        quota.record_job_usage(
            workspace_id=user["workspace_id"],
            user_id=user["id"],
            event_type=job_type,
        )
        return job

    @app.post("/api/jobs/source-test")
    async def jobs_source_test(
        payload: JobCreateRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        return ok(create_job(payload, "source_test", user))

    @app.post("/api/jobs/source-fetch")
    async def jobs_source_fetch(
        payload: JobCreateRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        return ok(create_job(payload, "source_fetch", user))

    @app.post("/api/jobs/user-feed-refresh")
    async def jobs_user_feed_refresh(
        payload: JobCreateRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        return ok(create_job(payload, "user_feed_refresh", user))

    @app.post("/api/source/test")
    async def source_test_compat(
        payload: dict[str, Any],
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        job = create_job(compatibility_job_payload(payload), "source_test", user)
        return ok(queued_job_response(job, "测试任务已排队，Worker 会异步执行。"))

    @app.post("/api/source/update")
    async def source_update_compat(
        payload: dict[str, Any],
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        job = create_job(compatibility_job_payload(payload), "source_fetch", user)
        return ok(queued_job_response(job, "更新任务已排队，Worker 会异步执行。"))

    @app.get("/api/jobs/{job_id}")
    async def jobs_get(job_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        return ok(job_or_404(job_id, user))

    @app.post("/api/jobs/{job_id}/cancel")
    async def jobs_cancel(job_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        require_mutating_member(user)
        job_or_404(job_id, user)
        try:
            return ok(queue.cancel_job(job_id, user_id=None if _is_admin(user) else user["id"]))
        except ValueError as exc:
            raise ApiError("job_not_cancelable", str(exc), status_code=409) from exc

    @app.post("/api/jobs/{job_id}/retry")
    async def jobs_retry(job_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        require_mutating_member(user)
        job_or_404(job_id, user)
        try:
            return ok(queue.retry_job(job_id, user_id=None if _is_admin(user) else user["id"]))
        except ValueError as exc:
            raise ApiError("job_not_retryable", str(exc), status_code=409) from exc

    @app.get("/api/jobs")
    async def jobs_list(
        status: str | None = None,
        limit: int = 50,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        return ok(
            {
                "jobs": queue.list_jobs(
                    workspace_id=user["workspace_id"],
                    user_id=None if _is_admin(user) else user["id"],
                    status=status,
                    limit=max(1, min(int(limit), 200)),
                )
            }
        )

    @app.get("/api/dashboard/summary")
    async def dashboard_summary(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        sources = store.list_visible_sources(user)
        subscriptions = store.list_user_subscriptions(user["id"])
        jobs = queue.list_jobs(
            workspace_id=user["workspace_id"],
            user_id=None if _is_admin(user) else user["id"],
        )
        latest = feed_archive.latest_feed(workspace_id=user["workspace_id"], user_id=user["id"])
        item_state_counts = item_state.count_flags(workspace_id=user["workspace_id"], user_id=user["id"])
        return ok(
            {
                "source_count": len(sources),
                "subscription_count": len(subscriptions),
                "queued_job_count": len([job for job in jobs if job["status"] == "queued"]),
                "running_job_count": len([job for job in jobs if job["status"] == "running"]),
                "failed_job_count": len([job for job in jobs if job["status"] == "failed"]),
                "latest_generated_at": latest.get("generated_at"),
                "item_state_counts": item_state_counts,
                "current_user": _sanitize_user(user),
            }
        )

    @app.get("/api/feed/latest")
    async def feed_latest(
        user_id: str | None = None,
        hide_dismissed: bool = False,
        unread_first: bool = False,
        saved_first: bool = False,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        target = target_user_for_scope(user_id, user)
        return ok(
            feed_archive.latest_feed(
                workspace_id=target["workspace_id"],
                user_id=target["id"],
                hide_dismissed=hide_dismissed,
                unread_first=unread_first,
                saved_first=saved_first,
            )
        )

    @app.get("/api/feed/history")
    async def feed_history(
        user_id: str | None = None,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        target = target_user_for_scope(user_id, user)
        return ok(feed_archive.history_feed(workspace_id=target["workspace_id"], user_id=target["id"]))

    @app.get("/api/archive/graph")
    async def archive_graph(_user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        return ok(feed_archive.article_graph())

    @app.get("/api/archive/items")
    async def archive_items(
        user_id: str | None = None,
        channel: str | None = None,
        topic: str | None = None,
        source: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        min_score: float = 0.0,
        limit: int = 100,
        offset: int = 0,
        sort: str = "published_at",
        order: str = "desc",
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        validate_archive_params(date_from=date_from, date_to=date_to, sort=sort, order=order)
        target = target_user_for_scope(user_id, user)
        return ok(
            feed_archive.archive_items(
                user_id=target["id"],
                channel=channel,
                topic=topic,
                source=source,
                date_from=date_from,
                date_to=date_to,
                min_score=min_score,
                limit=max(1, min(int(limit), 200)),
                offset=max(int(offset), 0),
                sort=sort,
                order=order,
            )
        )

    @app.get("/api/archive/trends")
    async def archive_trends(
        user_id: str | None = None,
        group_by: str = "channel",
        bucket: str = "none",
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        validate_archive_params(group_by=group_by, bucket=bucket)
        target = target_user_for_scope(user_id, user)
        return ok({"trends": feed_archive.archive_trends(group_by=group_by, user_id=target["id"], bucket=bucket)})

    @app.get("/api/archive/facets")
    async def archive_facets(
        user_id: str | None = None,
        channel: str | None = None,
        topic: str | None = None,
        source: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        min_score: float = 0.0,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        validate_archive_params(date_from=date_from, date_to=date_to)
        target = target_user_for_scope(user_id, user)
        return ok(
            feed_archive.archive_facets(
                user_id=target["id"],
                channel=channel,
                topic=topic,
                source=source,
                date_from=date_from,
                date_to=date_to,
                min_score=min_score,
            )
        )

    @app.get("/api/archive/source-quality")
    async def archive_source_quality(
        user_id: str | None = None,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        target = target_user_for_scope(user_id, user)
        return ok({"sources": feed_archive.source_quality(user_id=target["id"])})

    @app.api_route("/api/{_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def api_not_found(_path: str) -> dict[str, Any]:
        raise ApiError("not_found", "API endpoint not found", status_code=404)

    if static_path.exists():
        app.mount("/", StaticFiles(directory=str(static_path), html=True), name="static")

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve InfoHub Light service API")
    parser.add_argument("--host", default=os.getenv("HORIZON_WEB_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("HORIZON_WEB_PORT", "8080")))
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()

    load_dotenv()
    app = create_app(data_dir=args.data_dir)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
