from urllib.parse import quote

import pytest

from src.services.source_type_registry import (
    SourceConfigError,
    get_source_setup_guide,
    list_source_types,
    normalize_source_setup_input,
    source_key,
    validate_normalized_source_setup,
    validate_source_config,
)


SOURCE_TYPES = {
    "rss",
    "bilibili",
    "telegram",
    "github",
    "github_user",
    "reddit",
    "reddit_user",
    "twitter",
    "instagram",
    "website",
    "youtube",
    "hackernews",
    "apify",
}

CREDENTIAL_ERROR = "credentials are not accepted; configure secrets in Web"
UNSUPPORTED_SOURCE_TYPE_ERROR = "unsupported source type"
SOURCE_REQUIRES_WEB_SETUP_ERROR = "source_requires_web_setup"
YOUTUBE_CHANNEL_ID = "UCabcdefghijklmnopqrstuv"
YOUTUBE_PLAYLIST_IDS = (
    "PLabcdefghijklmnopqrstuvwxyz012345",
    "UUabcdefghijklmnopqrstuv",
    "LLabcdefghijklmnopqrstuv",
    "FLabcdefghijklmnopqrstuv",
)


def test_setup_guide_is_complete_bilingual_and_secret_safe():
    zh = get_source_setup_guide(None, "zh-CN")
    en = get_source_setup_guide(None, "en")

    assert {item["type"] for item in zh["source_types"]} == SOURCE_TYPES
    assert {item["type"] for item in en["source_types"]} == SOURCE_TYPES
    for locale, payload in (("zh-CN", zh), ("en", en)):
        assert payload["locale"] == locale
        for summary in payload["source_types"]:
            assert "required_fields" in summary
            detail = get_source_setup_guide(summary["type"], locale)["source_type"]
            assert set(detail) >= {
                "type",
                "label",
                "description",
                "self_service",
                "requires_web_setup",
                "required_fields",
                "fields",
            }
            for field in detail["fields"]:
                assert set(field) >= {
                    "name",
                    "label",
                    "required",
                    "input_type",
                    "default",
                    "options",
                    "min",
                    "max",
                    "help",
                    "accepted_formats",
                    "examples",
                    "how_to_find",
                }

    serialized = repr((zh, en)).lower()
    assert "secret_env" not in serialized
    assert "token_env" not in serialized
    assert "sk-" not in serialized


def test_setup_guide_summaries_include_safe_minimum_required_fields():
    summaries = {
        item["type"]: item["required_fields"]
        for item in get_source_setup_guide(None, "en")["source_types"]
    }

    assert summaries == {
        "rss": ["url"],
        "bilibili": ["site", "route_key", "params"],
        "telegram": ["channel"],
        "github": ["repository"],
        "github_user": ["username"],
        "reddit": ["subreddit"],
        "reddit_user": ["username"],
        "twitter": ["handle"],
        "instagram": ["handle"],
        "website": ["url"],
        "youtube": ["url"],
        "hackernews": [],
        "apify": ["platform", "kind", "target"],
    }


def test_agent_rss_setup_preserves_the_configured_fetch_limit():
    normalized = normalize_source_setup_input(
        "rss",
        {"url": "https://example.com/feed.xml", "fetch_limit": 3},
    )

    assert normalized["config"]["fetch_limit"] == 3
    assert validate_normalized_source_setup(
        "rss", "rss", normalized["config"]
    ) == normalized


def test_bilibili_setup_guide_exposes_semantic_route_without_service_url():
    zh = get_source_setup_guide("bilibili", "zh-CN")["source_type"]
    en = get_source_setup_guide("bilibili", "en")["source_type"]

    assert zh["required_fields"] == ["site", "route_key", "params"]
    assert en["required_fields"] == ["site", "route_key", "params"]
    assert {field["name"] for field in zh["fields"]} == {
        "site",
        "route_key",
        "params",
        "keep_latest_item",
    }
    assert "RSSHub Base URL" in repr((zh, en))
    assert "search_bilibili_users" in repr((zh, en))
    assert "http://rsshub" not in repr((zh, en))


def test_youtube_setup_guide_routes_names_to_bounded_agent_resolution():
    guide = get_source_setup_guide("youtube", "en")["source_type"]

    assert guide["resolution"] == {
        "supported": True,
        "strategy": "agent_web",
        "official_hosts": ["www.youtube.com"],
        "locator_kinds": [
            "handle",
            "channel_url",
            "channel_id",
            "channel_feed",
        ],
        "max_candidates": 5,
    }
    assert {field["name"] for field in guide["fields"]} == {
        "url",
        "keep_latest_item",
    }
    assert "resolve_source" in repr(guide)


