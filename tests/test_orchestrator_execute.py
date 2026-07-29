from dataclasses import FrozenInstanceError, fields
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from src.models import Config, ContentItem, SourceType
from src.orchestrator import HorizonOrchestrator
from src.scrapers.hackernews import HackerNewsScraper
from src.services.feed_run import (
    AcquisitionUsage,
    FeedRunResult,
    RunIssue,
    SourceOutcome,
    safe_run_diagnostics,
)
from src.services.source_acquisition import SourceAcquisitionCoordinator
from src.storage.manager import StorageManager
from src.storage.service_store import ServiceStore


def _config(*, ai_enabled: bool = False) -> Config:
    return Config.model_validate(
        {
            "version": "1.0",
            "ai": {
                "enabled": ai_enabled,
                "provider": "openai",
                "model": "gpt-4o-mini",
                "api_key_env": "MISSING_TEST_API_KEY",
            },
            "sources": {"hackernews": {"enabled": True}},
            "filtering": {
                "featured_score_threshold": 7.5,
                "daily_push_score_threshold": 8.5,
                "time_window_hours": 24,
            },
        }
    )


def _item(item_id: str, url: str, *, content: str | None = None) -> ContentItem:
    return ContentItem(
        id=item_id,
        source_type=SourceType.HACKERNEWS,
        title=item_id,
        url=url,
        content=content,
        published_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
    )


class _ForbiddenNotifications:
    def __getattr__(self, name):
        raise AssertionError(f"notification side effect invoked: {name}")


def _forbid_legacy_side_effects(monkeypatch, orchestrator):
    async def forbidden(*args, **kwargs):
        raise AssertionError("legacy publisher side effect invoked")

    def forbidden_factory(*args, **kwargs):
        raise AssertionError("summary generation invoked")

    monkeypatch.setattr(orchestrator, "_write_web_ui", forbidden)
    monkeypatch.setattr(orchestrator, "_run_article_graph_pipeline", forbidden)
    monkeypatch.setattr(orchestrator, "_generate_summary", forbidden)
    monkeypatch.setattr("src.orchestrator.DailySummarizer", forbidden_factory)
    monkeypatch.setattr("src.orchestrator.load_history_item_ids", forbidden_factory)
    orchestrator.email_manager = _ForbiddenNotifications()
    orchestrator.webhook_notifier = _ForbiddenNotifications()


def test_feed_run_models_are_frozen_schema_v2_values():
    issue = RunIssue(
        stage="fetch",
        code="timeout",
        message="source timed out",
        retryable=True,
    )
    outcome = SourceOutcome(
        source_id="source_1",
        subscription_id=None,
        source_key="rss:https://example.com/feed.xml",
        analysis_mode="full",
        status="failed",
        fetched_count=0,
        issue=issue,
    )
    result = FeedRunResult(
        run_id="run_example",
        status="partial",
        started_at="2026-07-10T01:00:00+00:00",
        finished_at="2026-07-10T01:00:01+00:00",
        source_outcomes=(outcome,),
        issues=(issue,),
        acquisition_usage=AcquisitionUsage(
            cache_hits=2,
            cache_misses=1,
            upstream_attempts=1,
            waits=3,
        ),
    )

    assert result.schema_version == 2
    assert result.items == ()
    assert result.featured_item_ids == ()
    assert result.daily_push_item_ids == ()
    assert result.source_outcomes == (outcome,)
    assert result.issues == (issue,)
    with pytest.raises(FrozenInstanceError):
        issue.code = "changed"
    assert [field.name for field in fields(FeedRunResult)] == [
        "schema_version",
        "run_id",
        "status",
        "started_at",
        "finished_at",
        "items",
        "featured_item_ids",
        "daily_push_item_ids",
        "source_outcomes",
        "issues",
        "analysis_usage",
        "acquisition_usage",
    ]
    assert safe_run_diagnostics(result, item_count=0)["acquisition_usage"] == {
        "cache_hits": 2,
        "cache_misses": 1,
        "upstream_attempts": 1,
        "waits": 3,
    }
    with pytest.raises(FrozenInstanceError):
        outcome.status = "succeeded"
    with pytest.raises(FrozenInstanceError):
        result.status = "succeeded"


