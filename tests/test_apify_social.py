import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from src.models import ApifySocialConfig, ApifySocialSubscriptionConfig, SourceType
from src.scrapers.apify_client import ApifyClient
from src.scrapers.apify_social import ApifySocialScraper


def _run_resp(run_id="run1", dataset_id="ds1"):
    return {"data": {"id": run_id, "defaultDatasetId": dataset_id}}


def _status_resp(status="SUCCEEDED"):
    return {"data": {"status": status}}


def _social_config(*subscriptions, **kwargs):
    defaults = {
        "enabled": True,
        "token_env": "APIFY_TOKEN",
        "timeout_seconds": 5,
        "actors": {
            "x": {"actor_id": "altimis~scweet"},
            "instagram": {"actor_id": "apify/instagram-api-scraper"},
            "facebook": {"actor_id": "whoareyouanas/facebook-group-scraper"},
            "telegram": {"actor_id": "thescrapelab/apify-telegram-scraper"},
        },
        "subscriptions": list(subscriptions),
    }
    defaults.update(kwargs)
    return ApifySocialConfig(**defaults)


def _sub(platform, kind, target, **kwargs):
    defaults = {
        "platform": platform,
        "kind": kind,
        "target": target,
        "fetch_limit": 3,
        "enabled": True,
        "tags": ["行业动态"],
    }
    defaults.update(kwargs)
    return ApifySocialSubscriptionConfig(**defaults)


def test_apify_client_runs_actor_with_bearer_token_and_fetches_dataset():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer test-token"
        if request.method == "POST" and request.url.path == "/v2/acts/apify~instagram-api-scraper/runs":
            assert json.loads(request.content) == {"directUrls": ["https://instagram.com/openai"]}
            return httpx.Response(200, json=_run_resp())
        if request.method == "GET" and request.url.path == "/v2/actor-runs/run1":
            return httpx.Response(200, json=_status_resp())
        if request.method == "GET" and request.url.path == "/v2/datasets/ds1/items":
            assert request.url.params["clean"] == "true"
            return httpx.Response(200, json=[{"id": "item1"}])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(
        ApifyClient(
            token="test-token",
            http_client=client,
            poll_interval=0,
            timeout_seconds=5,
            retry_base_delay=0,
        ).run_actor("apify/instagram-api-scraper", {"directUrls": ["https://instagram.com/openai"]})
    )
    asyncio.run(client.aclose())

    assert result == [{"id": "item1"}]
    assert [request.method for request in requests] == ["POST", "GET", "GET"]


def test_apify_client_retries_rate_limit_before_succeeding():
    attempts = {"post": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            attempts["post"] += 1
            if attempts["post"] == 1:
                return httpx.Response(429, json={"error": {"message": "rate limit"}})
            return httpx.Response(200, json=_run_resp())
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp())
        if "/datasets/" in request.url.path:
            return httpx.Response(200, json=[])
        raise AssertionError(f"Unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(
        ApifyClient(
            token="test-token",
            http_client=client,
            poll_interval=0,
            timeout_seconds=5,
            retry_base_delay=0,
        ).run_actor("actor/id", {})
    )
    asyncio.run(client.aclose())

    assert result == []
    assert attempts["post"] == 2


def test_apify_client_rotates_to_next_token_on_quota_failure():
    seen_auth = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers["Authorization"])
        if request.method == "POST" and request.headers["Authorization"] == "Bearer token-one":
            return httpx.Response(
                402,
                json={"error": {"message": "monthly usage quota exceeded"}},
            )
        if request.method == "POST":
            return httpx.Response(200, json=_run_resp())
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp())
        if "/datasets/" in request.url.path:
            return httpx.Response(200, json=[{"id": "ok"}])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(
        ApifyClient(
            tokens=[("APIFY_TOKEN", "token-one"), ("APIFY_TOKEN_2", "token-two")],
            http_client=client,
            poll_interval=0,
            timeout_seconds=5,
            retry_base_delay=0,
        ).run_actor("actor/id", {})
    )
    asyncio.run(client.aclose())

    assert result == [{"id": "ok"}]
    assert seen_auth == [
        "Bearer token-one",
        "Bearer token-two",
        "Bearer token-two",
        "Bearer token-two",
    ]