def test_agent_setup_contract_is_distinct_from_the_rest_catalog_projection():
    guide_types = {
        item["type"] for item in get_source_setup_guide(None, "en")["source_types"]
    }
    rest_types = {item["type"] for item in list_source_types()}

    assert guide_types == SOURCE_TYPES
    assert rest_types == {
        "rss",
        "github_release",
        "github_user",
        "reddit_subreddit",
        "reddit_user",
        "telegram_channel",
        "apify_social",
        "hackernews",
    }


def test_agent_normalization_maps_public_types_to_catalog_types():
    bilibili = normalize_source_setup_input(
        "bilibili",
        {
            "site": "bilibili",
            "route_key": "user_video",
            "params": {"uid": "039627524"},
        },
    )
    github = normalize_source_setup_input(
        "github", {"repository": "https://github.com/openai/codex"}
    )
    reddit = normalize_source_setup_input(
        "reddit", {"subreddit": "https://reddit.com/r/LocalLLaMA/"}
    )
    telegram = normalize_source_setup_input(
        "telegram", {"channel": "https://t.me/durov"}
    )
    twitter = normalize_source_setup_input("twitter", {"handle": "@openai"})
    website = normalize_source_setup_input(
        "website", {"url": "https://example.com/feed.xml"}
    )
    youtube = normalize_source_setup_input(
        "youtube",
        {"url": f"https://www.youtube.com/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}"},
    )
    apify = normalize_source_setup_input(
        "apify", {"platform": "x", "kind": "profile", "target": "openai"}
    )

    assert github == {
        "catalog_source_type": "github_release",
        "config": {
            "enabled": True,
            "owner": "openai",
            "repo": "codex",
            "type": "repo_releases",
        },
        "policy": {
            "resolution_mode": "create_or_existing",
            "self_service": True,
            "requires_web_setup": False,
        },
    }
    assert bilibili == {
        "catalog_source_type": "rss",
        "config": {
            "enabled": True,
            "provider": "rsshub",
            "site": "bilibili",
            "route_key": "user_video",
            "params": {"uid": "39627524"},
            "url": "https://space.bilibili.com/39627524",
            "name": "https://space.bilibili.com/39627524",
            "keep_latest_item": False,
        },
        "policy": {
            "resolution_mode": "create_or_existing",
            "self_service": True,
            "requires_web_setup": False,
        },
    }
    assert reddit["catalog_source_type"] == "reddit_subreddit"
    assert reddit["config"]["subreddit"] == "LocalLLaMA"
    assert telegram["catalog_source_type"] == "telegram_channel"
    assert telegram["config"]["channel"] == "durov"
    assert twitter == {
        "catalog_source_type": "apify_social",
        "config": {
            "platform": "x",
            "kind": "profile",
            "target": "openai",
            "enabled": True,
            "fetch_limit": 3,
            "analysis_mode": "full",
        },
        "policy": {
            "resolution_mode": "create_or_existing",
            "self_service": True,
            "requires_web_setup": False,
        },
    }
    assert website["catalog_source_type"] == "rss"
    assert youtube["catalog_source_type"] == "rss"
    assert youtube["config"]["keep_latest_item"] is True
    assert apify["lookup_identity"]["catalog_source_type"] == "apify_social"


@pytest.mark.parametrize(
    ("source_type", "config"),
    [
        ("rss", {"url": "https://example.com/feed?access_token=never-store-this"}),
        ("telegram", {"channel": "https://t.me/durov?api_key=never-store-this"}),
        ("github", {"repository": "https://github.com/openai/codex?auth=never-store-this"}),
        ("reddit", {"subreddit": "https://reddit.com/r/LocalLLaMA?token=never-store-this"}),
        ("twitter", {"handle": "https://x.com/openai?signature=never-store-this"}),
        ("website", {"url": "https://example.com/feed?credential=never-store-this"}),
        ("youtube", {"url": "https://youtube.com/feed?password=never-store-this"}),
        ("apify", {"platform": "x", "kind": "profile", "target": "https://x.com/openai?token=never-store-this"}),
        ("rss", {"url": "https://example.com/feed?cursor=access_token"}),
    ],
)
def test_agent_normalization_rejects_sensitive_url_queries_for_every_public_type(
    source_type, config
):
    with pytest.raises(SourceConfigError, match="credentials are not accepted") as exc_info:
        normalize_source_setup_input(source_type, config)

    assert "never-store-this" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("source_type", "config"),
    [
        ("rss", {"url": "https://user:do-not-echo-credential@example.com/feed.xml"}),
        ("telegram", {"channel": "https://user:do-not-echo-credential@t.me/durov"}),
        ("github", {"repository": "https://user:do-not-echo-credential@github.com/openai/codex"}),
        ("reddit", {"subreddit": "https://user:do-not-echo-credential@reddit.com/r/LocalLLaMA"}),
        ("twitter", {"handle": "https://user:do-not-echo-credential@x.com/openai"}),
        ("website", {"url": "https://user:do-not-echo-credential@example.com/feed.xml"}),
        ("youtube", {"url": "https://user:do-not-echo-credential@youtube.com/feed"}),
        ("apify", {"platform": "x", "kind": "profile", "target": "https://user:do-not-echo-credential@x.com/openai"}),
    ],
)
def test_agent_normalization_rejects_url_userinfo_for_every_public_type(
    source_type, config
):
    with pytest.raises(SourceConfigError, match="credentials are not accepted") as exc_info:
        normalize_source_setup_input(source_type, config)

    assert "do-not-echo-credential" not in str(exc_info.value)


