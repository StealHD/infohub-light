import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from src.models import (
    ApifySocialConfig,
    ApifySocialSubscriptionConfig,
    GitHubSourceConfig,
    HackerNewsConfig,
    RedditConfig,
    RedditSubredditConfig,
    RedditUserConfig,
    RSSSourceConfig,
    TelegramChannelConfig,
    TelegramConfig,
)
from src.scrapers.apify_social import ApifySocialScraper
from src.scrapers.github import GitHubScraper
from src.scrapers.hackernews import HackerNewsScraper
from src.scrapers.reddit import RedditScraper
from src.scrapers.rss import RSSScraper
from src.scrapers.telegram import TelegramScraper
from src.services.content_presentation import build_content_presentation


NOW = datetime(2026, 7, 14, 9, 0, tzinfo=timezone.utc)
SINCE = NOW - timedelta(days=1)


def _service_fields(source_type: str, name: str) -> dict:
    return {
        "source_id": f"src-{source_type}",
        "source_display_name": name,
        "catalog_source_type": source_type,
    }


def test_all_catalog_adapters_project_to_one_presentation_contract() -> None:
    rss_response = MagicMock()
    rss_response.text = """<rss version='2.0'><channel><item><guid>rss-1</guid>
      <title>RSS title</title><link>https://example.com/rss</link>
      <pubDate>Tue, 14 Jul 2026 09:00:00 GMT</pubDate>
      <description><![CDATA[<p>RSS summary</p>]]></description><author>RSS Author</author>
    </item></channel></rss>"""
    rss_response.raise_for_status.return_value = None
    rss_client = AsyncMock()
    rss_client.get.return_value = rss_response
    rss_item = asyncio.run(
        RSSScraper(
            [RSSSourceConfig(name="RSS", url="https://example.com/feed.xml", **_service_fields("rss", "RSS Feed"))],
            rss_client,
        ).fetch(SINCE)
    )[0]

    github_client = AsyncMock()
    release_response = MagicMock()
    release_response.json.return_value = [{
        "id": 1,
        "tag_name": "v1.0",
        "html_url": "https://github.com/openai/codex/releases/tag/v1.0",
        "body": "Release notes",
        "author": {"login": "openai"},
        "published_at": NOW.isoformat().replace("+00:00", "Z"),
        "prerelease": False,
    }]
    release_response.raise_for_status.return_value = None
    github_client.get.return_value = release_response
    release_config = GitHubSourceConfig(
        type="repo_releases", owner="openai", repo="codex",
        **_service_fields("github_release", "Codex Releases"),
    )
    release_item = asyncio.run(GitHubScraper([release_config], github_client).fetch(SINCE))[0]
    user_config = GitHubSourceConfig(
        type="user_events", username="torvalds",
        **_service_fields("github_user", "torvalds activity"),
    )
    event_item = GitHubScraper([user_config], github_client)._parse_event(
        {
            "id": "event-1",
            "type": "PushEvent",
            "created_at": NOW.isoformat().replace("+00:00", "Z"),
            "repo": {"name": "torvalds/linux"},
            "payload": {"commits": [{"message": "Merge update"}]},
        },
        user_config,
    )
    assert event_item is not None

    hn_config = HackerNewsConfig(
        fetch_top_stories=1,
        min_score=0,
        **_service_fields("hackernews", "Hacker News"),
    )
    hn_item = HackerNewsScraper(hn_config, AsyncMock())._parse_story(
        {"id": 1, "title": "HN title", "url": "https://example.com/hn", "by": "pg", "time": int(NOW.timestamp()), "score": 55, "descendants": 6},
        [{"by": "commenter", "text": "Useful discussion"}],
    )

    subreddit = RedditSubredditConfig(
        subreddit="LocalLLaMA",
        **_service_fields("reddit_subreddit", "r/LocalLLaMA"),
    )
    reddit_user = RedditUserConfig(
        username="spez",
        **_service_fields("reddit_user", "u/spez"),
    )
    reddit = RedditScraper(RedditConfig(subreddits=[subreddit], users=[reddit_user]), AsyncMock())
    reddit_post = {
        "id": "reddit-1", "title": "Reddit title", "is_self": False,
        "subreddit": "LocalLLaMA", "permalink": "/r/LocalLLaMA/comments/1",
        "url": "https://example.com/reddit", "author": "author",
        "created_utc": NOW.timestamp(), "score": 21, "num_comments": 4,
        "upvote_ratio": 0.9,
    }
    subreddit_item = reddit._parse_post(reddit_post, [], "subreddit", subreddit)
    user_item = reddit._parse_post({**reddit_post, "id": "reddit-2"}, [], "user", reddit_user)
    assert subreddit_item is not None and user_item is not None

    telegram_config = TelegramChannelConfig(
        channel="durov",
        **_service_fields("telegram_channel", "Telegram · durov"),
    )
    telegram_html = f"""<div class='tgme_widget_message' data-post='durov/1'>
      <time datetime='{NOW.isoformat()}'></time>
      <div class='tgme_widget_message_text'>Telegram message <a href='https://example.com/tg'>link</a></div>
    </div>"""
    telegram_item = TelegramScraper(
        TelegramConfig(channels=[telegram_config]), AsyncMock()
    )._parse_channel_html(telegram_html, telegram_config, SINCE)[0]

    social_config = ApifySocialConfig(enabled=True, subscriptions=[])
    social = ApifySocialScraper(social_config, AsyncMock())
    x_sub = ApifySocialSubscriptionConfig(
        platform="x", kind="profile", target="thsottiaux",
        **_service_fields("apify_social", "X · @thsottiaux"),
    )
    instagram_sub = ApifySocialSubscriptionConfig(
        platform="instagram", kind="profile", target="openai",
        **_service_fields("apify_social", "Instagram · OpenAI"),
    )
    facebook_sub = ApifySocialSubscriptionConfig(
        platform="facebook", kind="page", target="openai",
        **_service_fields("apify_social", "Facebook · OpenAI"),
    )
    apify_telegram_sub = ApifySocialSubscriptionConfig(
        platform="telegram", kind="channel", target="durov",
        **_service_fields("apify_social", "Apify Telegram · durov"),
    )
    x_item = social._parse_x({"id": "tweet-1", "created_at": NOW.isoformat(), "full_text": "X post", "user": {"screen_name": "thsottiaux"}}, x_sub, SINCE)
    instagram_item = social._parse_instagram({"shortCode": "IG1", "timestamp": NOW.isoformat(), "caption": "IG caption", "ownerUsername": "openai"}, instagram_sub, SINCE)
    facebook_item = social._parse_facebook({"post_url": "https://facebook.com/openai/posts/1", "date": NOW.isoformat(), "text": "FB post", "author": "OpenAI"}, facebook_sub, SINCE)
    apify_telegram_item = social._parse_telegram({"Id": 2, "Date": NOW.isoformat(), "Url": "https://t.me/durov/2", "Body": "Apify TG message", "Channel_Handle": "durov"}, apify_telegram_sub, SINCE)
    assert all([x_item, instagram_item, facebook_item, apify_telegram_item])

    cases = [
        (rss_item, "rss", "feed_summary", "person"),
        (release_item, "github_release", "release_notes", "account"),
        (event_item, "github_user", "event_description", "account"),
        (subreddit_item, "reddit_subreddit", "discussion", "person"),
        (user_item, "reddit_user", "discussion", "person"),
        (hn_item, "hackernews", "discussion", "person"),
        (telegram_item, "telegram_channel", "message", "channel"),
        (x_item, "apify_social", "post_body", "account"),
        (instagram_item, "apify_social", "caption", "account"),
        (facebook_item, "apify_social", "post_body", "account"),
        (apify_telegram_item, "apify_social", "message", "channel"),
    ]
    for item, catalog_type, content_kind, author_kind in cases:
        presentation = build_content_presentation(item)
        assert presentation["version"] == 1
        assert presentation["source"]["catalog_type"] == catalog_type
        assert presentation["content"]["content_kind"] == content_kind
        assert presentation["author"]["kind"] == author_kind
        assert presentation["content"]["title"]
        assert presentation["author"]["name"]
        assert presentation["timing"]["published_at"]
        assert presentation["links"]["canonical_url"].startswith("http")
        assert "reason" not in presentation["analysis"]