def test_apify_client_reports_all_token_failures():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"error": {"message": "insufficient account credit"}},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ValueError, match="APIFY_TOKEN.*APIFY_TOKEN_2"):
            asyncio.run(
                ApifyClient(
                    tokens=[("APIFY_TOKEN", "token-one"), ("APIFY_TOKEN_2", "token-two")],
                    http_client=client,
                    poll_interval=0,
                    timeout_seconds=5,
                    retry_base_delay=0,
                ).run_actor("actor/id", {})
            )
    finally:
        asyncio.run(client.aclose())


def test_apify_social_scraper_builds_platform_inputs_and_maps_items(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    seen_inputs = []

    now_iso = datetime.now(timezone.utc).isoformat()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen_inputs.append((request.url.path, json.loads(request.content)))
            dataset_id = f"ds{len(seen_inputs)}"
            return httpx.Response(200, json=_run_resp(f"run{len(seen_inputs)}", dataset_id))
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp())
        if request.url.path.endswith("/ds1/items"):
            return httpx.Response(200, json=[{
                "id": "tweet-42",
                "created_at": now_iso,
                "full_text": "OpenAI shipped a new coding agent workflow.",
                "user": {"screen_name": "OpenAI", "name": "OpenAI"},
                "favorite_count": 12,
                "reply_count": 3,
                "retweet_count": 4,
            }])
        if request.url.path.endswith("/ds2/items"):
            return httpx.Response(200, json=[{
                "id": "ig1",
                "shortCode": "ABC123",
                "url": "https://www.instagram.com/p/ABC123/",
                "caption": "New AI product demo",
                "timestamp": now_iso,
                "ownerUsername": "openai",
            }])
        if request.url.path.endswith("/ds3/items"):
            return httpx.Response(200, json=[{
                "post_url": "https://www.facebook.com/openai/posts/123",
                "text": "OpenAI page update",
                "date": now_iso,
                "author": "OpenAI",
            }])
        if request.url.path.endswith("/ds4/items"):
            return httpx.Response(200, json=[{
                "Channel_Handle": "zaihuapd",
                "Id": 99,
                "Date": now_iso,
                "Url": "https://t.me/zaihuapd/99",
                "Body": "AI infra update",
                "LinkPreview_Url": "https://example.com/ai",
            }])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    config = _social_config(
        _sub("x", "profile", "@OpenAI"),
        _sub("instagram", "profile", "openai"),
        _sub("facebook", "page", "https://www.facebook.com/openai"),
        _sub("telegram", "channel", "https://t.me/zaihuapd"),
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    items = asyncio.run(ApifySocialScraper(config, client).fetch(since))
    asyncio.run(client.aclose())

    assert [path for path, _ in seen_inputs] == [
        "/v2/acts/altimis~scweet/runs",
        "/v2/acts/apify~instagram-api-scraper/runs",
        "/v2/acts/whoareyouanas~facebook-group-scraper/runs",
        "/v2/acts/thescrapelab~apify-telegram-scraper/runs",
    ]
    assert seen_inputs[0][1]["source_mode"] == "profiles"
    assert seen_inputs[0][1]["profile_urls"] == ["OpenAI"]
    assert seen_inputs[1][1]["directUrls"] == ["https://www.instagram.com/openai/"]
    assert seen_inputs[2][1]["startUrls"] == [{"url": "https://www.facebook.com/openai"}]
    assert seen_inputs[3][1]["channels"] == [{"channelName": "zaihuapd", "limit": 3}]

    assert [item.source_type for item in items] == [
        SourceType.TWITTER,
        SourceType.INSTAGRAM,
        SourceType.FACEBOOK,
        SourceType.TELEGRAM,
    ]
    assert [item.id for item in items] == [
        "twitter:tweet:42",
        "instagram:post:ABC123",
        "facebook:post:a9acb383d6a8",
        "telegram:zaihuapd:99",
    ]
    assert items[0].metadata["apify_platform"] == "x"
    assert items[1].metadata["tags"] == ["行业动态"]
    assert str(items[3].url) == "https://example.com/ai"


def test_apify_social_scraper_reads_token_envs_and_maps_instagram_media(monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    monkeypatch.setenv("APIFY_TOKEN_2", "backup-token")
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    now_iso = datetime.now(timezone.utc).isoformat()
    seen_auth = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers["Authorization"])
        if request.method == "POST":
            return httpx.Response(200, json=_run_resp())
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp())
        if "/datasets/" in request.url.path:
            return httpx.Response(200, json=[{
                "id": "ig1",
                "shortCode": "TSUCHA1",
                "url": "https://www.instagram.com/p/TSUCHA1/",
                "caption": "latest photo",
                "timestamp": now_iso,
                "ownerUsername": "tsucha_ri",
                "displayUrl": "https://cdn.example.com/main.jpg",
                "childPosts": [
                    {"displayUrl": "https://cdn.example.com/child.jpg"},
                ],
            }])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    config = _social_config(
        _sub("instagram", "profile", "tsucha_ri"),
        token_envs=["APIFY_TOKEN", "APIFY_TOKEN_2"],
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    items = asyncio.run(ApifySocialScraper(config, client).fetch(since))
    asyncio.run(client.aclose())

    assert items[0].metadata["image_url"] == "https://cdn.example.com/main.jpg"
    assert items[0].metadata["media_urls"] == [
        "https://cdn.example.com/main.jpg",
        "https://cdn.example.com/child.jpg",
    ]
    assert set(seen_auth) == {"Bearer backup-token"}


def test_apify_social_scraper_uses_subscription_token_env(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "primary-token")
    monkeypatch.setenv("APIFY_TOKEN_2", "source-token")
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    now_iso = datetime.now(timezone.utc).isoformat()
    seen_auth = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers["Authorization"])
        if request.method == "POST":
            return httpx.Response(200, json=_run_resp())
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp())
        if "/datasets/" in request.url.path:
            return httpx.Response(200, json=[{
                "id": "ig1",
                "shortCode": "TSUCHA1",
                "url": "https://www.instagram.com/p/TSUCHA1/",
                "caption": "latest photo",
                "timestamp": now_iso,
                "ownerUsername": "tsucha_ri",
            }])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    config = _social_config(
        _sub("instagram", "profile", "tsucha_ri", token_env="APIFY_TOKEN_2"),
        token_envs=["APIFY_TOKEN", "APIFY_TOKEN_2"],
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    items = asyncio.run(ApifySocialScraper(config, client).fetch(since))
    asyncio.run(client.aclose())

    assert [item.id for item in items] == ["instagram:post:TSUCHA1"]
    assert set(seen_auth) == {"Bearer source-token"}


def test_apify_social_scraper_keeps_latest_profile_item_when_window_has_no_new_posts(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    old_iso = (since - timedelta(days=10)).isoformat()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=_run_resp())
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp())
        if "/datasets/" in request.url.path:
            return httpx.Response(200, json=[{
                "id": "ig-old",
                "shortCode": "OLDTSUCHA",
                "url": "https://www.instagram.com/p/OLDTSUCHA/",
                "caption": "older low-frequency profile post",
                "timestamp": old_iso,
                "ownerUsername": "tsucha_ri",
                "displayUrl": "https://cdn.example.com/old.jpg",
            }])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    config = _social_config(_sub("instagram", "profile", "tsucha_ri", fetch_limit=1))
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    items = asyncio.run(ApifySocialScraper(config, client).fetch(since))
    asyncio.run(client.aclose())

    assert [item.id for item in items] == ["instagram:post:OLDTSUCHA"]
    assert items[0].metadata["tags"] == ["行业动态"]
    assert items[0].metadata["image_url"] == "https://cdn.example.com/old.jpg"


def test_apify_social_scraper_builds_keyword_and_hashtag_inputs(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            captured.append(json.loads(request.content))
            return httpx.Response(200, json=_run_resp(f"run{len(captured)}", f"ds{len(captured)}"))
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp())
        if "/datasets/" in request.url.path:
            return httpx.Response(200, json=[])
        raise AssertionError(f"Unexpected request: {request.url}")

    config = _social_config(
        _sub("x", "keyword", "Claude Code MCP"),
        _sub("instagram", "hashtag", "#aiagents"),
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    asyncio.run(ApifySocialScraper(config, client).fetch(datetime.now(timezone.utc) - timedelta(hours=1)))
    asyncio.run(client.aclose())

    assert captured[0]["source_mode"] == "search"
    assert captured[0]["search_query"] == "Claude Code MCP"
    assert captured[1]["directUrls"] == ["https://www.instagram.com/explore/tags/aiagents/"]


def test_apify_social_scraper_skips_when_token_missing(monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    items = asyncio.run(
        ApifySocialScraper(
            _social_config(_sub("x", "profile", "OpenAI")),
            client,
        ).fetch(datetime.now(timezone.utc) - timedelta(hours=1))
    )
    asyncio.run(client.aclose())

    assert items == []
