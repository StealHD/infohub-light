import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from src.models import Config, ContentItem, SourceType
from src.orchestrator import HorizonOrchestrator
from src.services.feed_production import FeedProductionService
from src.services.feed_run import FeedRunResult, RunIssue, SourceOutcome
from src.services.job_queue import JobQueue
from src.services.user_feed_store import UserFeedStore
from src.storage.manager import StorageManager
from src.storage.service_store import ServiceStore
from src.ui.site import build_site_payload


def _config() -> Config:
    return Config.model_validate(
        {
            "version": "1.0",
            "ai": {
                "enabled": False,
                "provider": "openai",
                "model": "gpt-4o-mini",
                "api_key_env": "OPENAI_API_KEY",
            },
            "sources": {"hackernews": {"enabled": False}},
            "filtering": {"time_window_hours": 24},
        }
    )


def _item(
    item_id: str,
    source_id: str,
    subscription_id: str,
    *,
    source_priority: int = 0,
    score: float | None = None,
    published_at: datetime | None = None,
) -> ContentItem:
    item = ContentItem(
        id=item_id,
        source_type=SourceType.RSS,
        title=item_id,
        url=f"https://example.com/{item_id}",
        content=item_id,
        published_at=published_at or datetime.now(timezone.utc),
        metadata={
            "feed_name": source_id,
            "source_id": source_id,
            "subscription_id": subscription_id,
            "source_key": f"rss:https://example.com/{source_id}.xml",
            "analysis_mode": "full",
            "source_priority": source_priority,
            "channel": "AI",
            "topics": ["Codex"],
        },
    )
    item.ai_score = score
    return item


def _outcome(source_id: str, subscription_id: str, *, failed: bool = False) -> SourceOutcome:
    issue = RunIssue("fetch", "TimeoutError", "timed out", True) if failed else None
    return SourceOutcome(
        source_id=source_id,
        subscription_id=subscription_id,
        source_key=f"rss:https://example.com/{source_id}.xml",
        analysis_mode="full",
        status="failed" if failed else "succeeded",
        fetched_count=0 if failed else 1,
        issue=issue,
    )


def _profile_item(
    item_id: str,
    source_id: str,
    subscription_id: str,
    *,
    source_type: SourceType = SourceType.INSTAGRAM,
    published_at: datetime | None = None,
) -> ContentItem:
    item = _item(
        item_id,
        source_id,
        subscription_id,
        published_at=published_at,
    )
    item.source_type = source_type
    item.metadata.update(
        {
            "catalog_source_type": "apify_social",
            "apify_platform": "x" if source_type == SourceType.TWITTER else "instagram",
            "apify_kind": "profile",
        }
    )
    return item


def _result(
    run_id: str,
    status: str,
    items: tuple[ContentItem, ...],
    outcomes: tuple[SourceOutcome, ...],
) -> FeedRunResult:
    return FeedRunResult(
        run_id=run_id,
        status=status,
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=datetime.now(timezone.utc).isoformat(),
        items=items,
        source_outcomes=outcomes,
        issues=tuple(outcome.issue for outcome in outcomes if outcome.issue),
    )


def _service(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    return store, workspace, owner, FeedProductionService(store, _config())


def test_partial_refresh_retains_recent_items_from_successful_and_failed_sources(
    tmp_path, monkeypatch
):
    store, workspace, owner, service = _service(tmp_path, monkeypatch)
    first = _result(
        "run_first",
        "succeeded",
        (_item("a-old", "src_a", "sub_a"), _item("b-old", "src_b", "sub_b")),
        (_outcome("src_a", "sub_a"), _outcome("src_b", "sub_b")),
    )
    service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_first",
        job_type="user_feed_refresh",
        result=first,
        active_source_ids={"src_a", "src_b"},
    )
    partial = _result(
        "run_partial",
        "partial",
        (_item("a-new", "src_a", "sub_a"),),
        (_outcome("src_a", "sub_a"), _outcome("src_b", "sub_b", failed=True)),
    )

    snapshot = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_partial",
        job_type="user_feed_refresh",
        result=partial,
        active_source_ids={"src_a", "src_b"},
    )

    payload = snapshot["payload"]
    assert {item["id"] for item in payload["items"]} == {
        "a-old",
        "a-new",
        "b-old",
    }
    assert payload["today_items"] == payload["items"]
    assert payload["schema_version"] == 2
    assert payload["run_id"] == "run_partial"
    assert payload["run_status"] == "partial"
    rows = store.connect().execute(
        "SELECT article_id, source_id, subscription_id FROM user_feed_items WHERE snapshot_id = ?",
        (snapshot["id"],),
    ).fetchall()
    assert {(row["article_id"], row["source_id"], row["subscription_id"]) for row in rows} == {
        ("a-old", "src_a", "sub_a"),
        ("a-new", "src_a", "sub_a"),
        ("b-old", "src_b", "sub_b"),
    }