def test_execute_returns_fresh_succeeded_empty_result_without_legacy_side_effects(
    tmp_path,
    monkeypatch,
):
    orchestrator = HorizonOrchestrator(
        _config(),
        StorageManager(data_dir=str(tmp_path)),
    )

    async def fetch_nothing(since, **_kwargs):
        return [], ()

    monkeypatch.setattr(orchestrator, "fetch_service_sources", fetch_nothing)
    _forbid_legacy_side_effects(monkeypatch, orchestrator)

    first = asyncio.run(orchestrator.execute())
    second = asyncio.run(orchestrator.execute())

    assert first.schema_version == 2
    assert first.run_id.startswith("run_")
    assert second.run_id.startswith("run_")
    assert first.run_id != second.run_id
    assert first.status == "succeeded"
    assert first.items == ()
    assert first.featured_item_ids == ()
    assert first.daily_push_item_ids == ()
    assert first.source_outcomes == ()
    assert first.issues == ()
    assert datetime.fromisoformat(first.started_at).tzinfo is not None
    assert datetime.fromisoformat(first.finished_at).tzinfo is not None


def test_execute_ai_enabled_empty_result_skips_analysis_selection(tmp_path, monkeypatch):
    orchestrator = HorizonOrchestrator(
        _config(ai_enabled=True),
        StorageManager(data_dir=str(tmp_path)),
    )

    async def fetch_nothing(since, **_kwargs):
        return [], ()

    async def forbidden_stage(*args, **kwargs):
        raise AssertionError("empty feed entered analysis or selection")

    monkeypatch.setattr(orchestrator, "fetch_service_sources", fetch_nothing)
    monkeypatch.setattr(orchestrator, "_analyze_content", forbidden_stage)
    monkeypatch.setattr(orchestrator, "merge_topic_duplicates", forbidden_stage)
    monkeypatch.setattr(orchestrator, "_expand_twitter_discussion", forbidden_stage)
    monkeypatch.setattr(orchestrator, "_enrich_important_items", forbidden_stage)
    _forbid_legacy_side_effects(monkeypatch, orchestrator)

    result = asyncio.run(orchestrator.execute(enrich=True))

    assert result.status == "succeeded"
    assert result.items == ()
    assert result.featured_item_ids == ()
    assert result.daily_push_item_ids == ()


def test_execute_returns_structured_failure_for_pipeline_exception(tmp_path, monkeypatch):
    orchestrator = HorizonOrchestrator(
        _config(),
        StorageManager(data_dir=str(tmp_path)),
    )

    async def fail_fetch(since, **_kwargs):
        raise TimeoutError("source fetch timed out")

    monkeypatch.setattr(orchestrator, "fetch_service_sources", fail_fetch)
    _forbid_legacy_side_effects(monkeypatch, orchestrator)

    result = asyncio.run(orchestrator.execute())

    assert result.status == "failed"
    assert result.items == ()
    assert result.featured_item_ids == ()
    assert result.daily_push_item_ids == ()
    assert len(result.issues) == 1
    assert result.issues[0].stage == "pipeline"
    assert result.issues[0].code == "TimeoutError"
    assert result.issues[0].message == "source fetch timed out"
    assert result.issues[0].retryable is True


def test_execute_marks_deterministic_pipeline_exception_non_retryable(
    tmp_path, monkeypatch
):
    orchestrator = HorizonOrchestrator(
        _config(),
        StorageManager(data_dir=str(tmp_path)),
    )

    async def fail_fetch(_since, **_kwargs):
        raise ValueError("invalid deterministic source configuration")

    monkeypatch.setattr(orchestrator, "fetch_service_sources", fail_fetch)
    _forbid_legacy_side_effects(monkeypatch, orchestrator)

    result = asyncio.run(orchestrator.execute())

    assert result.status == "failed"
    assert result.issues[0].code == "ValueError"
    assert result.issues[0].retryable is False


def test_fetch_service_source_defaults_unknown_exception_to_non_retryable(
    tmp_path, monkeypatch
):
    config = _config()
    config.sources.hackernews.source_id = "src_hn"
    config.sources.hackernews.subscription_id = "sub_hn"
    config.sources.hackernews.source_key = "hackernews:top"
    orchestrator = HorizonOrchestrator(
        config,
        StorageManager(data_dir=str(tmp_path)),
    )

    class FailingScraper:
        async def fetch(self, _since):
            raise ValueError("deterministic parse failure")

    monkeypatch.setattr(
        orchestrator,
        "_service_source_specs",
        lambda _client: [
            ("HackerNews:src_hn", FailingScraper(), config.sources.hackernews)
        ],
    )
    _forbid_legacy_side_effects(monkeypatch, orchestrator)

    result = asyncio.run(orchestrator.execute())

    assert result.status == "failed"
    assert result.source_outcomes[0].issue is not None
    assert result.source_outcomes[0].issue.code == "ValueError"
    assert result.source_outcomes[0].issue.retryable is False