@pytest.mark.parametrize(
    "config",
    [
        {"url": "https://example.com/feed.xml", "name": {"cookie": "session-value"}},
        {"repository": {"token": "session-value"}},
        {"repository": ["openai/codex", {"authorization": "session-value"}]},
        {"repository": "openai/codex", "x_api_key": "session-value"},
    ],
)
def test_agent_normalization_rejects_nested_credential_shaped_keys_and_values(config):
    with pytest.raises(SourceConfigError, match="credentials are not accepted") as exc_info:
        normalize_source_setup_input("website" if "url" in config else "github", config)

    assert "session-value" not in str(exc_info.value)


def test_agent_normalization_rejects_non_scalar_field_values_before_alias_parsing():
    with pytest.raises(SourceConfigError, match="url must be a string"):
        normalize_source_setup_input("website", {"url": ["https://example.com/feed.xml"]})


@pytest.mark.parametrize(
    "value",
    [
        "https://t.me/+privateinvite",
        "https://t.me/joinchat/privateinvite",
        "+privateinvite",
        "joinchat/privateinvite",
        "https://t.me/durov/preview",
    ],
)
def test_agent_normalization_rejects_private_or_non_channel_telegram_urls(value):
    with pytest.raises(SourceConfigError, match="public Telegram channel"):
        normalize_source_setup_input("telegram", {"channel": value})


@pytest.mark.parametrize(
    "value",
    [
        "https://t.me/durov?single=1",
        "https://t.me/durov#post",
        "https://t.me/durov?",
        "https://t.me/durov#",
        "https://t.me//durov",
        "https://t.me/share?url=https%3A%2F%2Fexample.com",
        "https://t.me/proxy?server=example.com",
        "https://t.me/socks?server=example.com",
        "https://t.me/confirmphone?phone=123",
        "https://t.me/addlist/example",
        "share",
        "@proxy",
        "socks",
        "confirmphone",
        "joinchat",
        "addlist",
    ],
)
def test_agent_normalization_rejects_telegram_routes_and_url_suffixes(value):
    with pytest.raises(SourceConfigError, match="public Telegram channel"):
        normalize_source_setup_input("telegram", {"channel": value})


@pytest.mark.parametrize(
    "value", ["durov", "@durov", "https://t.me/durov", "https://t.me/durov/"]
)
def test_agent_normalization_accepts_public_telegram_username_roots(value):
    result = normalize_source_setup_input("telegram", {"channel": value})

    assert result["config"]["channel"] == "durov"


def test_agent_normalization_wraps_malformed_url_as_source_config_error():
    with pytest.raises(SourceConfigError) as exc_info:
        normalize_source_setup_input("website", {"url": "https://[broken"})

    assert "https://[broken" not in str(exc_info.value)


def test_agent_normalization_rejects_credentials_without_echoing_them():
    with pytest.raises(SourceConfigError, match="credentials are not accepted"):
        normalize_source_setup_input(
            "github", {"repository": "openai/codex", "token": "never-store-this"}
        )
    with pytest.raises(SourceConfigError, match="credentials are not accepted") as exc_info:
        normalize_source_setup_input(
            "rss",
            {"url": "https://example.com/feed?access_token=never-store-this"},
        )
    assert "never-store-this" not in str(exc_info.value)


