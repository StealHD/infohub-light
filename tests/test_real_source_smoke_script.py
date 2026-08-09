import os

from scripts.service_real_source_smoke import build_report, default_smoke_sources


def test_default_smoke_sources_include_required_public_sources(monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)

    sources = default_smoke_sources(include_flaky=False)
    by_key = {source["key"]: source for source in sources}

    assert list(by_key) == [
        "rss_github_blog",
        "hackernews_top",
        "github_openai_codex",
        "telegram_durov",
    ]
    assert by_key["rss_github_blog"]["source_type"] == "rss"
    assert by_key["rss_github_blog"]["config"]["url"] == "https://github.blog/feed/"
    assert by_key["hackernews_top"]["fetch"] is True
    assert by_key["github_openai_codex"]["config"] == {"owner": "openai", "repo": "codex"}
    assert by_key["telegram_durov"]["config"] == {"channel": "durov"}
    assert all(source["required"] is True for source in sources)
    assert all("secret_env" not in source for source in sources)


def test_default_smoke_sources_mark_reddit_flaky_and_apify_optional(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "real-token-value")

    sources = default_smoke_sources(include_flaky=True)
    by_key = {source["key"]: source for source in sources}

    assert by_key["reddit_localllama"]["required"] is False
    assert by_key["reddit_localllama"]["expected_degraded"] is True
    assert by_key["apify_x_openai"]["required"] is False
    assert by_key["apify_x_openai"]["secret_env"] == "APIFY_TOKEN"
    assert "real-token-value" not in repr(sources)


def test_build_report_fails_only_required_source_failures():
    report = build_report(
        [
            {"key": "rss_github_blog", "required": True, "source_test_status": "succeeded"},
            {"key": "telegram_durov", "required": True, "source_test_status": "failed"},
            {
                "key": "reddit_localllama",
                "required": False,
                "expected_degraded": True,
                "source_test_status": "failed",
            },
        ],
        feed_latest={"scope": "user", "snapshot_id": "snap_1", "items": [{"id": "rss:item"}]},
        source_health={"sources": [{"source": "GitHub Blog", "status": "healthy"}]},
    )

    assert report["ok"] is False
    assert report["required_failed"] == ["telegram_durov"]
    assert report["optional_degraded"] == ["reddit_localllama"]
    assert report["feed_latest"]["snapshot_id"] == "snap_1"
    assert report["source_health"]["sources"][0]["status"] == "healthy"


def test_build_report_passes_when_required_sources_and_feed_snapshot_pass():
    report = build_report(
        [
            {"key": "rss_github_blog", "required": True, "source_test_status": "succeeded"},
            {"key": "hackernews_top", "required": True, "source_test_status": "succeeded"},
            {"key": "github_openai_codex", "required": True, "source_test_status": "succeeded"},
            {"key": "telegram_durov", "required": True, "source_test_status": "succeeded"},
        ],
        feed_latest={"scope": "user", "snapshot_id": "snap_1", "items": [{"id": "hn:item"}]},
        source_health={"sources": [{"source": "Hacker News", "status": "healthy"}]},
    )

    assert report["ok"] is True
    assert report["required_failed"] == []
    assert report["optional_degraded"] == []
