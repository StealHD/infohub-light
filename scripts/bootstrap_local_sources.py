#!/usr/bin/env python3
"""Configure local AI keys and the four production-oriented owner subscriptions."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from src.services.secret_store import SecretStore
from src.services.feed_schedule import FeedScheduleService
from src.services.source_schedule import SourceScheduleService
from src.services.source_type_registry import source_key, validate_source_config
from src.storage.service_store import ServiceStore
from src.ui.server import _read_json, _write_json, validate_config_data


SECRET_DEFINITIONS = (
    ("Gemini Primary", "ai", "gemini", "GOOGLE_API_KEY"),
    ("Apify Primary", "apify", "apify", "APIFY_TOKEN"),
    ("Apify Secondary", "apify", "apify", "APIFY_TOKEN_2"),
)

SOURCE_DEFINITIONS = (
    {
        "type": "rss",
        "display_name": "Apple Developer News",
        "scope": "workspace",
        "default_channel": "工作/项目",
        "default_topics": ["行业动态"],
        "priority": 80,
        "config": {
            "name": "Apple Developer News",
            "url": "https://developer.apple.com/news/rss/news.rss",
        },
    },
    {
        "type": "rss",
        "display_name": "OpenAI News",
        "scope": "workspace",
        "default_channel": "AI",
        "default_topics": ["模型发布", "行业动态"],
        "priority": 80,
        "config": {
            "name": "OpenAI News",
            "url": "https://openai.com/news/rss.xml",
        },
    },
    {
        "type": "github_release",
        "display_name": "Claude Code Releases",
        "scope": "workspace",
        "default_channel": "AI",
        "default_topics": ["AI 编程", "行业动态"],
        "priority": 80,
        "config": {"owner": "anthropics", "repo": "claude-code", "type": "repo_releases"},
    },
    {
        "type": "apify_social",
        "display_name": "X · @thsottiaux",
        "scope": "private",
        "default_channel": "朋友动态",
        "default_topics": ["行业动态"],
        "priority": 50,
        "secret_env": "APIFY_TOKEN_2",
        "config": {
            "platform": "x",
            "kind": "profile",
            "target": "thsottiaux",
            "fetch_limit": 1,
            "analysis_mode": "full",
        },
    },
)


def _owner(store: ServiceStore) -> dict[str, Any]:
    workspace = store.get_default_workspace()
    owner = next(
        (
            user
            for user in store.list_users(workspace_id=workspace["id"])
            if user["role"] == "owner" and user["enabled"]
        ),
        None,
    )
    if owner is None:
        raise RuntimeError("an enabled owner user is required")
    return owner


def bootstrap_local_sources(
    data_dir: Path | str,
    secret_values: dict[str, str],
) -> dict[str, Any]:
    data_path = Path(data_dir)
    missing = [env_name for *_metadata, env_name in SECRET_DEFINITIONS if not secret_values.get(env_name)]
    if missing:
        raise ValueError("missing required local secret values: " + ", ".join(missing))

    secret_store = SecretStore(data_path)
    for *_metadata, env_name in SECRET_DEFINITIONS:
        secret_store.validate_value(secret_values[env_name])

    config_path = data_path / "config.json"
    config_data = _read_json(config_path)
    ai = config_data.setdefault("ai", {})
    ai.update(
        {
            "enabled": True,
            "provider": "gemini",
            "model": "gemini-3.5-flash",
            "base_url": None,
            "api_key_env": "GOOGLE_API_KEY",
            "languages": ["zh"],
            "summary_max_chars": 200,
            "analysis_max_output_tokens": 800,
            "analysis_content_chars": 1000,
            "analysis_comments_chars": 1500,
            # Stay within the common Gemini Flash request-per-minute limit
            # while processing a feed sequentially.
            "throttle_sec": 6.5,
        }
    )
    if ai.get("base_url") is None:
        ai.pop("base_url", None)
    validate_config_data(config_data)
    _write_json(config_path, config_data)

    store = ServiceStore(data_path)
    store.initialize()
    try:
        workspace = store.get_default_workspace()
        owner = _owner(store)
        for name, kind, provider, env_name in SECRET_DEFINITIONS:
            secret_store.set(env_name, secret_values[env_name])
            existing = store.get_secret_ref_by_env(
                workspace_id=workspace["id"],
                env_name=env_name,
            )
            if existing is None:
                store.create_secret_ref(
                    workspace_id=workspace["id"],
                    owner_user_id=owner["id"],
                    name=name,
                    env_name=env_name,
                    kind=kind,
                    provider=provider,
                    scope="workspace",
                )

        source_ids: list[str] = []
        x_subscription_id: str | None = None
        for definition in SOURCE_DEFINITIONS:
            normalized = validate_source_config(definition["type"], definition["config"])
            source = store.upsert_source(
                workspace_id=workspace["id"],
                scope=definition["scope"],
                owner_user_id=owner["id"],
                source_type=definition["type"],
                display_name=definition["display_name"],
                description="",
                default_channel=definition["default_channel"],
                default_topics=definition["default_topics"],
                config=normalized,
                source_key=source_key(definition["type"], normalized),
                secret_env=definition.get("secret_env"),
                enabled=True,
            )
            source_ids.append(source["id"])
            subscription = store.create_subscription(
                user_id=owner["id"],
                source_id=source["id"],
                enabled=True,
                analysis_mode="full",
                priority=int(definition["priority"]),
            )
            if definition["type"] == "apify_social":
                x_subscription_id = subscription["id"]
        FeedScheduleService(store).update_user_schedule(
            workspace_id=workspace["id"],
            user_id=owner["id"],
            enabled=True,
            interval_minutes=360,
        )
        if x_subscription_id is None:
            raise RuntimeError("X subscription was not created")
        SourceScheduleService(store).update_subscription_schedule(
            workspace_id=workspace["id"],
            user_id=owner["id"],
            subscription_id=x_subscription_id,
            enabled=True,
            interval_minutes=30,
        )
        secret_store.load_into_environ()
        return {
            "owner_id": owner["id"],
            "source_count": len(source_ids),
            "subscription_count": len(source_ids),
            "source_ids": source_ids,
            "secret_names": [name for name, *_rest in SECRET_DEFINITIONS],
        }
    finally:
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()
    values = {env_name: os.getenv(env_name, "") for *_metadata, env_name in SECRET_DEFINITIONS}
    result = bootstrap_local_sources(args.data_dir, values)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