@pytest.mark.parametrize(
    "query_name",
    ["access_key", "private_key", "x_api_key", "access_%6bey"],
)
@pytest.mark.parametrize(
    ("source_type", "config_factory"),
    [
        ("rss", lambda query: {"url": f"https://example.com/feed?{query}=value"}),
        ("telegram", lambda query: {"channel": f"https://t.me/durov?{query}=value"}),
        ("github", lambda query: {"repository": f"https://github.com/openai/codex?{query}=value"}),
        ("reddit", lambda query: {"subreddit": f"https://reddit.com/r/LocalLLaMA?{query}=value"}),
        ("twitter", lambda query: {"handle": f"https://x.com/openai?{query}=value"}),
        ("website", lambda query: {"url": f"https://example.com/feed?{query}=value"}),
        (
            "youtube",
            lambda query: {
                "url": f"https://www.youtube.com/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}&{query}=value"
            },
        ),
        (
            "apify",
            lambda query: {
                "platform": "x",
                "kind": "profile",
                "target": f"https://x.com/openai?{query}=value",
            },
        ),
    ],
)
def test_agent_normalization_rejects_composite_sensitive_query_names(
    query_name, source_type, config_factory
):
    with pytest.raises(SourceConfigError) as exc_info:
        normalize_source_setup_input(source_type, config_factory(query_name))

    assert str(exc_info.value) == CREDENTIAL_ERROR


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/feed?cursor=access_key",
        "https://example.com/feed?cursor=x_api_key",
        "https://example.com/feed?cursor=ok&cursor=private_key",
        "https://example.com/feed?cursor=Authorization%3A+Bearer+never-store-this",
    ],
)
def test_agent_normalization_safely_checks_decoded_and_repeated_query_values(url):
    with pytest.raises(SourceConfigError) as exc_info:
        normalize_source_setup_input("website", {"url": url})

    assert str(exc_info.value) == CREDENTIAL_ERROR
    assert "never-store-this" not in str(exc_info.value)


def test_query_values_and_free_text_do_not_treat_substrings_as_credentials():
    rss = normalize_source_setup_input(
        "rss",
        {
            "url": (
                "https://example.com/feed?q=monkey&title=authentic"
                "&cursor=sk-never-store-this"
            ),
            "name": "Monkey: Daily",
        },
    )

    assert rss["config"]["name"] == "Monkey: Daily"
    assert rss["config"]["url"].endswith(
        "?q=monkey&title=authentic&cursor=sk-never-store-this"
    )


@pytest.mark.parametrize(
    "config",
    [
        {
            "url": "https://example.com/feed",
            "name": "Feed ghp_1234567890abcdef",
        },
        {
            "url": "https://example.com/feed",
            "name": "Release github_pat_12345678_abcdefgh",
        },
        {
            "url": "https://example.com/feed?cursor=xoxb-12345678-abcdefgh",
        },
        {
            "url": "https://example.com/feed#xoxp-12345678-abcdefgh",
        },
        {
            "url": "https://example.com/feed#github%255Fpat%255F12345678%255Fabcdefgh",
        },
    ],
)
def test_agent_normalization_rejects_embedded_known_token_values_in_all_url_parts(
    config,
):
    with pytest.raises(SourceConfigError) as exc_info:
        normalize_source_setup_input("rss", config)

    assert str(exc_info.value) == CREDENTIAL_ERROR
    assert "12345678" not in str(exc_info.value)


def test_bearer_business_title_is_safe_without_credential_context():
    result = normalize_source_setup_input(
        "rss",
        {
            "url": "https://example.com/bearer-market-report.xml",
            "name": "Bearer Market Report",
        },
    )

    assert result["config"]["name"] == "Bearer Market Report"


@pytest.mark.parametrize(
    "name",
    [
        "Authori\u200bzation: Bearer never-store-this",
        "Authori\ufe0fzation: Bearer never-store-this",
        "Authorization%3A%20Bearer%20never-store-this",
        "Authorization%253A%2520Bearer%2520never-store-this",
    ],
)
def test_free_text_credential_classification_folds_ignorable_and_encoded_syntax(name):
    with pytest.raises(SourceConfigError) as exc_info:
        normalize_source_setup_input(
            "rss", {"url": "https://example.com/feed", "name": name}
        )

    assert str(exc_info.value) == CREDENTIAL_ERROR
    assert "never-store-this" not in str(exc_info.value)


def test_free_text_security_classification_does_not_rewrite_persisted_safe_text():
    result = normalize_source_setup_input(
        "rss",
        {
            "url": "https://example.com/feed?q=monkey",
            "name": "Release%20Notes — Monkey: Daily",
        },
    )

    assert result["config"]["name"] == "Release%20Notes — Monkey: Daily"
    assert result["config"]["url"].endswith("?q=monkey")