def test_new_item_count_compares_adjacent_deduplicated_snapshot_ids(
    tmp_path,
    monkeypatch,
):
    _store, workspace, owner, service = _service(tmp_path, monkeypatch)
    first_item = _item("stable-a", "src_a", "sub_a")
    first = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_new_count_first",
        job_type="user_feed_refresh",
        result=_result(
            "run_new_count_first",
            "succeeded",
            (first_item, first_item),
            (_outcome("src_a", "sub_a"),),
        ),
        active_source_ids={"src_a"},
    )

    assert first["item_count"] == 1
    assert first["new_item_count"] == 1

    metadata_update = _item("stable-a", "src_a", "sub_a")
    metadata_update.title = "same stable item with updated metadata"
    metadata_only = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_new_count_metadata",
        job_type="user_feed_refresh",
        result=_result(
            "run_new_count_metadata",
            "succeeded",
            (metadata_update,),
            (_outcome("src_a", "sub_a"),),
        ),
        active_source_ids={"src_a"},
    )

    assert metadata_only["new_item_count"] == 0

    partial = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_new_count_partial",
        job_type="user_feed_refresh",
        result=_result(
            "run_new_count_partial",
            "partial",
            (_item("stable-b", "src_a", "sub_a"),),
            (
                _outcome("src_a", "sub_a"),
                _outcome("src_failed", "sub_failed", failed=True),
            ),
        ),
        active_source_ids={"src_a", "src_failed"},
    )

    assert partial["new_item_count"] == 1
    assert {item["id"] for item in partial["payload"]["items"]} == {
        "stable-a",
        "stable-b",
    }

    replacement = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_new_count_replacement",
        job_type="user_feed_refresh",
        result=_result(
            "run_new_count_replacement",
            "succeeded",
            (_item("stable-c", "src_c", "sub_c"),),
            (_outcome("src_c", "sub_c"),),
        ),
        active_source_ids={"src_c"},
    )

    assert replacement["new_item_count"] == 1
    assert [item["id"] for item in replacement["payload"]["items"]] == ["stable-c"]


def test_profile_source_fetch_expires_item_beyond_global_window_when_empty(
    tmp_path, monkeypatch
):
    _store, workspace, owner, service = _service(tmp_path, monkeypatch)
    old = _profile_item(
        "instagram:post:old",
        "src_instagram",
        "sub_instagram",
        published_at=datetime.now(timezone.utc) - timedelta(days=30),
    )
    service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_profile_initial",
        job_type="source_fetch",
        source_id="src_instagram",
        result=_result(
            "run_profile_initial",
            "succeeded",
            (old,),
            (_outcome("src_instagram", "sub_instagram"),),
        ),
    )

    latest = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_profile_empty",
        job_type="source_fetch",
        source_id="src_instagram",
        result=_result(
            "run_profile_empty",
            "succeeded",
            (),
            (
                SourceOutcome(
                    source_id="src_instagram",
                    subscription_id="sub_instagram",
                    source_key="apify:instagram:profile",
                    analysis_mode="full",
                    status="succeeded",
                    fetched_count=0,
                ),
            ),
        ),
    )

    assert latest["payload"]["items"] == []


def test_profile_source_fetch_keeps_multiple_items_inside_global_window(
    tmp_path, monkeypatch
):
    _store, workspace, owner, service = _service(tmp_path, monkeypatch)
    service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_x_old",
        job_type="source_fetch",
        source_id="src_x",
        result=_result(
            "run_x_old",
            "succeeded",
            (_profile_item("twitter:tweet:old", "src_x", "sub_x", source_type=SourceType.TWITTER),),
            (_outcome("src_x", "sub_x"),),
        ),
    )
    replacement = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_x_new",
        job_type="source_fetch",
        source_id="src_x",
        result=_result(
            "run_x_new",
            "succeeded",
            (_profile_item("twitter:tweet:new", "src_x", "sub_x", source_type=SourceType.TWITTER),),
            (_outcome("src_x", "sub_x"),),
        ),
    )

    assert {item["id"] for item in replacement["payload"]["items"]} == {
        "twitter:tweet:old",
        "twitter:tweet:new",
    }
    assert {
        item["retention_policy"] for item in replacement["payload"]["items"]
    } == {"time_window"}


def test_full_refresh_expires_profile_and_normal_source_outside_window(
    tmp_path, monkeypatch
):
    _store, workspace, owner, service = _service(tmp_path, monkeypatch)
    old_time = datetime.now(timezone.utc) - timedelta(days=30)
    service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_mixed_initial",
        job_type="user_feed_refresh",
        result=_result(
            "run_mixed_initial",
            "succeeded",
            (
                _profile_item(
                    "instagram:post:latest",
                    "src_instagram",
                    "sub_instagram",
                    published_at=old_time,
                ),
                _item("rss:old", "src_rss", "sub_rss", published_at=old_time),
            ),
            (
                _outcome("src_instagram", "sub_instagram"),
                _outcome("src_rss", "sub_rss"),
            ),
        ),
        active_source_ids={"src_instagram", "src_rss"},
    )

    latest = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_mixed_empty",
        job_type="user_feed_refresh",
        result=_result(
            "run_mixed_empty",
            "succeeded",
            (),
            (
                SourceOutcome(
                    source_id="src_instagram",
                    subscription_id="sub_instagram",
                    source_key="apify:instagram:profile",
                    analysis_mode="full",
                    status="succeeded",
                    fetched_count=0,
                ),
                SourceOutcome(
                    source_id="src_rss",
                    subscription_id="sub_rss",
                    source_key="rss:old",
                    analysis_mode="full",
                    status="succeeded",
                    fetched_count=0,
                ),
            ),
        ),
        active_source_ids={"src_instagram", "src_rss"},
    )

    assert latest["payload"]["items"] == []


