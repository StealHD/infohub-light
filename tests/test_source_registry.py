import json

from src.models import Config
from src.scrapers.source_registry import build_direct_source_registry


def _make_config() -> Config:
    return Config.model_validate(
        {
            "version": "1.0",
            "ai": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "api_key_env": "OPENAI_API_KEY",
            },
            "sources": {
                "rss": [
                    {
                        "name": "Example Feed",
                        "url": "https://example.com/feed.xml",
                        "enabled": True,
                    }
                ],
                "hackernews": {"enabled": True},
            },
            "filtering": {"ai_score_threshold": 7.5, "time_window_hours": 24},
        }
    )


def test_direct_source_registry_expands_configured_rss_and_has_no_aihub():
    endpoints = build_direct_source_registry(_make_config())
    payload = json.dumps([endpoint.__dict__ for endpoint in endpoints])

    assert "https://example.com/feed.xml" in payload
    assert "api.github.com" in payload
    assert "hacker-news.firebaseio.com" in payload
    assert "aihub" not in payload.lower()