@pytest.mark.parametrize(
    "query_name",
    [
        "ｔｏｋｅｎ",
        "ａｐｉ＿ｋｅｙ",
        quote("ｔｏｋｅｎ", safe=""),
        quote("ａｐｉ＿ｋｅｙ", safe=""),
    ],
)
def test_agent_normalization_rejects_nfkc_sensitive_query_names(query_name):
    with pytest.raises(SourceConfigError) as exc_info:
        normalize_source_setup_input(
            "rss", {"url": f"https://example.com/feed?{query_name}=value"}
        )

    assert str(exc_info.value) == CREDENTIAL_ERROR


@pytest.mark.parametrize(
    "query_value",
    [
        "ａｐｉ＿ｋｅｙ",
        quote("ａｐｉ＿ｋｅｙ", safe=""),
        quote("Ａｕｔｈｏｒｉｚａｔｉｏｎ： Ｂｅａｒｅｒ value", safe=""),
    ],
)
def test_agent_normalization_rejects_nfkc_credential_query_values(query_value):
    with pytest.raises(SourceConfigError) as exc_info:
        normalize_source_setup_input(
            "website", {"url": f"https://example.com/feed?cursor={query_value}"}
        )

    assert str(exc_info.value) == CREDENTIAL_ERROR


@pytest.mark.parametrize(
    ("source_type", "config"),
    [
        ("rss", {"url": "https://example.com/feed", "name": "Authorization: Bearer never-store-this"}),
        ("telegram", {"channel": "Proxy-Authorization: Basic never-store-this"}),
        ("github", {"repository": "Cookie: session=never-store-this"}),
        ("reddit", {"subreddit": "Set-Cookie: session=never-store-this"}),
        ("twitter", {"handle": "X-API-Key: never-store-this"}),
        ("website", {"url": "token=never-store-this"}),
        ("youtube", {"url": "api_key=never-store-this"}),
        (
            "apify",
            {
                "platform": "x",
                "kind": "profile",
                "target": "credential=never-store-this",
            },
        ),
    ],
)
def test_agent_normalization_rejects_credential_headers_and_assignments_in_free_text(
    source_type, config
):
    with pytest.raises(SourceConfigError) as exc_info:
        normalize_source_setup_input(source_type, config)

    assert str(exc_info.value) == CREDENTIAL_ERROR
    assert "never-store-this" not in str(exc_info.value)


@pytest.mark.parametrize(
    "source_type",
    [
        "Authorization: Bearer never-store-this",
        "token=never-store-this",
        "sk-never-store-this",
    ],
)
def test_unsupported_source_type_errors_are_constant_and_do_not_echo_input(source_type):
    with pytest.raises(SourceConfigError) as guide_error:
        get_source_setup_guide(source_type, "en")
    with pytest.raises(SourceConfigError) as normalize_error:
        normalize_source_setup_input(source_type, {})
    with pytest.raises(SourceConfigError) as validation_error:
        validate_source_config(source_type, {})
    with pytest.raises(SourceConfigError) as source_key_error:
        source_key(source_type, {})

    assert str(guide_error.value) == UNSUPPORTED_SOURCE_TYPE_ERROR
    assert str(normalize_error.value) == UNSUPPORTED_SOURCE_TYPE_ERROR
    assert str(validation_error.value) == UNSUPPORTED_SOURCE_TYPE_ERROR
    assert str(source_key_error.value) == UNSUPPORTED_SOURCE_TYPE_ERROR
    assert "never-store-this" not in str(guide_error.value)
    assert "never-store-this" not in str(normalize_error.value)
    assert "never-store-this" not in str(validation_error.value)
    assert "never-store-this" not in str(source_key_error.value)


@pytest.mark.parametrize(
    ("url", "canonical_url"),
    [
        (
            f"https://youtube.com/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}",
            f"https://www.youtube.com/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}",
        ),
        *[
            (
                f"https://www.youtube.com/feeds/videos.xml?playlist_id={playlist_id}",
                f"https://www.youtube.com/feeds/videos.xml?playlist_id={playlist_id}",
            )
            for playlist_id in YOUTUBE_PLAYLIST_IDS
        ],
    ],
)
def test_youtube_normalization_accepts_only_feed_identities_and_returns_canonical_url(
    url, canonical_url
):
    result = normalize_source_setup_input("youtube", {"url": url})

    assert result["catalog_source_type"] == "rss"
    assert result["config"]["url"] == canonical_url


