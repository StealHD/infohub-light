"""Human-readable registry of direct source endpoints.

This module documents the public/origin endpoints Horizon uses so the
deployment stays independent from aggregator services such as AIHub-like hubs.
It intentionally contains no third-party private or reverse-engineered API.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Config


@dataclass(frozen=True)
class DirectSourceEndpoint:
    """One direct source endpoint pattern used by a scraper."""

    source: str
    adapter: str
    endpoint: str
    auth: str
    notes: str


def build_direct_source_registry(config: Config | None = None) -> list[DirectSourceEndpoint]:
    """Return direct source endpoint patterns, optionally expanded from config."""
    endpoints: list[DirectSourceEndpoint] = [
        DirectSourceEndpoint(
            source="rss",
            adapter="src.scrapers.rss.RSSScraper",
            endpoint="<configured RSS/Atom feed URL>",
            auth="none, unless the configured URL embeds ${ENV_VAR}",
            notes="Fetches the original RSS/Atom feed directly with feedparser.",
        ),
        DirectSourceEndpoint(
            source="github",
            adapter="src.scrapers.github.GitHubScraper",
            endpoint="https://api.github.com/users/{username}/events/public",
            auth="optional GITHUB_TOKEN",
            notes="Tracks public user activity events from GitHub REST API.",
        ),
        DirectSourceEndpoint(
            source="github",
            adapter="src.scrapers.github.GitHubScraper",
            endpoint="https://api.github.com/repos/{owner}/{repo}/releases",
            auth="optional GITHUB_TOKEN",
            notes="Tracks repository releases from GitHub REST API.",
        ),
        DirectSourceEndpoint(
            source="hackernews",
            adapter="src.scrapers.hackernews.HackerNewsScraper",
            endpoint="https://hacker-news.firebaseio.com/v0/topstories.json and /item/{id}.json",
            auth="none",
            notes="Uses Hacker News Firebase API and fetches story/comment details.",
        ),
        DirectSourceEndpoint(
            source="reddit",
            adapter="src.scrapers.reddit.RedditScraper",
            endpoint="https://www.reddit.com/r/{subreddit}/{sort}.json and /comments/{post_id}.json",
            auth="none",
            notes="Uses Reddit public JSON endpoints with a descriptive User-Agent.",
        ),
        DirectSourceEndpoint(
            source="telegram",
            adapter="src.scrapers.telegram.TelegramScraper",
            endpoint="https://t.me/s/{channel}",
            auth="none",
            notes="Reads public channel web previews only.",
        ),
        DirectSourceEndpoint(
            source="ossinsight",
            adapter="src.scrapers.ossinsight.OSSInsightScraper",
            endpoint="https://api.ossinsight.io/explorer/...",
            auth="none",
            notes="Uses OSS Insight public API for trending GitHub repositories.",
        ),
        DirectSourceEndpoint(
            source="openbb",
            adapter="src.scrapers.openbb.OpenBBScraper",
            endpoint="OpenBB SDK provider endpoints",
            auth="provider-specific env/settings resolved by OpenBB",
            notes="Optional financial source; skipped if OpenBB extra is not installed.",
        ),
        DirectSourceEndpoint(
            source="twitter",
            adapter="src.scrapers.twitter.TwitterScraper",
            endpoint="Apify actor altimis/scweet",
            auth="APIFY_TOKEN",
            notes="Optional only. X/Twitter has no stable public origin API here, so it is disabled by default.",
        ),
    ]

    if config is None:
        return endpoints

    expanded: list[DirectSourceEndpoint] = []
    for feed in config.sources.rss:
        if not feed.enabled:
            continue
        expanded.append(
            DirectSourceEndpoint(
                source="rss",
                adapter="src.scrapers.rss.RSSScraper",
                endpoint=str(feed.url),
                auth="none, unless URL contains expanded private env vars",
                notes=f"Configured feed: {feed.name}",
            )
        )

    return expanded + [endpoint for endpoint in endpoints if endpoint.source != "rss"]