def test_explicit_latest_per_source_still_replaces_previous_item(
    tmp_path, monkeypatch
):
    _store, workspace, owner, service = _service(tmp_path, monkeypatch)
    old = _item("rss:latest:old", "src_rss", "sub_rss")
    old.metadata["retention_policy"] = "latest_per_source"
    new = _item("rss:latest:new", "src_rss", "sub_rss")
    new.metadata["retention_policy"] = "latest_per_source"

    service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_explicit_latest_old",
        job_type="source_fetch",
        source_id="src_rss",
        result=_result(
            "run_explicit_latest_old",
            "succeeded",
            (old,),
            (_outcome("src_rss", "sub_rss"),),
        ),
    )
    latest = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_explicit_latest_new",
        job_type="source_fetch",
        source_id="src_rss",
        result=_result(
            "run_explicit_latest_new",
            "succeeded",
            (new,),
            (_outcome("src_rss", "sub_rss"),),
        ),
    )

    assert [item["id"] for item in latest["payload"]["items"]] == [
        "rss:latest:new"
    ]


def test_explicit_social_latest_per_source_is_not_normalized_to_time_window(
    tmp_path, monkeypatch
):
    _store, workspace, owner, service = _service(tmp_path, monkeypatch)
    old = _profile_item("twitter:explicit:old", "src_x", "sub_x")
    old.metadata["retention_policy"] = "latest_per_source"
    new = _profile_item("twitter:explicit:new", "src_x", "sub_x")
    new.metadata["retention_policy"] = "latest_per_source"

    service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_explicit_social_old",
        job_type="source_fetch",
        source_id="src_x",
        result=_result(
            "run_explicit_social_old",
            "succeeded",
            (old,),
            (_outcome("src_x", "sub_x"),),
        ),
    )
    latest = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_explicit_social_new",
        job_type="source_fetch",
        source_id="src_x",
        result=_result(
            "run_explicit_social_new",
            "succeeded",
            (new,),
            (_outcome("src_x", "sub_x"),),
        ),
    )

    assert [item["id"] for item in latest["payload"]["items"]] == [
        "twitter:explicit:new"
    ]
    assert latest["payload"]["items"][0]["retention_policy_explicit"] is True


def test_full_refresh_with_explicitly_empty_active_sources_discards_current_items(
    tmp_path, monkeypatch
):
    _store, workspace, owner, service = _service(tmp_path, monkeypatch)
    result = _result(
        "run_invalidated_source",
        "succeeded",
        (_item("disabled-new", "src_disabled", "sub_disabled"),),
        (_outcome("src_disabled", "sub_disabled"),),
    )

    snapshot = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_invalidated_source",
        job_type="user_feed_refresh",
        result=result,
        active_source_ids=set(),
    )

    assert snapshot["payload"]["items"] == []


def test_partial_refresh_preserves_cross_source_duplicate_when_any_provenance_fails(
    tmp_path,
    monkeypatch,
):
    _store, workspace, owner, service = _service(tmp_path, monkeypatch)
    source_a = _item("a-shared", "src_a", "sub_a")
    source_b = _item("b-shared", "src_b", "sub_b")
    source_b.url = source_a.url
    merged = HorizonOrchestrator(
        _config(),
        StorageManager(data_dir=tmp_path),
    ).merge_cross_source_duplicates([source_a, source_b])

    assert len(merged) == 1
    assert set(merged[0].metadata["source_ids"]) == {"src_a", "src_b"}
    assert set(merged[0].metadata["subscription_ids"]) == {"sub_a", "sub_b"}

    service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_shared_initial",
        job_type="user_feed_refresh",
        result=_result(
            "run_shared_initial",
            "succeeded",
            tuple(merged),
            (_outcome("src_a", "sub_a"), _outcome("src_b", "sub_b")),
        ),
        active_source_ids={"src_a", "src_b"},
    )

    partial = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_shared_partial",
        job_type="user_feed_refresh",
        result=_result(
            "run_shared_partial",
            "partial",
            (),
            (
                SourceOutcome(
                    source_id="src_a",
                    subscription_id="sub_a",
                    source_key="rss:https://example.com/src_a.xml",
                    analysis_mode="full",
                    status="succeeded",
                    fetched_count=0,
                ),
                _outcome("src_b", "sub_b", failed=True),
            ),
        ),
        active_source_ids={"src_a", "src_b"},
    )

    assert [item["id"] for item in partial["payload"]["items"]] == ["a-shared"]
    assert set(partial["payload"]["items"][0]["source_ids"]) == {"src_a", "src_b"}


def test_cross_source_dedup_uses_max_priority_and_keeps_all_provenance(tmp_path):
    source_a = _item(
        "a-shared-priority",
        "src_a",
        "sub_a",
        source_priority=12,
    )
    source_b = _item(
        "b-shared-priority",
        "src_b",
        "sub_b",
        source_priority=91,
    )
    source_b.url = source_a.url

    merged = HorizonOrchestrator(
        _config(),
        StorageManager(data_dir=tmp_path),
    ).merge_cross_source_duplicates([source_a, source_b])

    assert len(merged) == 1
    assert merged[0].metadata["source_priority"] == 91
    assert set(merged[0].metadata["source_ids"]) == {"src_a", "src_b"}
    assert set(merged[0].metadata["subscription_ids"]) == {"sub_a", "sub_b"}
    assert set(merged[0].metadata["source_keys"]) == {
        "rss:https://example.com/src_a.xml",
        "rss:https://example.com/src_b.xml",
    }