@pytest.mark.parametrize(
    "url",
    [
        f"https://example.com/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}",
        "https://www.youtube.com/watch?v=abc",
        "https://www.youtube.com/feeds/videos.xml",
        "https://www.youtube.com/feeds/videos.xml?channel_id=",
        f"https://www.youtube.com/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}&channel_id=UCabcdefghijklmnopqrstuw",
        f"https://www.youtube.com/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}&playlist_id={YOUTUBE_PLAYLIST_IDS[0]}",
        f"https://www.youtube.com/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}&feature=shared",
        f"https://www.youtube.com/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}#fragment",
        f"https://www.youtube.com:443/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}",
        "https://www.youtube.com/feeds/videos.xml?channel_id=x",
        "https://www.youtube.com/feeds/videos.xml?channel_id=UCabcdefghijklmnopqrstu",
        "https://www.youtube.com/feeds/videos.xml?channel_id=UCabcdefghijklmnopqrstuvx",
        "https://www.youtube.com/feeds/videos.xml?channel_id=UCabcdefghijklmnopqrstu%2F",
        "https://www.youtube.com/feeds/videos.xml?playlist_id=XXabcdefghijklmnopqrstuvwxyz012345",
        "https://www.youtube.com/feeds/videos.xml?playlist_id=PLshort",
        "https://www.youtube.com/feeds/videos.xml?playlist_id=UUabcdefghijklmnopqrstuvx",
    ],
)
def test_youtube_normalization_rejects_non_feed_or_ambiguous_identity_urls(url):
    with pytest.raises(SourceConfigError, match="YouTube feed URL"):
        normalize_source_setup_input("youtube", {"url": url})


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("LocalLLaMA", "LocalLLaMA"),
        ("r/LocalLLaMA", "LocalLLaMA"),
        ("R/LocalLLaMA/", "LocalLLaMA"),
        ("https://www.reddit.com/R/LocalLLaMA/", "LocalLLaMA"),
    ],
)
def test_reddit_normalization_accepts_only_names_or_exact_subreddit_roots(value, expected):
    result = normalize_source_setup_input("reddit", {"subreddit": value})

    assert result["config"]["subreddit"] == expected


@pytest.mark.parametrize(
    "value",
    [
        "https://reddit.com/r/python/comments/abc/post",
        "https://reddit.com/user/spez",
        "https://reddit.com/r/python/about",
        "https://reddit.com/r/python/?sort=new",
        "https://reddit.com/r/python/#fragment",
        "u/spez",
        "foo/bar",
        "r/python/comments",
        "ab",
        "python-name",
    ],
)
def test_reddit_normalization_rejects_posts_users_multisegment_and_invalid_names(value):
    with pytest.raises(SourceConfigError, match="subreddit"):
        normalize_source_setup_input("reddit", {"subreddit": value})


@pytest.mark.parametrize(
    ("repository", "owner", "repo"),
    [
        ("a/b", "a", "b"),
        ("openai/repo.name", "openai", "repo.name"),
        ("openai/.github", "openai", ".github"),
        ("https://github.com/open%61i/codex", "openai", "codex"),
        (f"{'a' * 39}/{'b' * 100}", "a" * 39, "b" * 100),
    ],
)
def test_github_normalization_accepts_realistic_offline_repository_grammar(
    repository, owner, repo
):
    result = normalize_source_setup_input("github", {"repository": repository})

    assert result["config"]["owner"] == owner
    assert result["config"]["repo"] == repo


@pytest.mark.parametrize(
    "repository",
    [
        "https://github.com/openai/codex.git",
        "openai/codex.git",
    ],
)
def test_github_normalization_strips_clone_suffix_from_url_and_bare_identity(repository):
    result = normalize_source_setup_input("github", {"repository": repository})

    assert result["config"]["owner"] == "openai"
    assert result["config"]["repo"] == "codex"


@pytest.mark.parametrize(
    "repository",
    [
        "bad owner/repo name",
        "-owner/repo",
        "owner-/repo",
        "owner--name/repo",
        f"{'a' * 40}/repo",
        f"owner/{'b' * 101}",
        "owner/.",
        "owner/..",
        "owner/repo%2Fextra",
        "owner%2Frepo",
        "owner/repo%0Aname",
        "owner/repo\nname",
        "owner//repo",
        "https://github.com//openai/codex",
        "https://github.com/openai/codex?tab=readme",
        "https://github.com/openai/codex#readme",
        "https://github.com:443/openai/codex",
    ],
)
def test_github_normalization_rejects_invalid_or_ambiguous_repository_identities(
    repository,
):
    with pytest.raises(SourceConfigError, match="repository"):
        normalize_source_setup_input("github", {"repository": repository})


