"""Validate real source adapters against Presentation v1 without AI or DB writes."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.models import Config
from src.orchestrator import HorizonOrchestrator
from src.services.secret_store import SecretStore
from src.storage.manager import StorageManager
from src.services.feed_payload import serialize_feed_item


REQUIRED_SOURCE_IDS = {
    "smoke-rss",
    "smoke-github-release",
    "smoke-github-user",
    "smoke-hackernews",
    "smoke-telegram",
}
OPTIONAL_DEGRADED_SOURCE_IDS = {"smoke-reddit-subreddit", "smoke-reddit-user"}


def _identity(source_id: str, catalog_type: str, name: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_key": f"smoke:{catalog_type}:{source_id}",
        "source_display_name": name,
        "catalog_source_type": catalog_type,
        "analysis_mode": "full",
        "source_priority": 0,
    }


def build_smoke_config(*, include_apify: bool) -> Config:
    """Build the eight catalog adapters with AI explicitly disabled."""
    subscriptions: list[dict[str, Any]] = []
    if include_apify:
        subscriptions.append(
            {
                "platform": "x",
                "kind": "profile",
                "target": "thsottiaux",
                "fetch_limit": 1,
                **_identity("smoke-apify-x", "apify_social", "X · @thsottiaux"),
            }
        )
    return Config.model_validate(
        {
            "version": "1.0",
            "ai": {
                "enabled": False,
                "provider": "gemini",
                "model": "gemini-3.5-flash",
                "api_key_env": "GOOGLE_API_KEY",
            },
            "sources": {
                "rss": [
                    {
                        "name": "GitHub Blog",
                        "url": "https://github.blog/feed/",
                        **_identity("smoke-rss", "rss", "GitHub Blog"),
                    }
                ],
                "github": [
                    {
                        "type": "repo_releases",
                        "owner": "openai",
                        "repo": "codex",
                        **_identity("smoke-github-release", "github_release", "OpenAI Codex Releases"),
                    },
                    {
                        "type": "user_events",
                        "username": "torvalds",
                        **_identity("smoke-github-user", "github_user", "torvalds activity"),
                    },
                ],
                "hackernews": {
                    "enabled": True,
                    "fetch_top_stories": 5,
                    "min_score": 0,
                    **_identity("smoke-hackernews", "hackernews", "Hacker News"),
                },
                "reddit": {
                    "enabled": True,
                    "fetch_comments": 1,
                    "subreddits": [
                        {
                            "subreddit": "LocalLLaMA",
                            "sort": "hot",
                            "fetch_limit": 1,
                            "min_score": 0,
                            **_identity("smoke-reddit-subreddit", "reddit_subreddit", "r/LocalLLaMA"),
                        }
                    ],
                    "users": [
                        {
                            "username": "spez",
                            "sort": "new",
                            "fetch_limit": 1,
                            **_identity("smoke-reddit-user", "reddit_user", "u/spez"),
                        }
                    ],
                },
                "telegram": {
                    "enabled": True,
                    "channels": [
                        {
                            "channel": "durov",
                            "fetch_limit": 1,
                            **_identity("smoke-telegram", "telegram_channel", "Telegram · durov"),
                        }
                    ],
                },
                "apify_social": {
                    "enabled": bool(subscriptions),
                    "token_env": "APIFY_TOKEN",
                    "token_envs": ["APIFY_TOKEN", "APIFY_TOKEN_2"],
                    "subscriptions": subscriptions,
                },
                "ossinsight": {"enabled": False},
            },
            "filtering": {"time_window_hours": 8760},
        }
    )


def validate_serialized_item(item: dict[str, Any]) -> list[str]:
    """Return field paths only; never include source content in the report."""
    errors: list[str] = []
    presentation = item.get("presentation")
    if not isinstance(presentation, dict):
        return ["presentation.missing"]
    if presentation.get("version") != 1:
        errors.append("presentation.version")
    required_sections = {
        "source": ("catalog_type", "platform", "name"),
        "author": ("name", "kind"),
        "timing": ("published_at", "fetched_at"),
        "links": ("canonical_url", "source_url"),
        "content": ("title", "title_origin", "excerpt", "content_kind", "excerpt_truncated"),
        "taxonomy": ("channel", "configured_topics", "inferred_topics", "topics", "entities"),
        "engagement": ("native_score", "likes", "comments", "reposts", "shares", "upvote_ratio"),
        "analysis": ("status", "score", "signal_strength", "signal_type", "summary_zh", "action_suggestion"),
    }
    for section, keys in required_sections.items():
        value = presentation.get(section)
        if not isinstance(value, dict):
            errors.append(f"presentation.{section}.missing")
            continue
        for key in keys:
            if key not in value:
                errors.append(f"presentation.{section}.{key}")
    content = presentation.get("content") or {}
    if len(str(content.get("excerpt") or "")) > 600:
        errors.append("presentation.content.excerpt_too_long")
    analysis = presentation.get("analysis") or {}
    if "reason" in analysis:
        errors.append("presentation.analysis.reason_forbidden")
    if len(str(analysis.get("summary_zh") or "")) > 200:
        errors.append("presentation.analysis.summary_zh_too_long")
    if len(str(analysis.get("action_suggestion") or "")) > 80:
        errors.append("presentation.analysis.action_suggestion_too_long")
    if "content" in item:
        errors.append("item.raw_content_forbidden")
    return errors


def _expected_source_ids(include_apify: bool) -> list[str]:
    ids = [
        "smoke-rss",
        "smoke-github-release",
        "smoke-github-user",
        "smoke-hackernews",
        "smoke-reddit-subreddit",
        "smoke-reddit-user",
        "smoke-telegram",
    ]
    if include_apify:
        ids.append("smoke-apify-x")
    return ids


def run_smoke(*, data_dir: str, hours: int) -> dict[str, Any]:
    SecretStore(data_dir).load_into_environ()
    include_apify = bool(os.getenv("APIFY_TOKEN") or os.getenv("APIFY_TOKEN_2"))
    config = build_smoke_config(include_apify=include_apify)
    result = asyncio.run(
        HorizonOrchestrator(config, StorageManager(data_dir=data_dir)).execute(
            force_hours=hours,
            enrich=False,
        )
    )
    serialized = [
        serialize_feed_item(item, featured_threshold=config.filtering.featured_score_threshold)
        for item in result.items
    ]
    item_errors: dict[str, list[list[str]]] = {}
    item_counts: dict[str, int] = {}
    for item, payload in zip(result.items, serialized):
        source_id = str(item.metadata.get("source_id") or "unknown")
        item_counts[source_id] = item_counts.get(source_id, 0) + 1
        errors = validate_serialized_item(payload)
        if errors:
            item_errors.setdefault(source_id, []).append(errors)
    outcomes = {outcome.source_id: outcome for outcome in result.source_outcomes}
    sources = []
    required_failed: list[str] = []
    optional_degraded: list[str] = []
    for source_id in _expected_source_ids(include_apify):
        outcome = outcomes.get(source_id)
        count = item_counts.get(source_id, 0)
        errors = item_errors.get(source_id, [])
        if outcome is None:
            status = "missing_outcome"
            code = "missing_outcome"
        elif outcome.status == "failed":
            status = "failed"
            code = outcome.issue.code if outcome.issue else "source_failed"
        elif count == 0:
            status = "empty"
            code = "no_parseable_item"
        elif errors:
            status = "invalid"
            code = "presentation_contract_failed"
        else:
            status = "valid"
            code = None
        row = {
            "source_id": source_id,
            "status": status,
            "item_count": count,
            "error_code": code,
            "field_errors": errors,
        }
        sources.append(row)
        if status != "valid":
            if source_id in OPTIONAL_DEGRADED_SOURCE_IDS:
                optional_degraded.append(source_id)
            else:
                required_failed.append(source_id)
    if not include_apify:
        sources.append({
            "source_id": "smoke-apify-x",
            "status": "skipped",
            "item_count": 0,
            "error_code": "apify_key_not_configured",
            "field_errors": [],
        })
    return {
        "ok": not required_failed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ai_calls": 0,
        "required_failed": required_failed,
        "optional_degraded": optional_degraded,
        "sources": sources,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--hours", type=int, default=8760)
    parser.add_argument("--output")
    args = parser.parse_args()
    report = run_smoke(data_dir=args.data_dir, hours=max(args.hours, 1))
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