def test_consecutive_partial_refreshes_keep_failed_cross_source_provenance(
    tmp_path,
    monkeypatch,
):
    _store, workspace, owner, service = _service(tmp_path, monkeypatch)
    source_a = _item("a-shared", "src_a", "sub_a")
    source_b = _item("b-shared", "src_b", "sub_b")
    source_b.url = source_a.url
    merged = HorizonOrchestrator(
        _config(),
        StorageManager(data_dir=tmp_path),
    ).merge_cross_source_duplicates([source_a, source_b])
    service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_consecutive_initial",
        job_type="user_feed_refresh",
        result=_result(
            "run_consecutive_initial",
            "succeeded",
            tuple(merged),
            (_outcome("src_a", "sub_a"), _outcome("src_b", "sub_b")),
        ),
        active_source_ids={"src_a", "src_b"},
    )

    current_a = _item("a-shared", "src_a", "sub_a")
    first_partial = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_consecutive_partial_one",
        job_type="user_feed_refresh",
        result=_result(
            "run_consecutive_partial_one",
            "partial",
            (current_a,),
            (_outcome("src_a", "sub_a"), _outcome("src_b", "sub_b", failed=True)),
        ),
        active_source_ids={"src_a", "src_b"},
    )
    assert set(first_partial["payload"]["items"][0]["source_ids"]) == {"src_a", "src_b"}

    second_partial = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_consecutive_partial_two",
        job_type="user_feed_refresh",
        result=_result(
            "run_consecutive_partial_two",
            "partial",
            (),
            (
                SourceOutcome(
                    source_id="src_a",
                    subscription_id="sub_a",
                    source_key="rss:https://example.com/src_a.xml",
                    analysis_mode="full",
                    status="succeeded",
                    fetched_count=0,
                ),
                _outcome("src_b", "sub_b", failed=True),
            ),
        ),
        active_source_ids={"src_a", "src_b"},
    )

    assert [item["id"] for item in second_partial["payload"]["items"]] == ["a-shared"]
    assert set(second_partial["payload"]["items"][0]["source_ids"]) == {"src_a", "src_b"}


def test_cross_source_dedup_keeps_distinct_query_identifiers(tmp_path):
    first = _item("query-one", "src_a", "sub_a")
    second = _item("query-two", "src_b", "sub_b")
    first.url = "https://example.com/item?id=1"
    second.url = "https://example.com/item?id=2"

    merged = HorizonOrchestrator(
        _config(),
        StorageManager(data_dir=tmp_path),
    ).merge_cross_source_duplicates([first, second])

    assert {item.id for item in merged} == {"query-one", "query-two"}


def test_incremental_feed_merge_uses_canonical_url_and_stable_existing_id(
    tmp_path, monkeypatch
):
    _store, workspace, owner, service = _service(tmp_path, monkeypatch)
    existing = _item("stable-id", "src_a", "sub_a")
    existing.url = "https://www.example.com/story/?view=full#first"
    first = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_canonical_first",
        job_type="user_feed_refresh",
        result=_result(
            "run_canonical_first",
            "succeeded",
            (existing,),
            (_outcome("src_a", "sub_a"),),
        ),
        active_source_ids={"src_a", "src_b"},
    )
    assert first["payload"]["items"][0]["id"] == "stable-id"

    duplicate = _item("new-native-id", "src_b", "sub_b")
    duplicate.url = "https://example.com/story?view=full#second"
    merged = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_canonical_incremental",
        job_type="source_fetch",
        source_id="src_b",
        result=_result(
            "run_canonical_incremental",
            "succeeded",
            (duplicate,),
            (_outcome("src_b", "sub_b"),),
        ),
    )

    assert [item["id"] for item in merged["payload"]["items"]] == ["stable-id"]
    item = merged["payload"]["items"][0]
    assert set(item["source_ids"]) == {"src_a", "src_b"}
    assert set(item["subscription_ids"]) == {"sub_a", "sub_b"}

    distinct_query = _item("query-two", "src_b", "sub_b")
    distinct_query.url = "https://example.com/story?view=compact"
    distinct = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_canonical_distinct_query",
        job_type="source_fetch",
        source_id="src_b",
        result=_result(
            "run_canonical_distinct_query",
            "succeeded",
            (distinct_query,),
            (_outcome("src_b", "sub_b"),),
        ),
    )

    assert {item["id"] for item in distinct["payload"]["items"]} == {
        "stable-id",
        "query-two",
    }


def test_unchanged_feed_reuses_snapshot_and_changed_content_creates_version(
    tmp_path, monkeypatch
):
    store, workspace, owner, service = _service(tmp_path, monkeypatch)
    published_at = datetime(2026, 7, 14, 8, 0, tzinfo=timezone.utc)
    first_item = _item(
        "same-id", "src_a", "sub_a", published_at=published_at
    )
    first = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_noop_first",
        job_type="user_feed_refresh",
        result=_result(
            "run_noop_first",
            "succeeded",
            (first_item,),
            (_outcome("src_a", "sub_a"),),
        ),
        active_source_ids={"src_a"},
    )
    same_item = _item(
        "same-id", "src_a", "sub_a", published_at=published_at
    )
    second = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_noop_second",
        job_type="user_feed_refresh",
        result=_result(
            "run_noop_second",
            "succeeded",
            (same_item,),
            (_outcome("src_a", "sub_a"),),
        ),
        active_source_ids={"src_a"},
    )

    assert first["snapshot_created"] is True
    assert second["snapshot_created"] is False
    assert second["id"] == first["id"]
    assert store.connect().execute(
        "SELECT COUNT(*) FROM user_feed_snapshots WHERE user_id = ?",
        (owner["id"],),
    ).fetchone()[0] == 1

    changed_item = _item(
        "same-id", "src_a", "sub_a", published_at=published_at
    )
    changed_item.title = "Changed public title"
    changed = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_noop_changed",
        job_type="user_feed_refresh",
        result=_result(
            "run_noop_changed",
            "succeeded",
            (changed_item,),
            (_outcome("src_a", "sub_a"),),
        ),
        active_source_ids={"src_a"},
    )

    assert changed["snapshot_created"] is True
    assert changed["id"] != first["id"]
    assert changed["content_hash"] != first["content_hash"]


