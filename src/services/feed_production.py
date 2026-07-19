"""Build and persist service-owned schema-v2 user feed snapshots."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from ..models import Config
from ..storage.service_store import ServiceStore
from ..ui.site import build_site_payload, normalize_feed_payload
from .feed_run import FeedRunResult, safe_issue, safe_run_diagnostics
from .canonical_content import merge_feed_items
from .user_feed_store import UserFeedSnapshotInput, UserFeedStore
from .user_content_store import UserContentStore


class FeedRunFailed(RuntimeError):
    """A structured feed run failed before a snapshot could be finalized."""

    def __init__(self, result: FeedRunResult):
        message = "; ".join(
            str((safe_issue(issue) or {}).get("message") or "")
            for issue in result.issues
        ) or "feed run failed"
        super().__init__(message)
        self.result = result
        self.retryable = any(issue.retryable for issue in result.issues)


def active_service_source_ids(config: Config) -> set[str]:
    """Return catalog source IDs enabled in a user-scoped Config."""
    candidates: list[Any] = [
        *config.sources.github,
        config.sources.hackernews,
        *config.sources.rss,
        *config.sources.reddit.subreddits,
        *config.sources.reddit.users,
        *config.sources.telegram.channels,
        *config.sources.apify_social.subscriptions,
    ]
    return {
        str(source.source_id)
        for source in candidates
        if getattr(source, "enabled", True) and getattr(source, "source_id", None)
    }


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _within_window(item: dict[str, Any], cutoff: datetime) -> bool:
    timestamp = _parse_time(item.get("published_at")) or _parse_time(item.get("fetched_at"))
    return timestamp is None or timestamp >= cutoff


def _sorted_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    oldest = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(
        items,
        key=lambda item: (
            float(item.get("score") or 0),
            int(item.get("source_priority") or 0),
            _parse_time(item.get("published_at"))
            or _parse_time(item.get("fetched_at"))
            or oldest,
            str(item.get("id") or ""),
        ),
        reverse=True,
    )


def _item_source_ids(item: dict[str, Any]) -> set[str]:
    values = item.get("source_ids")
    source_ids = {
        str(value)
        for value in values
        if value
    } if isinstance(values, list) else set()
    if item.get("source_id"):
        source_ids.add(str(item["source_id"]))
    return source_ids


def _is_latest_per_source(item: dict[str, Any]) -> bool:
    return str(item.get("retention_policy") or "") == "latest_per_source"


def _normalize_legacy_social_retention(item: dict[str, Any]) -> dict[str, Any]:
    """Treat derived legacy social-profile retention as the rolling window."""

    normalized = dict(item)
    if (
        _is_latest_per_source(normalized)
        and not bool(normalized.get("retention_policy_explicit"))
        and str(normalized.get("source_type") or "").lower()
        in {"twitter", "instagram"}
    ):
        normalized["retention_policy"] = "time_window"
    return normalized


def _current_item_allowed(item: dict[str, Any], cutoff: datetime) -> bool:
    """Apply the rolling cutoff to social posts without hiding fetched articles."""

    if _is_latest_per_source(item):
        return True
    if str(item.get("source_type") or "").lower() in {"twitter", "instagram"}:
        return _within_window(item, cutoff)
    return True


def _item_provenance_keys(item: dict[str, Any]) -> set[str]:
    subscription_ids = {
        str(value)
        for value in [
            *(item.get("subscription_ids") or []),
            item.get("subscription_id"),
        ]
        if value
    }
    if subscription_ids:
        return {f"subscription:{value}" for value in subscription_ids}
    return {f"source:{value}" for value in _item_source_ids(item)}


def _without_replaced_latest(
    previous_items: list[dict[str, Any]],
    current_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    current_keys: set[str] = set()
    for item in current_items:
        if _is_latest_per_source(item):
            current_keys.update(_item_provenance_keys(item))
    if not current_keys:
        return previous_items
    return [
        item
        for item in previous_items
        if not (
            _is_latest_per_source(item)
            and bool(_item_provenance_keys(item) & current_keys)
        )
    ]


def _merge_failed_provenance(
    current: dict[str, Any],
    previous: dict[str, Any],
    failed_source_ids: set[str],
) -> None:
    """Keep failed-source ownership when a successful duplicate replaces an old item."""
    previous_failed_sources = _item_source_ids(previous) & failed_source_ids
    if not previous_failed_sources:
        return

    current_sources = list(current.get("source_ids") or [])
    if current.get("source_id"):
        current_sources.append(current["source_id"])
    current["source_ids"] = list(dict.fromkeys(
        str(value)
        for value in [*current_sources, *sorted(previous_failed_sources)]
        if value
    ))
    for key in ("subscription_ids", "source_keys"):
        current_values = current.get(key) if isinstance(current.get(key), list) else []
        previous_values = previous.get(key) if isinstance(previous.get(key), list) else []
        current[key] = list(dict.fromkeys(
            str(value)
            for value in [*current_values, *previous_values]
            if value
        ))


class FeedProductionService:
    """Turn one structured run into a user-scoped snapshot."""

    def __init__(self, store: ServiceStore, config: Config):
        self.store = store
        self.config = config
        self.feed_store = UserFeedStore(store)

    def save_run_result(
        self,
        *,
        workspace_id: str,
        user_id: str,
        job_id: str,
        job_type: str,
        result: FeedRunResult,
        source_id: str | None = None,
        active_source_ids: set[str] | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        conn = self.store.connect()
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        try:
            snapshot = self._save_run_result_locked(
                workspace_id=workspace_id,
                user_id=user_id,
                job_id=job_id,
                job_type=job_type,
                result=result,
                source_id=source_id,
                active_source_ids=active_source_ids,
                commit=False,
            )
            if commit:
                conn.commit()
            return snapshot
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise

    def _save_run_result_locked(
        self,
        *,
        workspace_id: str,
        user_id: str,
        job_id: str,
        job_type: str,
        result: FeedRunResult,
        source_id: str | None = None,
        active_source_ids: set[str] | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        if result.status == "failed":
            raise ValueError("failed run cannot create a feed snapshot")
        current = build_site_payload(
            all_items=list(result.items),
            date=str(result.finished_at)[:10],
            total_fetched=sum(outcome.fetched_count for outcome in result.source_outcomes),
            featured_threshold=self.config.filtering.featured_score_threshold,
            daily_push_threshold=self.config.filtering.daily_push_score_threshold,
            daily_push_limit=self.config.filtering.daily_push_limit,
            homepage_min_score=self.config.filtering.homepage_min_score,
            recent_item_limit=self.config.filtering.recent_item_limit,
            tag_library=self.config.tags,
            personal_tag_library=self.config.personal_tags,
            ai_enabled=bool(self.config.ai.enabled),
        )
        source_priorities = {
            item.id: int(item.metadata.get("source_priority") or 0)
            for item in result.items
        }
        for item in current.get("items", []):
            item["source_priority"] = source_priorities.get(str(item.get("id") or ""), 0)
        previous_snapshot = self.feed_store.latest_snapshot(
            workspace_id=workspace_id,
            user_id=user_id,
        )
        previous_items = []
        if previous_snapshot:
            previous_items = list(previous_snapshot["payload"].get("items") or [])
        cutoff = datetime.now(timezone.utc) - timedelta(
            hours=max(int(self.config.filtering.time_window_hours), 1)
        )
        if job_type == "user_feed_refresh":
            indexed_items = UserContentStore(self.store).recent_feed_items(
                workspace_id=workspace_id,
                user_id=user_id,
                seen_after=cutoff.isoformat(),
                active_source_ids=active_source_ids,
            )
            previous_items = merge_feed_items(
                previous_items=indexed_items,
                current_items=previous_items,
                include_previous=True,
                identity_items=previous_items,
            )
        normalized_previous_items = []
        for item in previous_items:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            normalized = _normalize_legacy_social_retention(item)
            if not (
                _within_window(normalized, cutoff)
                or _is_latest_per_source(normalized)
            ):
                continue
            normalized_previous_items.append(
                {
                    **normalized,
                    "source_priority": int(normalized.get("source_priority") or 0),
                }
            )
        previous_items = normalized_previous_items
        current_items = [
            item
            for item in current.get("items", [])
            if item.get("id") and _current_item_allowed(item, cutoff)
        ]

        if job_type == "source_fetch":
            for item in current_items:
                if source_id and not item.get("source_id"):
                    item["source_id"] = source_id
            previous_items = _without_replaced_latest(previous_items, current_items)
            merged_items = merge_feed_items(
                previous_items=previous_items,
                current_items=current_items,
                include_previous=True,
            )
        elif job_type == "user_feed_refresh":
            active = (
                None
                if active_source_ids is None
                else set(active_source_ids)
            )
            failed = {
                outcome.source_id
                for outcome in result.source_outcomes
                if outcome.status == "failed" and outcome.source_id
            }
            retained_items = []
            current_latest_keys = {
                key
                for item in current_items
                if _is_latest_per_source(item)
                for key in _item_provenance_keys(item)
            }
            for item in previous_items:
                provenance = _item_source_ids(item)
                if active is not None and not provenance & active:
                    continue
                if (
                    _is_latest_per_source(item)
                    and _item_provenance_keys(item) & current_latest_keys
                ):
                    continue
                retained_items.append(item)
            accepted_current = []
            for item in current_items:
                provenance = _item_source_ids(item)
                if active is None or provenance & active:
                    retained = next(
                        (
                            previous
                            for previous in retained_items
                            if str(previous.get("id")) == str(item.get("id"))
                        ),
                        None,
                    )
                    if retained is not None:
                        _merge_failed_provenance(item, retained, failed)
                    accepted_current.append(item)
            merged_items = merge_feed_items(
                previous_items=retained_items,
                current_items=accepted_current,
                include_previous=True,
                identity_items=previous_items,
            )
        else:
            raise ValueError(f"unsupported feed job type: {job_type}")

        items = _sorted_items(merged_items)
        payload = normalize_feed_payload({**current, "items": items})
        payload.update(
            {
                "schema_version": 2,
                "run_id": result.run_id,
                "run_status": result.status,
                "generated_at": result.finished_at,
                "items": items,
                "today_items": list(items),
                "today_total_items": len(items),
                "item_count": len(items),
                "scope": "user",
                **safe_run_diagnostics(result, item_count=len(items)),
            }
        )
        snapshot_input = UserFeedSnapshotInput(
            run_id=result.run_id,
            run_status=result.status,
            generated_at=result.finished_at,
            items=tuple(items),
            extra=payload,
        )
        snapshot = self.feed_store.save_run_snapshot(
            workspace_id=workspace_id,
            user_id=user_id,
            job_id=job_id,
            snapshot=snapshot_input,
            commit=commit,
        )
        UserContentStore(self.store).upsert_captured_items(
            workspace_id=workspace_id,
            user_id=user_id,
            items=list(result.items),
        )
        return snapshot