@pytest.mark.parametrize("source_type", ["rss", "website"])
@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/feed",
        "http://feeds.localhost/feed",
        "http://LOCALHOST./feed",
        "http://127.0.0.1/feed",
        "http://10.0.0.1/feed",
        "http://169.254.169.254/feed",
        "http://0.0.0.0/feed",
        "http://192.0.2.1/feed",
        "http://224.0.0.1/feed",
        "http://[::1]/feed",
        "http://[fc00::1]/feed",
        "http://[fe80::1]/feed",
        "http://[::]/feed",
        "http://[2001:db8::1]/feed",
        "http://[ff02::1]/feed",
    ],
)
def test_agent_rss_urls_reject_non_public_local_targets_without_dns(source_type, url):
    with pytest.raises(SourceConfigError, match="public network"):
        normalize_source_setup_input(source_type, {"url": url})


@pytest.mark.parametrize("source_type", ["rss", "website"])
@pytest.mark.parametrize(
    "url",
    [
        "http://127.1/feed",
        "http://127.0.1/feed",
        "http://2130706433/feed",
        "http://0x7f000001/feed",
        "http://0x7f.1/feed",
        "http://0177.0.0.1/feed",
        "http://0177.1/feed",
        "http://017700000001/feed",
    ],
)
def test_agent_rss_urls_reject_historical_loopback_ipv4_forms_without_dns(
    source_type, url
):
    with pytest.raises(SourceConfigError, match="public network"):
        normalize_source_setup_input(source_type, {"url": url})


@pytest.mark.parametrize("source_type", ["rss", "website"])
@pytest.mark.parametrize(
    "url",
    [
        "http://127%2e0%2e0%2e1/feed",
        "http://%31%32%37.0.0.1/feed",
        "http://localhost%2e/feed",
        "http://%6cocalhost/feed",
        "http://[2001:4860:4860::8888%25zone]/feed",
    ],
)
def test_agent_rss_urls_reject_percent_escaped_hostnames_without_echoing_input(
    source_type, url
):
    with pytest.raises(SourceConfigError) as exc_info:
        normalize_source_setup_input(source_type, {"url": url})

    assert str(exc_info.value) == "url must target the public network"
    assert url not in str(exc_info.value)


@pytest.mark.parametrize("source_type", ["rss", "website"])
def test_agent_rss_urls_reject_backslash_authorities_without_echoing_input(source_type):
    url = "http://127.0.0.1\\example.com/feed"

    with pytest.raises(SourceConfigError) as exc_info:
        normalize_source_setup_input(source_type, {"url": url})

    assert str(exc_info.value) == "url must target the public network"
    assert url not in str(exc_info.value)


@pytest.mark.parametrize("source_type", ["rss", "website"])
@pytest.mark.parametrize(
    "url",
    [
        "https://127.example.com/feed",
        "https://0x7f000001.example.com/feed",
        "https://release-0177.example/feed",
    ],
)
def test_agent_rss_urls_do_not_confuse_normal_domains_with_historical_ipv4(
    source_type, url
):
    result = normalize_source_setup_input(source_type, {"url": url})

    assert result["config"]["url"] == url


@pytest.mark.parametrize("source_type", ["rss", "website"])
def test_agent_rss_policy_requires_public_network_execution(source_type):
    result = normalize_source_setup_input(
        source_type, {"url": "http://93.184.216.34/feed.xml"}
    )

    assert result["policy"] == {
        "resolution_mode": "create_or_existing",
        "self_service": True,
        "requires_web_setup": False,
        "public_network_only": True,
    }


def test_apify_lookup_accepts_only_identity_fields_and_guide_matches():
    guide = get_source_setup_guide("apify", "en")["source_type"]

    assert [field["name"] for field in guide["fields"]] == [
        "platform",
        "kind",
        "target",
    ]


@pytest.mark.parametrize(
    "customization",
    [
        {"fetch_limit": 20},
        {"fetch_limit": 99},
        {"analysis_mode": "full"},
        {"analysis_mode": "personal_only"},
    ],
)
def test_apify_lookup_rejects_source_customization_with_stable_web_setup_error(
    customization,
):
    with pytest.raises(SourceConfigError) as exc_info:
        normalize_source_setup_input(
            "apify",
            {
                "platform": "x",
                "kind": "profile",
                "target": "openai",
                **customization,
            },
        )

    assert str(exc_info.value) == SOURCE_REQUIRES_WEB_SETUP_ERROR


