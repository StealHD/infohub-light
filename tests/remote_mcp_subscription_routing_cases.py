"""Shared source-routing cases for service and real MCP protocol tests."""

CREATE_CASES = {
    "rss": {"url": "https://example.com/feed.xml"},
    "website": {"url": "https://example.com/feed.xml"},
    "github": {"repository": "openclaw/openclaw"},
    "github_user": {"username": "openai"},
    "reddit": {"subreddit": "LocalLLaMA"},
    "reddit_user": {"username": "spez"},
    "telegram": {"channel": "durov"},
    "hackernews": {},
    "bilibili": {
        "site": "bilibili",
        "route_key": "user_video",
        "params": {"uid": "39627524"},
    },
    "twitter": {"handle": "openai"},
    "instagram": {"handle": "instagram"},
    "youtube": {
        "url": (
            "https://www.youtube.com/feeds/videos.xml?"
            "channel_id=UC_x5XG1OV2P6uZZ5FSM9Ttw"
        )
    },
}

DIRECT_CONFIG_TYPES = tuple(
    source_type for source_type in CREATE_CASES if source_type != "youtube"
)