def test_execute_returns_partial_with_per_source_outcomes(tmp_path, monkeypatch):
    orchestrator = HorizonOrchestrator(
        _config(),
        StorageManager(data_dir=str(tmp_path)),
    )
    item = _item("hackernews:item:partial", "https://example.com/partial")
    issue = RunIssue(
        stage="fetch",
        code="TimeoutError",
        message="rss timed out",
        retryable=True,
    )
    outcomes = (
        SourceOutcome(
            source_id="src_hn",
            subscription_id="sub_hn",
            source_key="hackernews",
            analysis_mode="full",
            status="succeeded",
            fetched_count=1,
        ),
        SourceOutcome(
            source_id="src_rss",
            subscription_id="sub_rss",
            source_key="rss:https://example.com/feed.xml",
            analysis_mode="full",
            status="failed",
            fetched_count=0,
            issue=issue,
        ),
    )

    async def fetch_partial(_since, **_kwargs):
        return [item], outcomes

    monkeypatch.setattr(orchestrator, "fetch_service_sources", fetch_partial)
    _forbid_legacy_side_effects(monkeypatch, orchestrator)

    result = asyncio.run(orchestrator.execute())

    assert result.status == "partial"
    assert result.items == (item,)
    assert result.source_outcomes == outcomes
    assert result.issues == (issue,)


def test_fetch_service_sources_stamps_priority_even_when_adapter_metadata_omits_it(
    tmp_path,
    monkeypatch,
):
    config = _config()
    config.sources.hackernews.source_id = "src_hn"
    config.sources.hackernews.subscription_id = "sub_hn"
    config.sources.hackernews.source_key = "hackernews:top"
    config.sources.hackernews.source_priority = 64
    item = _item("hackernews:item:priority", "https://example.com/priority")

    class AdapterWithoutPriorityMetadata:
        async def fetch(self, _since):
            return [item]

    orchestrator = HorizonOrchestrator(config, StorageManager(data_dir=str(tmp_path)))
    monkeypatch.setattr(
        orchestrator,
        "_service_source_specs",
        lambda _client: [
            (
                "HackerNews:src_hn",
                AdapterWithoutPriorityMetadata(),
                config.sources.hackernews,
            )
        ],
    )

    items, outcomes = asyncio.run(
        orchestrator.fetch_service_sources(datetime.now(timezone.utc))
    )

    assert items[0].metadata["source_priority"] == 64
    assert outcomes[0].source_id == "src_hn"


def test_execute_uses_runtime_rss_window_until_explicit_hours_override(
    tmp_path,
    monkeypatch,
):
    config = Config.model_validate(
        {
            "version": "1.0",
            "ai": {
                "enabled": False,
                "provider": "openai",
                "model": "gpt-4o-mini",
                "api_key_env": "MISSING_TEST_API_KEY",
            },
            "sources": {
                "rss": [
                    {
                        "name": "Initial RSS",
                        "url": "https://example.com/initial.xml",
                        "source_id": "src_initial",
                        "subscription_id": "sub_initial",
                        "service_fetch_window_hours": 168,
                    },
                    {
                        "name": "Daily RSS",
                        "url": "https://example.com/daily.xml",
                        "source_id": "src_daily",
                        "subscription_id": "sub_daily",
                    },
                ],
                "hackernews": {"enabled": False},
            },
            "filtering": {"time_window_hours": 24},
        }
    )
    orchestrator = HorizonOrchestrator(
        config,
        StorageManager(data_dir=str(tmp_path)),
    )
    windows: dict[str, float] = {}

    async def capture_fetch(_label, _scraper, _source, since):
        windows[_source.name] = (
            datetime.now(timezone.utc) - since
        ).total_seconds() / 3600
        return []

    monkeypatch.setattr(orchestrator, "_fetch_service_source", capture_fetch)
    _forbid_legacy_side_effects(monkeypatch, orchestrator)

    default_result = asyncio.run(orchestrator.execute())
    assert default_result.status == "succeeded"
    assert len(windows) == 2
    assert 167.9 <= windows["Initial RSS"] <= 168.1
    assert 23.9 <= windows["Daily RSS"] <= 24.1

    windows.clear()
    forced_result = asyncio.run(orchestrator.execute(force_hours=6))
    assert forced_result.status == "succeeded"
    assert len(windows) == 2
    assert all(5.9 <= value <= 6.1 for value in windows.values())