def test_compact_feed_write_keeps_full_items_only_in_item_rows_and_dual_reads(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HORIZON_COMPACT_FEED_SNAPSHOTS_ENABLED", "true")
    store, workspace, owner, service = _service(tmp_path, monkeypatch)
    item = _item("compact-id", "src_compact", "sub_compact", score=9.0)
    snapshot = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_compact",
        job_type="user_feed_refresh",
        result=_result(
            "run_compact",
            "succeeded",
            (item,),
            (_outcome("src_compact", "sub_compact"),),
        ),
        active_source_ids={"src_compact"},
    )

    row = store.connect().execute(
        "SELECT storage_version, content_hash, payload_json FROM user_feed_snapshots WHERE id = ?",
        (snapshot["id"],),
    ).fetchone()
    item_row = store.connect().execute(
        "SELECT item_json FROM user_feed_items WHERE snapshot_id = ?",
        (snapshot["id"],),
    ).fetchone()
    compact_payload = json.loads(row["payload_json"])

    assert row["storage_version"] == 2
    assert len(row["content_hash"]) == 64
    assert "items" not in compact_payload
    assert "today_items" not in compact_payload
    assert "featured_items" not in compact_payload
    assert json.loads(item_row["item_json"])["id"] == "compact-id"

    loaded = UserFeedStore(store).latest_snapshot(
        workspace_id=workspace["id"], user_id=owner["id"]
    )
    assert loaded["payload"]["items"][0]["id"] == "compact-id"
    assert loaded["payload"]["today_items"] == loaded["payload"]["items"]
    assert loaded["payload"]["featured_items"][0]["id"] == "compact-id"
    assert loaded["storage_version"] == 2


def test_compact_feed_write_waits_for_storage_v3_migration(tmp_path, monkeypatch):
    store, workspace, owner, _feed_service = _service(tmp_path, monkeypatch)
    store.connect().execute("DELETE FROM schema_migrations WHERE version = 3")
    store.connect().commit()
    feeds = UserFeedStore(store)
    feeds.save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_unmigrated_legacy",
        payload={"schema_version": 2, "items": [{"id": "legacy-item"}]},
    )
    monkeypatch.setenv("HORIZON_COMPACT_FEED_SNAPSHOTS_ENABLED", "true")

    written = feeds.save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_unmigrated_compact_attempt",
        payload={"schema_version": 2, "items": [{"id": "changed-item"}]},
    )

    assert written["storage_version"] == 1
    assert "items" in store.connect().execute(
        "SELECT payload_json FROM user_feed_snapshots WHERE id = ?",
        (written["id"],),
    ).fetchone()["payload_json"]


def test_feed_finalizer_orders_by_score_priority_time_and_id(tmp_path, monkeypatch):
    _store, workspace, owner, service = _service(tmp_path, monkeypatch)
    base_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    items = (
        _item(
            "highest-score",
            "src_score",
            "sub_score",
            source_priority=0,
            score=9.0,
            published_at=base_time - timedelta(hours=1),
        ),
        _item(
            "highest-priority",
            "src_priority",
            "sub_priority",
            source_priority=100,
            score=8.0,
            published_at=base_time - timedelta(hours=2),
        ),
        _item(
            "z-tie",
            "src_tie_z",
            "sub_tie_z",
            source_priority=50,
            score=8.0,
            published_at=base_time,
        ),
        _item(
            "a-tie",
            "src_tie_a",
            "sub_tie_a",
            source_priority=50,
            score=8.0,
            published_at=base_time,
        ),
        _item(
            "newer-but-lower-priority",
            "src_lower",
            "sub_lower",
            source_priority=10,
            score=8.0,
            published_at=base_time + timedelta(minutes=1),
        ),
    )

    snapshot = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_exact_order",
        job_type="user_feed_refresh",
        result=_result(
            "run_exact_order",
            "succeeded",
            items,
            tuple(
                _outcome(item.metadata["source_id"], item.metadata["subscription_id"])
                for item in items
            ),
        ),
        active_source_ids={item.metadata["source_id"] for item in items},
    )

    assert [item["id"] for item in snapshot["payload"]["items"]] == [
        "highest-score",
        "highest-priority",
        "z-tie",
        "a-tie",
        "newer-but-lower-priority",
    ]
    assert [item["source_priority"] for item in snapshot["payload"]["items"]] == [
        0,
        100,
        50,
        50,
        10,
    ]


def test_zero_score_feed_is_priority_first(tmp_path, monkeypatch):
    _store, workspace, owner, service = _service(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    low = _item(
        "new-low-priority",
        "src_low",
        "sub_low",
        source_priority=1,
        published_at=now,
    )
    high = _item(
        "old-high-priority",
        "src_high",
        "sub_high",
        source_priority=99,
        published_at=now - timedelta(hours=1),
    )

    snapshot = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_priority_first",
        job_type="user_feed_refresh",
        result=_result(
            "run_priority_first",
            "succeeded",
            (low, high),
            (_outcome("src_low", "sub_low"), _outcome("src_high", "sub_high")),
        ),
        active_source_ids={"src_low", "src_high"},
    )

    assert [item["id"] for item in snapshot["payload"]["items"]] == [
        "old-high-priority",
        "new-low-priority",
    ]


