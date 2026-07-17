import pytest

from src.services.source_type_registry import (
    SourceConfigError,
    get_source_setup_guide,
    list_source_types,
    normalize_source_setup_input,
    source_key,
    validate_source_config,
)


SOURCE_TYPES = {
    "rss",
    "telegram",
    "github",
    "reddit",
    "twitter",
    "website",
    "youtube",
    "apify",
}

CREDENTIAL_ERROR = "credentials are not accepted; configure secrets in Web"
UNSUPPORTED_SOURCE_TYPE_ERROR = "unsupported source type"


def test_setup_guide_is_complete_bilingual_and_secret_safe():
    zh = get_source_setup_guide(None, "zh-CN")
    en = get_source_setup_guide(None, "en")

    assert {item["type"] for item in zh["source_types"]} == SOURCE_TYPES
    assert {item["type"] for item in en["source_types"]} == SOURCE_TYPES
    for locale, payload in (("zh-CN", zh), ("en", en)):
        assert payload["locale"] == locale
        for summary in payload["source_types"]:
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
        "youtube", {"url": "https://www.youtube.com/feeds/videos.xml?channel_id=UC123"}
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
    assert reddit["catalog_source_type"] == "reddit_subreddit"
    assert reddit["config"]["subreddit"] == "LocalLLaMA"
    assert telegram["catalog_source_type"] == "telegram_channel"
    assert telegram["config"]["channel"] == "durov"
    assert twitter == {
        "lookup_identity": {
            "catalog_source_type": "apify_social",
            "config": {
                "platform": "x",
                "kind": "profile",
                "target": "openai",
            },
        },
        "policy": {
            "resolution_mode": "existing_visible_only",
            "self_service": False,
            "requires_web_setup": True,
        },
    }
    assert website["catalog_source_type"] == "rss"
    assert youtube["catalog_source_type"] == "rss"
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
        ("youtube", lambda query: {"url": f"https://www.youtube.com/feeds/videos.xml?channel_id=UC123&{query}=value"}),
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
        "https://example.com/feed?cursor=sk-never-store-this",
        "https://example.com/feed?cursor=ok&cursor=private_key",
        "https://example.com/feed?cursor=Authorization%3A+Bearer+never-store-this",
    ],
)
def test_agent_normalization_safely_checks_decoded_and_repeated_query_values(url):
    with pytest.raises(SourceConfigError) as exc_info:
        normalize_source_setup_input("website", {"url": url})

    assert str(exc_info.value) == CREDENTIAL_ERROR
    assert "never-store-this" not in str(exc_info.value)


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
            "https://youtube.com/feeds/videos.xml?channel_id=UC123",
            "https://www.youtube.com/feeds/videos.xml?channel_id=UC123",
        ),
        (
            "https://www.youtube.com/feeds/videos.xml?playlist_id=PLabc_123-xyz",
            "https://www.youtube.com/feeds/videos.xml?playlist_id=PLabc_123-xyz",
        ),
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
        "https://example.com/feeds/videos.xml?channel_id=UC123",
        "https://www.youtube.com/watch?v=abc",
        "https://www.youtube.com/feeds/videos.xml",
        "https://www.youtube.com/feeds/videos.xml?channel_id=",
        "https://www.youtube.com/feeds/videos.xml?channel_id=UC123&channel_id=UC456",
        "https://www.youtube.com/feeds/videos.xml?channel_id=UC123&playlist_id=PL123",
        "https://www.youtube.com/feeds/videos.xml?channel_id=UC123&feature=shared",
        "https://www.youtube.com/feeds/videos.xml?channel_id=UC123#fragment",
        "https://www.youtube.com:443/feeds/videos.xml?channel_id=UC123",
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
    ("source_type", "config", "catalog_source_type"),
    [
        ("rss", {"url": "https://example.com/feed.xml"}, "rss"),
        ("telegram", {"channel": "durov"}, "telegram_channel"),
        ("github", {"repository": "openai/codex"}, "github_release"),
        ("reddit", {"subreddit": "LocalLLaMA"}, "reddit_subreddit"),
        ("website", {"url": "https://example.com/feed.xml"}, "rss"),
        (
            "youtube",
            {"url": "https://www.youtube.com/feeds/videos.xml?channel_id=UC123"},
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
    assert result["policy"] == {
        "resolution_mode": "create_or_existing",
        "self_service": True,
        "requires_web_setup": False,
    }


@pytest.mark.parametrize(
    ("source_type", "config"),
    [
        ("twitter", {"handle": "@openai"}),
        (
            "apify",
            {"platform": "x", "kind": "profile", "target": "openai"},
        ),
    ],
)
def test_managed_sources_return_lookup_identity_and_existing_visible_only_policy(
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
