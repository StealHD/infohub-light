import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from src.models import RedditConfig, RedditSubredditConfig
from src.scrapers.reddit import REDDIT_HEADERS, RedditScraper


def _make_config(fetch_comments: int = 1) -> RedditConfig:
    return RedditConfig(
        enabled=True,
        subreddits=[
            RedditSubredditConfig(
                subreddit="LocalLLaMA",
                enabled=True,
                sort="hot",
                fetch_limit=1,
                min_score=1,
                source_id="src_reddit",
                subscription_id="sub_reddit",
                source_key="reddit_subreddit:localllama",
                analysis_mode="personal_only",
            )
        ],
        users=[],
        fetch_comments=fetch_comments,
    )


def _listing_payload() -> dict:
    now = datetime.now(timezone.utc)
    return {
        "data": {
            "children": [
                {
                    "kind": "t3",
                    "data": {
                        "id": "abc123",
                        "title": "Test post",
                        "is_self": True,
                        "subreddit": "LocalLLaMA",
                        "permalink": "/r/LocalLLaMA/comments/abc123/test_post/",
                        "author": "tester",
                        "created_utc": now.timestamp(),
                        "score": 42,
                        "upvote_ratio": 0.97,
                        "num_comments": 5,
                        "selftext": "post body",
                    },
                }
            ]
        }
    }


def test_reddit_fetch_uses_browser_like_headers():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": {"children": []}})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    scraper = RedditScraper(_make_config(fetch_comments=0), client)

    asyncio.run(scraper.fetch(datetime.now(timezone.utc) - timedelta(hours=1)))
    asyncio.run(client.aclose())

    assert len(requests) == 1
    assert requests[0].headers["user-agent"] == REDDIT_HEADERS["User-Agent"]
    assert requests[0].headers["accept-language"] == REDDIT_HEADERS["Accept-Language"]
    assert requests[0].headers["referer"] == REDDIT_HEADERS["Referer"]


def test_reddit_comment_403_degrades_to_post_without_comments():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/hot.json"):
            return httpx.Response(200, json=_listing_payload())
        if "/comments/" in request.url.path:
            return httpx.Response(403, text="blocked")
        raise AssertionError(f"unexpected url: {request.url}")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    scraper = RedditScraper(_make_config(fetch_comments=3), client)

    items = asyncio.run(scraper.fetch(datetime.now(timezone.utc) - timedelta(hours=1)))
    asyncio.run(client.aclose())

    assert len(items) == 1
    assert items[0].title == "Test post"
    assert "Top Comments" not in (items[0].content or "")
    assert items[0].metadata["source_id"] == "src_reddit"
    assert items[0].metadata["subscription_id"] == "sub_reddit"
    assert items[0].metadata["analysis_mode"] == "personal_only"
    assert items[0].metadata["show_in_personal_feed"] is True


def test_reddit_listing_403_falls_back_to_subreddit_rss():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/hot.json"):
            return httpx.Response(403, text="blocked")
        if request.url.path.endswith("/hot/.rss"):
            return httpx.Response(
                200,
                text="""
                <?xml version="1.0" encoding="UTF-8"?>
                <feed xmlns="http://www.w3.org/2005/Atom">
                  <entry>
                    <id>t3_rss123</id>
                    <title>RSS fallback post</title>
                    <author><name>rss_author</name></author>
                    <link href="https://www.reddit.com/r/LocalLLaMA/comments/rss123/test/" />
                    <updated>2030-01-01T00:00:00+00:00</updated>
                    <summary type="html">&lt;p&gt;RSS body&lt;/p&gt;</summary>
                  </entry>
                </feed>
                """,
            )
        raise AssertionError(f"unexpected url: {request.url}")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    scraper = RedditScraper(_make_config(fetch_comments=3), client)

    items = asyncio.run(scraper.fetch(datetime(2029, 12, 31, tzinfo=timezone.utc)))
    asyncio.run(client.aclose())

    assert [request.url.path for request in requests] == [
        "/r/LocalLLaMA/hot.json",
        "/r/LocalLLaMA/hot/.rss",
    ]
    assert len(items) == 1
    assert items[0].title == "RSS fallback post"
    assert items[0].content == "RSS body"
    assert items[0].author == "rss_author"
    assert items[0].metadata["subreddit"] == "LocalLLaMA"
    assert items[0].metadata["fallback"] == "rss"


def test_reddit_strict_mode_propagates_listing_failure():
    transport = httpx.MockTransport(lambda _request: httpx.Response(500, text="down"))
    client = httpx.AsyncClient(transport=transport)
    scraper = RedditScraper(_make_config(fetch_comments=0), client)
    scraper.strict_errors = True

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(scraper.fetch(datetime.now(timezone.utc) - timedelta(hours=1)))
    asyncio.run(client.aclose())


def test_reddit_strict_mode_propagates_failed_rss_fallback():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/hot.json"):
            return httpx.Response(403, text="listing blocked")
        if request.url.path.endswith("/hot/.rss"):
            return httpx.Response(503, text="fallback unavailable")
        raise AssertionError(f"unexpected url: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    scraper = RedditScraper(_make_config(fetch_comments=0), client)
    scraper.strict_errors = True

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(scraper.fetch(datetime.now(timezone.utc) - timedelta(hours=1)))
    asyncio.run(client.aclose())