def test_feed_finalizer_compares_timestamps_as_instants_not_iso_text(
    tmp_path,
    monkeypatch,
):
    _store, workspace, owner, service = _service(tmp_path, monkeypatch)
    newer_instant = datetime.now(timezone.utc)
    older_with_larger_clock_text = (newer_instant - timedelta(hours=1)).astimezone(
        timezone(timedelta(hours=14))
    )
    newer = _item(
        "newer-instant",
        "src_newer",
        "sub_newer",
        source_priority=20,
        published_at=newer_instant,
    )
    older = _item(
        "older-instant",
        "src_older",
        "sub_older",
        source_priority=20,
        published_at=older_with_larger_clock_text,
    )

    snapshot = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_timezone_order",
        job_type="user_feed_refresh",
        result=_result(
            "run_timezone_order",
            "succeeded",
            (older, newer),
            (
                _outcome("src_older", "sub_older"),
                _outcome("src_newer", "sub_newer"),
            ),
        ),
        active_source_ids={"src_older", "src_newer"},
    )

    assert [item["id"] for item in snapshot["payload"]["items"]] == [
        "newer-instant",
        "older-instant",
    ]


def test_source_fetch_merges_items_without_replacing_other_sources(tmp_path, monkeypatch):
    _store, workspace, owner, service = _service(tmp_path, monkeypatch)
    service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_initial",
        job_type="user_feed_refresh",
        result=_result(
            "run_initial",
            "succeeded",
            (_item("a-old", "src_a", "sub_a"), _item("b-old", "src_b", "sub_b")),
            (_outcome("src_a", "sub_a"), _outcome("src_b", "sub_b")),
        ),
        active_source_ids={"src_a", "src_b"},
    )

    snapshot = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_source",
        job_type="source_fetch",
        source_id="src_a",
        result=_result(
            "run_source",
            "succeeded",
            (_item("a-new", "src_a", "sub_a"),),
            (_outcome("src_a", "sub_a"),),
        ),
    )

    assert {item["id"] for item in snapshot["payload"]["items"]} == {
        "a-old",
        "a-new",
        "b-old",
    }
    assert snapshot["new_item_count"] == 1


def test_source_fetch_resorts_full_latest_feed_without_rewriting_old_snapshot(
    tmp_path,
    monkeypatch,
):
    _store, workspace, owner, service = _service(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    first = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_before_priority_fetch",
        job_type="user_feed_refresh",
        result=_result(
            "run_before_priority_fetch",
            "succeeded",
            (
                _item(
                    "existing-low",
                    "src_b",
                    "sub_b",
                    source_priority=5,
                    published_at=now,
                ),
            ),
            (_outcome("src_b", "sub_b"),),
        ),
        active_source_ids={"src_b"},
    )
    first_payload_before = first["payload"]

    latest = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_priority_source_fetch",
        job_type="source_fetch",
        source_id="src_a",
        result=_result(
            "run_priority_source_fetch",
            "succeeded",
            (
                _item(
                    "fetched-high",
                    "src_a",
                    "sub_a",
                    source_priority=80,
                    published_at=now - timedelta(hours=1),
                ),
            ),
            (_outcome("src_a", "sub_a"),),
        ),
    )

    first_after = service.feed_store._snapshot_by_id(first["id"])
    assert [item["id"] for item in latest["payload"]["items"]] == [
        "fetched-high",
        "existing-low",
    ]
    assert first_after["payload"] == first_payload_before
    assert first_after["payload"]["items"] == [first_payload_before["items"][0]]


def test_successful_empty_refresh_retains_recent_active_source_items(tmp_path, monkeypatch):
    _store, workspace, owner, service = _service(tmp_path, monkeypatch)
    service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_old",
        job_type="user_feed_refresh",
        result=_result(
            "run_old",
            "succeeded",
            (_item("old", "src_a", "sub_a"),),
            (_outcome("src_a", "sub_a"),),
        ),
        active_source_ids={"src_a"},
    )

    snapshot = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_empty",
        job_type="user_feed_refresh",
        result=_result(
            "run_empty",
            "succeeded",
            (),
            (
                SourceOutcome(
                    source_id="src_a",
                    subscription_id="sub_a",
                    source_key="rss:https://example.com/src_a.xml",
                    analysis_mode="full",
                    status="succeeded",
                    fetched_count=0,
                ),
            ),
        ),
        active_source_ids={"src_a"},
    )

    assert [item["id"] for item in snapshot["payload"]["items"]] == ["old"]
    assert snapshot["item_count"] == 1
    assert UserFeedStore(_store).latest_snapshot(
        workspace_id=workspace["id"], user_id=owner["id"]
    )["id"] == snapshot["id"]


def test_full_refresh_recovers_recent_social_items_missing_from_latest_snapshot(
    tmp_path, monkeypatch
):
    _store, workspace, owner, service = _service(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    old = _profile_item(
        "twitter:tweet:recent-old",
        "src_x",
        "sub_x",
        source_type=SourceType.TWITTER,
        published_at=now - timedelta(hours=6),
    )
    service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_recent_social_old",
        job_type="user_feed_refresh",
        result=_result(
            "run_recent_social_old",
            "succeeded",
            (old,),
            (_outcome("src_x", "sub_x"),),
        ),
        active_source_ids={"src_x"},
    )

    new = _profile_item(
        "twitter:tweet:recent-new",
        "src_x",
        "sub_x",
        source_type=SourceType.TWITTER,
        published_at=now - timedelta(hours=1),
    )
    legacy_payload = build_site_payload(
        all_items=[new],
        date=now.date().isoformat(),
        total_fetched=1,
        ai_enabled=False,
    )
    legacy_payload.update(
        {
            "schema_version": 2,
            "generated_at": now.isoformat(),
            "run_id": "run_legacy_latest_only",
            "run_status": "succeeded",
        }
    )
    legacy_payload["items"][0]["retention_policy"] = "latest_per_source"
    service.feed_store.save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_legacy_latest_only",
        payload=legacy_payload,
    )

    recovered = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_recent_social_recovered",
        job_type="user_feed_refresh",
        result=_result(
            "run_recent_social_recovered",
            "succeeded",
            (new,),
            (_outcome("src_x", "sub_x"),),
        ),
        active_source_ids={"src_x"},
    )

    assert {item["id"] for item in recovered["payload"]["items"]} == {
        "twitter:tweet:recent-old",
        "twitter:tweet:recent-new",
    }
    assert {
        item["retention_policy"] for item in recovered["payload"]["items"]
    } == {"time_window"}