def test_fetch_service_sources_admits_attempt_before_adapter_network_call(
    tmp_path, monkeypatch
):
    config = _config()
    config.sources.hackernews.source_id = "src_hn"
    config.sources.hackernews.subscription_id = "sub_hn"
    events = []

    class AttemptMeter:
        def before_fetch_attempt(self, *, provider, source_id):
            events.append(("admit", provider, source_id))

    class Adapter:
        async def fetch(self, _since):
            events.append(("fetch", "hackernews", "src_hn"))
            return []

    orchestrator = HorizonOrchestrator(config, StorageManager(data_dir=str(tmp_path)))
    orchestrator.set_service_attempt_meter(AttemptMeter())
    monkeypatch.setattr(
        orchestrator,
        "_service_source_specs",
        lambda _client: [("HackerNews:src_hn", Adapter(), config.sources.hackernews)],
    )

    asyncio.run(orchestrator.fetch_service_sources(datetime.now(timezone.utc)))

    assert events == [
        ("admit", "hackernews", "src_hn"),
        ("fetch", "hackernews", "src_hn"),
    ]


def test_fetch_service_sources_serializes_x_profile_actor_calls_per_job(
    tmp_path,
    monkeypatch,
):
    config = _config()
    active = 0
    max_active = 0

    class MeteredActor:
        async def fetch(self, _since):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            return []

    def source(source_id):
        return SimpleNamespace(
            source_id=source_id,
            subscription_id=f"sub_{source_id}",
            source_key=f"apify:x:profile:{source_id}",
            platform="x",
            kind="profile",
            analysis_mode="full",
            source_priority=50,
            service_fetch_window_hours=None,
            catalog_source_type="apify_social",
        )

    orchestrator = HorizonOrchestrator(
        config,
        StorageManager(data_dir=str(tmp_path)),
    )
    monkeypatch.setattr(
        orchestrator,
        "_service_source_specs",
        lambda _client: [
            ("Apify:src_x_1", MeteredActor(), source("src_x_1")),
            ("Apify:src_x_2", MeteredActor(), source("src_x_2")),
        ],
    )

    _items, outcomes = asyncio.run(
        orchestrator.fetch_service_sources(datetime.now(timezone.utc))
    )

    assert max_active == 1
    assert [outcome.status for outcome in outcomes] == ["succeeded", "succeeded"]


def test_orchestrator_shared_acquisition_reuses_upstream_but_projects_subscription(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    member = store.create_user(
        workspace_id=workspace["id"],
        username="member",
        password="member-password",
    )
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="hackernews",
        display_name="Hacker News",
        config={"fetch_top_stories": 30, "min_score": 100},
        source_key="hackernews:top",
    )
    owner_sub = store.create_subscription(user_id=owner["id"], source_id=source_id)
    member_sub = store.create_subscription(user_id=member["id"], source_id=source_id)
    events = []

    class AttemptMeter:
        def before_fetch_attempt(self, *, provider, source_id):
            events.append(("admit", provider, source_id))

    class Adapter:
        def __init__(self, subscription_id):
            self.subscription_id = subscription_id

        async def fetch(self, _since):
            events.append(("fetch", self.subscription_id))
            item = _item(
                "hackernews:item:shared",
                "https://example.com/shared?view=full",
            )
            item.metadata["subscription_id"] = self.subscription_id
            item.metadata["source_id"] = source_id
            return [item]

    def orchestrator_for(user, subscription):
        config = _config()
        config.sources.hackernews.source_id = source_id
        config.sources.hackernews.subscription_id = subscription["id"]
        config.sources.hackernews.source_key = "hackernews:top"
        orchestrator = HorizonOrchestrator(
            config, StorageManager(data_dir=str(tmp_path))
        )
        orchestrator.set_service_attempt_meter(AttemptMeter())
        coordinator = SourceAcquisitionCoordinator(
            store,
            workspace_id=workspace["id"],
            user_id=user["id"],
            job_id=f"job-{user['id']}",
        )
        orchestrator.set_service_acquisition_coordinator(coordinator)
        monkeypatch.setattr(
            orchestrator,
            "_service_source_specs",
            lambda _client: [
                (
                    f"HackerNews:{source_id}",
                    Adapter(subscription["id"]),
                    config.sources.hackernews,
                )
            ],
        )
        return orchestrator, coordinator

    first, first_coordinator = orchestrator_for(owner, owner_sub)
    second, second_coordinator = orchestrator_for(member, member_sub)
    first_result = asyncio.run(first.execute(force_hours=24))
    second_result = asyncio.run(second.execute(force_hours=24))

    assert events == [
        ("admit", "hackernews", source_id),
        ("fetch", owner_sub["id"]),
    ]
    assert first_result.items[0].metadata["subscription_id"] == owner_sub["id"]
    assert second_result.items[0].metadata["subscription_id"] == member_sub["id"]
    assert first_result.acquisition_usage.as_dict()["upstream_attempts"] == 1
    assert second_result.acquisition_usage.as_dict()["cache_hits"] == 1
    assert first_coordinator.metrics.as_dict()["cache_misses"] == 1
    assert second_coordinator.metrics.as_dict()["cache_hits"] == 1
    assert second_result.source_outcomes[0].capture_status == "cached"
    assert second_result.source_outcomes[0].upstream_schema is None