@pytest.mark.parametrize(
    ("source_type", "config", "catalog_source_type"),
    [
        ("rss", {"url": "https://example.com/feed.xml"}, "rss"),
        ("telegram", {"channel": "durov"}, "telegram_channel"),
        ("github", {"repository": "openai/codex"}, "github_release"),
        ("reddit", {"subreddit": "LocalLLaMA"}, "reddit_subreddit"),
        ("twitter", {"handle": "@openai"}, "apify_social"),
        ("website", {"url": "https://example.com/feed.xml"}, "rss"),
        (
            "youtube",
            {"url": f"https://www.youtube.com/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}"},
            "rss",
        ),
    ],
)
def test_self_service_normalization_returns_create_config_with_explicit_policy(
    source_type, config, catalog_source_type
):
    result = normalize_source_setup_input(source_type, config)

    assert result["catalog_source_type"] == catalog_source_type
    assert result["config"]["enabled"] is True
    expected_policy = {
        "resolution_mode": "create_or_existing",
        "self_service": True,
        "requires_web_setup": False,
    }
    if source_type in {"rss", "website", "youtube"}:
        expected_policy["public_network_only"] = True
    assert result["policy"] == expected_policy


@pytest.mark.parametrize(
    ("source_type", "config"),
    [
        (
            "apify",
            {"platform": "x", "kind": "profile", "target": "openai"},
        ),
    ],
)
def test_generic_managed_sources_return_existing_visible_only_policy(
    source_type, config
):
    result = normalize_source_setup_input(source_type, config)

    assert set(result) == {"lookup_identity", "policy"}
    assert result["lookup_identity"]["catalog_source_type"] == "apify_social"
    assert "enabled" not in result["lookup_identity"]["config"]
    assert result["policy"] == {
        "resolution_mode": "existing_visible_only",
        "self_service": False,
        "requires_web_setup": True,
    }


@pytest.mark.parametrize(
    ("source_type", "config"),
    [
        ("rss", {"url": "https://example.com/reverse.xml", "name": "Reverse"}),
        ("telegram", {"channel": "durov", "fetch_limit": 40}),
        ("github", {"repository": "openai/codex"}),
        (
            "reddit",
            {
                "subreddit": "LocalLLaMA",
                "sort": "top",
                "time_filter": "week",
                "fetch_limit": 50,
                "min_score": 25,
            },
        ),
        ("twitter", {"handle": "@openai"}),
        ("website", {"url": "https://example.com/website.xml"}),
        (
            "youtube",
            {
                "url": (
                    "https://youtube.com/feeds/videos.xml"
                    f"?channel_id={YOUTUBE_CHANNEL_ID}"
                )
            },
        ),
        ("apify", {"platform": "x", "kind": "profile", "target": "openai"}),
    ],
)
def test_normalized_reverse_validator_round_trips_all_public_agent_types(
    source_type,
    config,
):
    forward = normalize_source_setup_input(source_type, config)
    identity = forward.get("lookup_identity", forward)

    restored = validate_normalized_source_setup(
        source_type,
        identity["catalog_source_type"],
        identity["config"],
    )

    assert restored == forward


@pytest.mark.parametrize(
    ("source_type", "catalog_source_type", "config"),
    [
        (
            "youtube",
            "rss",
            validate_source_config(
                "rss", {"url": "https://example.com/not-youtube.xml"}
            ),
        ),
        (
            "github",
            "github_release",
            validate_source_config(
                "github_release", {"owner": "-invalid", "repo": "codex"}
            ),
        ),
        (
            "reddit",
            "reddit_subreddit",
            validate_source_config(
                "reddit_subreddit",
                {"subreddit": "python/comments/abc/post"},
            ),
        ),
        (
            "telegram",
            "telegram_channel",
            validate_source_config(
                "telegram_channel", {"channel": "joinchat"}
            ),
        ),
        (
            "telegram",
            "telegram_channel",
            validate_source_config(
                "telegram_channel", {"channel": "+privateinvite"}
            ),
        ),
        (
            "rss",
            "rss",
            validate_source_config(
                "rss", {"url": "https://example.com/disabled.xml", "enabled": False}
            ),
        ),
        (
            "website",
            "rss",
            validate_source_config(
                "rss",
                {
                    "url": "https://example.com/website-custom.xml",
                    "name": "Not available in the website Agent grammar",
                },
            ),
        ),
        (
            "twitter",
            "apify_social",
            {
                "platform": "x",
                "kind": "profile",
                "target": "openai/status/1",
            },
        ),
    ],
    ids=[
        "youtube-generic-rss",
        "github-invalid-owner",
        "reddit-post-path",
        "telegram-reserved-route",
        "telegram-private-invite",
        "rss-noncanonical-enabled-marker",
        "website-noncanonical-rss-options",
        "twitter-noncanonical-handle",
    ],
)
def test_normalized_reverse_validator_rejects_noncanonical_agent_identities(
    source_type,
    catalog_source_type,
    config,
):
    with pytest.raises(SourceConfigError):
        validate_normalized_source_setup(source_type, catalog_source_type, config)