def test_snapshot_diagnostics_use_safe_public_source_outcome_shape(tmp_path, monkeypatch):
    _store, workspace, owner, service = _service(tmp_path, monkeypatch)
    issue = RunIssue(
        "fetch",
        "HTTPError",
        (
            "request https://alice:url-pass@example.com/feed.xml?api_key=url-secret\n"
            "Bearer bearer-secret payload={'token':'payload-secret'} "
            "stack=Traceback-private"
        ),
        True,
    )
    result = FeedRunResult(
        run_id="run_safe_snapshot",
        status="partial",
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=datetime.now(timezone.utc).isoformat(),
        items=(_item("safe-item", "src_ok", "sub_ok"),),
        source_outcomes=(
            _outcome("src_ok", "sub_ok"),
            SourceOutcome(
                source_id="src_bad",
                subscription_id="sub_bad",
                source_key="rss:https://alice:key@example.com/feed.xml?token=source-key-secret",
                analysis_mode="full",
                status="failed",
                fetched_count=0,
                issue=issue,
            ),
        ),
        issues=(issue,),
    )

    snapshot = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_safe_snapshot",
        job_type="user_feed_refresh",
        result=result,
        active_source_ids={"src_ok", "src_bad"},
    )

    diagnostics = {
        "source_outcomes": snapshot["payload"]["source_outcomes"],
        "issues": snapshot["payload"]["issues"],
    }
    failed = diagnostics["source_outcomes"][1]
    assert set(failed) == {
        "source_id",
        "subscription_id",
        "source_key",
        "analysis_mode",
        "status",
        "fetched_count",
        "issue",
    }
    assert set(failed["issue"]) == {"stage", "code", "message", "retryable"}
    assert failed["source_key"] == "rss:https://example.com/feed.xml"
    assert "\n" not in failed["issue"]["message"]
    assert len(failed["issue"]["message"]) <= 240
    serialized = str(diagnostics)
    for secret in (
        "alice",
        "url-pass",
        "url-secret",
        "bearer-secret",
        "payload-secret",
        "Traceback-private",
        "source-key-secret",
    ):
        assert secret not in serialized


def test_empty_or_failed_user_refresh_never_reuses_another_users_snapshot(tmp_path, monkeypatch):
    store, workspace, owner, service = _service(tmp_path, monkeypatch)
    member = store.create_user(
        workspace_id=workspace["id"],
        username="member",
        password="member-password",
        role="member",
    )
    service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_owner",
        job_type="user_feed_refresh",
        result=_result(
            "run_owner",
            "succeeded",
            (_item("owner-only", "src_owner", "sub_owner"),),
            (_outcome("src_owner", "sub_owner"),),
        ),
        active_source_ids={"src_owner"},
    )

    with pytest.raises(ValueError, match="failed run"):
        service.save_run_result(
            workspace_id=workspace["id"],
            user_id=member["id"],
            job_id="job_member_failed",
            job_type="user_feed_refresh",
            result=_result(
                "run_member_failed",
                "failed",
                (),
                (_outcome("src_member", "sub_member", failed=True),),
            ),
            active_source_ids={"src_member"},
        )
    assert UserFeedStore(store).latest_snapshot(
        workspace_id=workspace["id"], user_id=member["id"]
    ) is None

    empty = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=member["id"],
        job_id="job_member_empty",
        job_type="user_feed_refresh",
        result=_result(
            "run_member_empty",
            "succeeded",
            (),
            (
                SourceOutcome(
                    source_id="src_member",
                    subscription_id="sub_member",
                    source_key="rss:https://example.com/member.xml",
                    analysis_mode="full",
                    status="succeeded",
                    fetched_count=0,
                ),
            ),
        ),
        active_source_ids={"src_member"},
    )

    assert empty["payload"]["items"] == []
    owner_latest = UserFeedStore(store).latest_snapshot(
        workspace_id=workspace["id"], user_id=owner["id"]
    )
    assert {item["id"] for item in owner_latest["payload"]["items"]} == {"owner-only"}


def test_full_refresh_removes_sources_that_are_no_longer_active(tmp_path, monkeypatch):
    _store, workspace, owner, service = _service(tmp_path, monkeypatch)
    service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_before_unsubscribe",
        job_type="user_feed_refresh",
        result=_result(
            "run_before_unsubscribe",
            "succeeded",
            (_item("a-old", "src_a", "sub_a"), _item("b-old", "src_b", "sub_b")),
            (_outcome("src_a", "sub_a"), _outcome("src_b", "sub_b")),
        ),
        active_source_ids={"src_a", "src_b"},
    )

    snapshot = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_after_unsubscribe",
        job_type="user_feed_refresh",
        result=_result(
            "run_after_unsubscribe",
            "succeeded",
            (_item("a-new", "src_a", "sub_a"),),
            (_outcome("src_a", "sub_a"),),
        ),
        active_source_ids={"src_a"},
    )

    assert {item["id"] for item in snapshot["payload"]["items"]} == {
        "a-old",
        "a-new",
    }