def test_execute_returns_failed_when_all_service_sources_fail(tmp_path, monkeypatch):
    orchestrator = HorizonOrchestrator(
        _config(),
        StorageManager(data_dir=str(tmp_path)),
    )
    issue = RunIssue(
        stage="fetch",
        code="TimeoutError",
        message="all sources timed out",
        retryable=True,
    )
    outcomes = (
        SourceOutcome(
            source_id="src_hn",
            subscription_id="sub_hn",
            source_key="hackernews",
            analysis_mode="full",
            status="failed",
            fetched_count=0,
            issue=issue,
        ),
    )

    async def fetch_failed(_since, **_kwargs):
        return [], outcomes

    monkeypatch.setattr(orchestrator, "fetch_service_sources", fetch_failed)
    _forbid_legacy_side_effects(monkeypatch, orchestrator)

    result = asyncio.run(orchestrator.execute())

    assert result.status == "failed"
    assert result.items == ()
    assert result.source_outcomes == outcomes
    assert result.issues == (issue,)


def test_execute_uses_failed_outcome_for_partial_even_without_issue(tmp_path, monkeypatch):
    orchestrator = HorizonOrchestrator(_config(), StorageManager(data_dir=str(tmp_path)))
    item = _item("hackernews:item:no-issue", "https://example.com/no-issue")
    outcomes = (
        SourceOutcome("src_ok", "sub_ok", "hackernews", "full", "succeeded", 1),
        SourceOutcome("src_failed", "sub_failed", "rss:failed", "full", "failed", 0),
    )

    async def fetch_mixed(_since, **_kwargs):
        return [item], outcomes

    monkeypatch.setattr(orchestrator, "fetch_service_sources", fetch_mixed)
    _forbid_legacy_side_effects(monkeypatch, orchestrator)

    result = asyncio.run(orchestrator.execute())

    assert result.status == "partial"
    assert result.source_outcomes == outcomes
    assert result.issues == ()


def test_execute_preserves_fetch_issue_when_later_analysis_fails(tmp_path, monkeypatch):
    orchestrator = HorizonOrchestrator(_config(ai_enabled=True), StorageManager(data_dir=str(tmp_path)))
    item = _item("hackernews:item:late-fail", "https://example.com/late-fail")
    fetch_issue = RunIssue("fetch", "TimeoutError", "rss timeout", True)
    outcomes = (
        SourceOutcome("src_ok", "sub_ok", "hackernews", "full", "succeeded", 1),
        SourceOutcome("src_bad", "sub_bad", "rss:bad", "full", "failed", 0, fetch_issue),
    )

    async def fetch_mixed(_since, **_kwargs):
        return [item], outcomes

    async def fail_analysis(_items):
        raise RuntimeError("analysis unavailable")

    monkeypatch.setattr(orchestrator, "fetch_service_sources", fetch_mixed)
    monkeypatch.setattr(orchestrator, "_analyze_content", fail_analysis)
    _forbid_legacy_side_effects(monkeypatch, orchestrator)

    result = asyncio.run(orchestrator.execute())

    assert result.status == "failed"
    assert result.source_outcomes == outcomes
    assert [issue.code for issue in result.issues] == ["TimeoutError", "RuntimeError"]