def test_partial_job_retry_atomically_replaces_its_existing_snapshot(tmp_path, monkeypatch):
    store, workspace, owner, service = _service(tmp_path, monkeypatch)
    queue = JobQueue(store)
    job = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="user_feed_refresh",
    )
    first_claim = queue.claim_next_job(worker_id="worker-a", lease_seconds=60)
    partial_snapshot = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=job["id"],
        job_type="user_feed_refresh",
        result=_result(
            "run_partial",
            "partial",
            (_item("partial-item", "src_a", "sub_a"),),
            (_outcome("src_a", "sub_a"), _outcome("src_b", "sub_b", failed=True)),
        ),
        active_source_ids={"src_a", "src_b"},
        commit=False,
    )
    queue.complete_job(
        job["id"],
        status="partial",
        result={"snapshot_id": partial_snapshot["id"]},
        worker_id="worker-a",
        claim_token=first_claim["claim_token"],
    )

    queue.retry_job(job["id"], user_id=owner["id"])
    second_claim = queue.claim_next_job(worker_id="worker-b", lease_seconds=60)
    succeeded_snapshot = service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=job["id"],
        job_type="user_feed_refresh",
        result=_result(
            "run_succeeded",
            "succeeded",
            (
                _item("final-a", "src_a", "sub_a"),
                _item("final-b", "src_b", "sub_b"),
            ),
            (_outcome("src_a", "sub_a"), _outcome("src_b", "sub_b")),
        ),
        active_source_ids={"src_a", "src_b"},
        commit=False,
    )
    queue.complete_job(
        job["id"],
        status="succeeded",
        result={"snapshot_id": succeeded_snapshot["id"]},
        worker_id="worker-b",
        claim_token=second_claim["claim_token"],
    )

    assert succeeded_snapshot["id"] == partial_snapshot["id"]
    assert succeeded_snapshot["payload"]["run_id"] == "run_succeeded"
    assert succeeded_snapshot["payload"]["run_status"] == "succeeded"
    assert {item["id"] for item in succeeded_snapshot["payload"]["items"]} == {
        "final-a",
        "final-b",
        "partial-item",
    }
    assert store.connect().execute(
        "SELECT COUNT(*) FROM user_feed_snapshots WHERE job_id = ?",
        (job["id"],),
    ).fetchone()[0] == 1
    assert {
        row["article_id"]
        for row in store.connect().execute(
            "SELECT article_id FROM user_feed_items WHERE snapshot_id = ?",
            (succeeded_snapshot["id"],),
        )
    } == {"final-a", "final-b", "partial-item"}


def test_concurrent_source_fetches_for_one_user_do_not_lose_each_other(tmp_path, monkeypatch):
    first_store, workspace, owner, first_service = _service(tmp_path, monkeypatch)
    first_service.save_run_result(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_initial",
        job_type="user_feed_refresh",
        result=_result(
            "run_initial",
            "succeeded",
            (_item("base", "src_base", "sub_base"),),
            (_outcome("src_base", "sub_base"),),
        ),
        active_source_ids={"src_base"},
    )
    second_store = ServiceStore(tmp_path)
    second_store.initialize()
    second_service = FeedProductionService(second_store, _config())

    second_read = threading.Event()
    first_read = threading.Event()
    first_saved = threading.Event()
    original_first_latest = first_service.feed_store.latest_snapshot
    original_first_save = first_service.feed_store.save_run_snapshot
    original_second_latest = second_service.feed_store.latest_snapshot
    original_second_save = second_service.feed_store.save_run_snapshot

    def observed_first_latest(**kwargs):
        snapshot = original_first_latest(**kwargs)
        first_read.set()
        return snapshot

    def delayed_first_save(**kwargs):
        second_read.wait(timeout=0.5)
        try:
            return original_first_save(**kwargs)
        finally:
            first_saved.set()

    def observed_second_latest(**kwargs):
        snapshot = original_second_latest(**kwargs)
        second_read.set()
        return snapshot

    def delayed_second_save(**kwargs):
        assert first_saved.wait(timeout=3)
        return original_second_save(**kwargs)

    monkeypatch.setattr(first_service.feed_store, "latest_snapshot", observed_first_latest)
    monkeypatch.setattr(first_service.feed_store, "save_run_snapshot", delayed_first_save)
    monkeypatch.setattr(second_service.feed_store, "latest_snapshot", observed_second_latest)
    monkeypatch.setattr(second_service.feed_store, "save_run_snapshot", delayed_second_save)

    def save(service, job_id, item_id, source_id):
        return service.save_run_result(
            workspace_id=workspace["id"],
            user_id=owner["id"],
            job_id=job_id,
            job_type="source_fetch",
            source_id=source_id,
            result=_result(
                f"run_{item_id}",
                "succeeded",
                (_item(item_id, source_id, f"sub_{source_id}"),),
                (_outcome(source_id, f"sub_{source_id}"),),
            ),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(save, first_service, "job_a", "item-a", "src_a")
        assert first_read.wait(timeout=3)
        futures = [
            first_future,
            executor.submit(save, second_service, "job_b", "item-b", "src_b"),
        ]
        for future in futures:
            future.result(timeout=10)

    latest = UserFeedStore(first_store).latest_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
    )
    assert {item["id"] for item in latest["payload"]["items"]} == {
        "base",
        "item-a",
        "item-b",
    }