def test_execute_ai_analysis_does_not_use_the_global_disk_cache(tmp_path, monkeypatch):
    orchestrator = HorizonOrchestrator(
        _config(ai_enabled=True),
        StorageManager(data_dir=str(tmp_path)),
    )
    item = _item("hackernews:item:private", "https://example.com/private")

    async def fetch_item(_since, **_kwargs):
        return [item], ()

    async def analyze_without_cache(analyzer, items):
        assert analyzer.cache is None
        items[0].ai_score = 1.0
        return items

    monkeypatch.setattr(orchestrator, "fetch_service_sources", fetch_item)
    monkeypatch.setattr("src.orchestrator.create_ai_client", lambda _config: object())
    monkeypatch.setattr("src.orchestrator.ContentAnalyzer.analyze_batch", analyze_without_cache)
    _forbid_legacy_side_effects(monkeypatch, orchestrator)

    result = asyncio.run(orchestrator.execute())

    assert result.status == "succeeded"
    assert not (tmp_path / "cache" / "analysis-cache.jsonl").exists()


def test_execute_returns_analyzed_deduped_items_and_selection_ids_without_publishing(
    tmp_path,
    monkeypatch,
):
    orchestrator = HorizonOrchestrator(
        _config(ai_enabled=True),
        StorageManager(data_dir=str(tmp_path)),
    )
    duplicate = _item(
        "hackernews:item:duplicate",
        "https://example.com/shared",
    )
    retained = _item(
        "hackernews:item:retained",
        "https://example.com/shared/",
        content="richer shared-source content",
    )
    featured = _item(
        "hackernews:item:featured",
        "https://example.com/featured",
    )
    daily = _item(
        "hackernews:item:daily",
        "https://example.com/daily",
    )

    async def fetch_items(since, **_kwargs):
        return [duplicate, retained, featured, daily], ()

    async def analyze(items):
        scores = {
            retained.id: 4.0,
            featured.id: 8.0,
            daily.id: 9.0,
        }
        for item in items:
            item.ai_score = scores[item.id]
        return items

    topic_dedupe_inputs = []

    async def keep_topic_items(items):
        topic_dedupe_inputs.append(tuple(item.id for item in items))
        return items

    async def forbidden_enrichment(items):
        raise AssertionError("enrichment must be opt-in")

    monkeypatch.setattr(orchestrator, "fetch_service_sources", fetch_items)
    monkeypatch.setattr(orchestrator, "_analyze_content", analyze)
    monkeypatch.setattr(orchestrator, "merge_topic_duplicates", keep_topic_items)
    monkeypatch.setattr(orchestrator, "_enrich_important_items", forbidden_enrichment)
    _forbid_legacy_side_effects(monkeypatch, orchestrator)

    result = asyncio.run(orchestrator.execute())

    assert result.status == "succeeded"
    assert tuple(item.id for item in result.items) == (
        retained.id,
        featured.id,
        daily.id,
    )
    assert result.featured_item_ids == (daily.id, featured.id)
    assert result.daily_push_item_ids == (daily.id,)
    assert topic_dedupe_inputs == [(daily.id, featured.id)]
    assert result.source_outcomes == ()
    assert result.issues == ()


def test_execute_makes_mixed_mode_url_group_personal_only_before_ai(tmp_path, monkeypatch):
    orchestrator = HorizonOrchestrator(
        _config(ai_enabled=True),
        StorageManager(data_dir=str(tmp_path)),
    )
    full = _item(
        "hackernews:item:full",
        "https://example.com/shared",
        content="Public source content that is deliberately the richer primary item.",
    )
    full.metadata.update(
        {
            "source_id": "src_full",
            "subscription_id": "sub_full",
            "analysis_mode": "full",
        }
    )
    personal = _item(
        "hackernews:item:personal",
        "https://example.com/shared/",
        content="PRIVATE PERSONAL CONTENT",
    )
    personal.metadata.update(
        {
            "source_id": "src_personal",
            "subscription_id": "sub_personal",
            "analysis_mode": "personal_only",
            "show_in_personal_feed": True,
        }
    )
    outcomes = (
        SourceOutcome("src_full", "sub_full", "hn:full", "full", "succeeded", 1),
        SourceOutcome(
            "src_personal",
            "sub_personal",
            "hn:personal",
            "personal_only",
            "succeeded",
            1,
        ),
    )

    async def fetch_items(_since, **_kwargs):
        return [full, personal], outcomes

    analyzed_content = []

    async def capture_analysis(_analyzer, items):
        analyzed_content.extend(item.content for item in items)
        for item in items:
            item.ai_score = 9.5
        return items

    monkeypatch.setattr(orchestrator, "fetch_service_sources", fetch_items)
    monkeypatch.setattr("src.orchestrator.create_ai_client", lambda _config: object())
    monkeypatch.setattr("src.orchestrator.ContentAnalyzer.analyze_batch", capture_analysis)
    _forbid_legacy_side_effects(monkeypatch, orchestrator)

    result = asyncio.run(orchestrator.execute())

    assert result.status == "succeeded"
    assert len(result.items) == 1
    assert result.items[0].metadata["analysis_mode"] == "personal_only"
    assert result.items[0].metadata["show_in_personal_feed"] is True
    assert "PRIVATE PERSONAL CONTENT" in (result.items[0].content or "")
    assert analyzed_content == []
    assert result.featured_item_ids == ()
    assert result.daily_push_item_ids == ()


def test_execute_marks_hackernews_story_request_failure_as_failed_source(tmp_path, monkeypatch):
    config = _config()
    config.sources.hackernews.source_id = "src_hn"
    config.sources.hackernews.subscription_id = "sub_hn"
    config.sources.hackernews.source_key = "hackernews:top"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/topstories.json"):
            return httpx.Response(200, json=[1])
        if request.url.path.endswith("/item/1.json"):
            return httpx.Response(503, text="temporarily unavailable")
        raise AssertionError(f"unexpected url: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    scraper = HackerNewsScraper(config.sources.hackernews, client)
    scraper.strict_errors = True
    orchestrator = HorizonOrchestrator(config, StorageManager(data_dir=str(tmp_path)))
    monkeypatch.setattr(
        orchestrator,
        "_service_source_specs",
        lambda _client: [("HackerNews:src_hn", scraper, config.sources.hackernews)],
    )
    _forbid_legacy_side_effects(monkeypatch, orchestrator)

    result = asyncio.run(orchestrator.execute())
    asyncio.run(client.aclose())

    assert result.status == "failed"
    assert len(result.source_outcomes) == 1
    assert result.source_outcomes[0].status == "failed"
    assert result.source_outcomes[0].source_id == "src_hn"
    assert result.source_outcomes[0].issue is not None
    assert result.source_outcomes[0].issue.code == "HTTPStatusError"


def test_execute_marks_hackernews_comment_request_failure_as_failed_source(tmp_path, monkeypatch):
    config = _config()
    config.sources.hackernews.source_id = "src_hn"
    config.sources.hackernews.subscription_id = "sub_hn"
    config.sources.hackernews.source_key = "hackernews:top"
    published = int(datetime.now(timezone.utc).timestamp())

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/topstories.json"):
            return httpx.Response(200, json=[1])
        if request.url.path.endswith("/item/1.json"):
            return httpx.Response(
                200,
                json={
                    "id": 1,
                    "title": "HN story",
                    "url": "https://example.com/hn-story",
                    "by": "author",
                    "time": published,
                    "score": 200,
                    "kids": [2],
                },
            )
        if request.url.path.endswith("/item/2.json"):
            return httpx.Response(503, text="comment unavailable")
        raise AssertionError(f"unexpected url: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    scraper = HackerNewsScraper(config.sources.hackernews, client)
    scraper.strict_errors = True
    orchestrator = HorizonOrchestrator(config, StorageManager(data_dir=str(tmp_path)))
    monkeypatch.setattr(
        orchestrator,
        "_service_source_specs",
        lambda _client: [("HackerNews:src_hn", scraper, config.sources.hackernews)],
    )
    _forbid_legacy_side_effects(monkeypatch, orchestrator)

    result = asyncio.run(orchestrator.execute())
    asyncio.run(client.aclose())

    assert result.status == "failed"
    assert result.source_outcomes[0].status == "failed"
    assert result.source_outcomes[0].issue is not None
    assert result.source_outcomes[0].issue.code == "HTTPStatusError"
