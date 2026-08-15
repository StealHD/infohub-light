import pytest

import src.services.source_type_registry as source_type_registry
from src.services.source_type_registry import (
    INSTAGRAM_PROFILE_SETUP_TYPE,
    X_PROFILE_SETUP_TYPE,
    YOUTUBE_CHANNEL_SETUP_TYPE,
    SourceConfigError,
    build_source_payload,
    catalog_source_setup_type,
    list_source_setup_types,
    list_source_types,
    normalize_platform_profile_setup_config,
    normalize_source_setup_input,
    project_catalog_source_config_for_web,
    self_service_agent_type_for_catalog,
    source_key,
    validate_secret_env_name,
    validate_source_config,
)

YOUTUBE_CHANNEL_ID = "UCabcdefghijklmnopqrstuv"
YOUTUBE_CHANNEL_FEED = (
    "https://www.youtube.com/feeds/videos.xml?"
    f"channel_id={YOUTUBE_CHANNEL_ID}"
)


def test_agent_source_type_validator_owns_exact_public_enum():
    public_types = {
        "rss",
        "bilibili",
        "telegram",
        "github",
        "reddit",
        "twitter",
        "website",
        "youtube",
        "apify",
    }

    assert {
        source_type_registry.validate_agent_source_type(item)
        for item in public_types
    } == public_types
    with pytest.raises(SourceConfigError, match="unsupported source type"):
        source_type_registry.validate_agent_source_type("hackernews")


def test_source_type_registry_lists_supported_types_and_templates():
    types = list_source_types()
    by_type = {item["type"]: item for item in types}

    assert {
        "rss",
        "github_release",
        "github_user",
        "reddit_subreddit",
        "reddit_user",
        "telegram_channel",
        "apify_social",
        "hackernews",
    }.issubset(by_type)
    assert by_type["github_release"]["required_fields"] == ["owner", "repo"]
    assert by_type["apify_social"]["template"]["platform"] == "x"
    assert set(by_type["rss"]) == {
        "type",
        "label",
        "description",
        "required_fields",
        "template",
        "fields",
        "supports_secret_env",
        "credential_mode",
    }
    assert by_type["rss"]["credential_mode"] == "none"
    assert by_type["apify_social"]["credential_mode"] == "source_secret"


def test_actor_ops_profile_config_keeps_route_identity_opaque():
    config = validate_source_config(
        "apify_social",
        {
            "profile_id": "route_01HZYX.actor-ops",
            "target": "@OpenAI",
            "fetch_limit": 1,
        },
    )

    assert config["profile_id"] == "route_01HZYX.actor-ops"
    assert "platform" not in config
    assert "kind" not in config
    assert source_key("apify_social", config) == (
        "apify_social:route_01HZYX.actor-ops:@openai"
    )

    with pytest.raises(SourceConfigError, match="profile_id"):
        validate_source_config(
            "apify_social",
            {"profile_id": "../route", "target": "openai"},
        )


def test_agent_apify_lookup_keeps_legacy_identity_and_requires_web_setup():
    setup = normalize_source_setup_input(
        "apify",
        {"platform": "x", "kind": "profile", "target": "openai"},
    )

    assert setup["lookup_identity"] == {
        "catalog_source_type": "apify_social",
        "config": {"platform": "x", "kind": "profile", "target": "openai"},
    }
    assert setup["policy"]["resolution_mode"] == "existing_visible_only"
    assert setup["policy"]["self_service"] is False


def test_web_setup_types_are_platform_first_without_exposing_apify_route_fields():
    storage_types = {item["type"] for item in list_source_types()}
    setup_types = {item["type"]: item for item in list_source_setup_types()}

    assert YOUTUBE_CHANNEL_SETUP_TYPE not in storage_types
    assert X_PROFILE_SETUP_TYPE not in storage_types
    assert INSTAGRAM_PROFILE_SETUP_TYPE not in storage_types
    assert "apify_social" not in setup_types
    youtube = setup_types[YOUTUBE_CHANNEL_SETUP_TYPE]
    assert youtube["catalog_source_type"] == "rss"
    assert youtube["label"] == "YouTube 频道"
    assert youtube["credential_mode"] == "none"
    fields = {field["name"]: field for field in youtube["fields"]}
    assert fields["url"]["input_type"] == "text"
    assert fields["keep_latest_item"]["default"] is True
    for setup_type in (X_PROFILE_SETUP_TYPE, INSTAGRAM_PROFILE_SETUP_TYPE):
        definition = setup_types[setup_type]
        assert "catalog_source_type" not in definition
        assert definition["availability"] == "ready"
        assert definition["unavailable_reason"] is None
        assert [field["name"] for field in definition["fields"]] == [
            "target",
            "fetch_limit",
            "analysis_mode",
        ]
        assert definition["fields"][2]["options"] == [
            {"value": "full", "label": "完整分析"},
            {"value": "personal_only", "label": "仅收集"},
        ]
        serialized = str(definition).casefold()
        for forbidden in ("apify", "actor", "route", "profile_id"):
            assert forbidden not in serialized


def test_platform_setup_availability_and_config_projection_are_safe():
    setup_types = {
        item["type"]: item
        for item in list_source_setup_types(
            availability={
                X_PROFILE_SETUP_TYPE: (
                    "temporarily_unavailable",
                    "platform_setup_pending",
                ),
                INSTAGRAM_PROFILE_SETUP_TYPE: (
                    "temporarily_unavailable",
                    "workspace_credential_unavailable",
                ),
            }
        )
    }
    assert setup_types[X_PROFILE_SETUP_TYPE]["unavailable_reason"] == (
        "platform_setup_pending"
    )
    assert setup_types[INSTAGRAM_PROFILE_SETUP_TYPE]["unavailable_reason"] == (
        "workspace_credential_unavailable"
    )

    normalized = normalize_platform_profile_setup_config(
        X_PROFILE_SETUP_TYPE,
        {"target": "@OpenAI", "fetch_limit": 3, "analysis_mode": "full"},
    )
    assert normalized == {
        "platform": "x",
        "kind": "profile",
        "target": "@OpenAI",
        "fetch_limit": 3,
        "analysis_mode": "full",
        "enabled": True,
    }
    with pytest.raises(SourceConfigError, match="unsupported fields"):
        normalize_platform_profile_setup_config(
            X_PROFILE_SETUP_TYPE,
            {"target": "openai", "profile_id": "x/profile/items"},
        )

    stored = {
        "profile_id": "x/profile/items",
        "target": "@OpenAI",
        "fetch_limit": 3,
        "analysis_mode": "full",
    }
    assert catalog_source_setup_type("apify_social", stored) == X_PROFILE_SETUP_TYPE
    assert project_catalog_source_config_for_web("apify_social", stored) == {
        "target": "@OpenAI",
        "fetch_limit": 3,
        "analysis_mode": "full",
    }
    assert project_catalog_source_config_for_web(
        "apify_social",
        {
            "platform": "instagram",
            "kind": "hashtag",
            "target": "openai",
            "fetch_limit": 5,
            "analysis_mode": "personal_only",
        },
    ) == {
        "target": "openai",
        "fetch_limit": 5,
        "analysis_mode": "personal_only",
    }


def test_youtube_channel_setup_projection_is_migration_free_and_agent_compatible():
    channel_config = validate_source_config(
        "rss",
        {"url": YOUTUBE_CHANNEL_FEED, "keep_latest_item": True},
    )
    playlist_config = validate_source_config(
        "rss",
        {
            "url": (
                "https://www.youtube.com/feeds/videos.xml?"
                "playlist_id=PLabcdefghijklmnopqrstuvwxyz012345"
            )
        },
    )
    ordinary_config = validate_source_config(
        "rss", {"url": "https://example.com/feed.xml"}
    )

    assert catalog_source_setup_type("rss", channel_config) == "youtube_channel"
    assert catalog_source_setup_type("rss", playlist_config) == "rss"
    assert catalog_source_setup_type("rss", ordinary_config) == "rss"
    assert self_service_agent_type_for_catalog("rss", channel_config) == "youtube"
    assert self_service_agent_type_for_catalog("rss", playlist_config) == "youtube"
    assert self_service_agent_type_for_catalog("rss", ordinary_config) == "rss"


def test_source_type_registry_projects_workspace_apify_pool_mode(monkeypatch):
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")

    by_type = {item["type"]: item for item in list_source_types()}

    assert by_type["apify_social"]["supports_secret_env"] is False
    assert by_type["apify_social"]["credential_mode"] == "workspace_apify_pool"
    assert by_type["rss"]["credential_mode"] == "none"


def test_source_type_registry_exposes_safe_canonical_field_metadata():
    types = {item["type"]: item for item in list_source_types()}
    exact_keys = {
        "name",
        "label",
        "input_type",
        "required",
        "default",
        "options",
        "min",
        "max",
        "help",
    }
    allowed_input_types = {"text", "url", "number", "select", "boolean"}

    assert set(types) == {
        "rss",
        "github_release",
        "github_user",
        "reddit_subreddit",
        "reddit_user",
        "telegram_channel",
        "apify_social",
        "hackernews",
    }
    for source_type in types.values():
        assert source_type["fields"]
        for field in source_type["fields"]:
            assert set(field) == exact_keys
            assert field["input_type"] in allowed_input_types
            assert isinstance(field["required"], bool)
            assert isinstance(field["options"], list)
            assert isinstance(field["help"], str) and field["help"]
            assert field["name"] not in {"secret", "secret_env", "token", "token_env", "api_key"}

    by_field = {
        source_type: {field["name"]: field for field in definition["fields"]}
        for source_type, definition in types.items()
    }
    assert by_field["rss"]["url"] == {
        "name": "url",
        "label": "Feed URL",
        "input_type": "url",
        "required": True,
        "default": None,
        "options": [],
        "min": None,
        "max": None,
        "help": "HTTP or HTTPS RSS/Atom URL without embedded credentials.",
    }
    for source_type in ("rss", "github_release", "github_user"):
        assert by_field[source_type]["fetch_limit"] | {
            "name": "fetch_limit", "default": 20, "min": 1, "max": 100,
        } == by_field[source_type]["fetch_limit"]
    assert by_field["reddit_subreddit"]["sort"]["default"] == "hot"
    assert by_field["reddit_subreddit"]["sort"]["options"] == [
        "hot",
        "new",
        "top",
        "rising",
        "controversial",
    ]
    assert by_field["reddit_subreddit"]["time_filter"]["default"] == "day"
    assert by_field["reddit_subreddit"]["fetch_limit"] | {
        "name": "fetch_limit",
        "label": "Fetch limit",
        "input_type": "number",
        "required": False,
        "default": 25,
        "options": [],
        "min": 1,
        "max": 100,
        "help": "Maximum posts requested per fetch.",
    } == by_field["reddit_subreddit"]["fetch_limit"]
    assert by_field["reddit_user"]["fetch_limit"]["default"] == 10
    assert by_field["telegram_channel"]["fetch_limit"] | {
        "default": 20,
        "min": 1,
        "max": 100,
    } == by_field["telegram_channel"]["fetch_limit"]
    assert by_field["apify_social"]["platform"]["options"] == [
        "x",
        "instagram",
        "facebook",
        "telegram",
    ]
    assert by_field["apify_social"]["analysis_mode"]["options"] == [
        "full",
        "personal_only",
    ]
    assert by_field["hackernews"]["fetch_top_stories"] | {
        "default": 30,
        "min": 1,
        "max": 500,
    } == by_field["hackernews"]["fetch_top_stories"]
    assert by_field["hackernews"]["min_score"]["default"] == 100
    assert by_field["hackernews"]["min_score"]["min"] == 0


def test_source_type_registry_validates_config_and_builds_stable_keys():
    rss = validate_source_config("rss", {"url": "https://example.com/feed.xml", "fetch_limit": 4})
    github = validate_source_config("github_release", {"owner": "OpenAI", "repo": "Codex", "fetch_limit": 5})
    reddit = validate_source_config("reddit_subreddit", {"subreddit": "r/LocalLLaMA"})
    telegram = validate_source_config("telegram_channel", {"channel": "@durov"})

    assert rss["name"] == "https://example.com/feed.xml"
    assert rss["fetch_limit"] == 4
    assert github["type"] == "repo_releases"
    assert github["fetch_limit"] == 5
    assert reddit["subreddit"] == "LocalLLaMA"
    assert telegram["channel"] == "durov"
    assert source_key("rss", rss) == "rss:https://example.com/feed.xml"
    assert source_key("github_release", github) == "github_release:openai/codex"
    assert source_key("reddit_subreddit", reddit) == "reddit_subreddit:localllama"
    assert source_key("telegram_channel", telegram) == "telegram_channel:durov"


def test_rss_latest_item_flag_is_opt_in_and_reaches_worker_payload():
    definition = next(item for item in list_source_types() if item["type"] == "rss")
    field = next(
        item for item in definition["fields"] if item["name"] == "keep_latest_item"
    )
    assert field["input_type"] == "boolean"
    assert field["default"] is False

    default = validate_source_config("rss", {"url": "https://example.com/feed.xml"})
    enabled = validate_source_config(
        "rss",
        {"url": "https://example.com/feed.xml", "keep_latest_item": True},
    )

    assert default["keep_latest_item"] is False
    assert enabled["keep_latest_item"] is True
    assert build_source_payload(
        {
            "id": "src-rss",
            "type": "rss",
            "display_name": "Profile RSS",
            "config": enabled,
        }
    )["keep_latest_item"] is True


def test_managed_bilibili_rss_uses_semantic_identity_and_configured_base_url():
    config = validate_source_config(
        "rss",
        {
            "provider": "rsshub",
            "site": "bilibili",
            "route_key": "user_video",
            "params": {"uid": "039627524"},
            "keep_latest_item": True,
        },
    )

    assert config == {
        "enabled": True,
        "provider": "rsshub",
        "site": "bilibili",
        "route_key": "user_video",
        "params": {"uid": "39627524"},
        "url": "https://space.bilibili.com/39627524",
        "name": "https://space.bilibili.com/39627524",
        "keep_latest_item": True,
    }
    assert source_key("rss", config) == (
        "rss:rsshub:bilibili:user_video:39627524"
    )

    payload = build_source_payload(
        {
            "id": "src-bilibili",
            "type": "rss",
            "display_name": "食贫道",
            "config": config,
        },
        rsshub_base_url="https://rsshub.example.com/private/",
    )

    assert payload["url"] == (
        "https://rsshub.example.com/private/bilibili/user/video/39627524/1"
    )
    assert payload["enforce_public_network"] is False
    assert "rsshub.example.com" not in source_key("rss", config)


@pytest.mark.parametrize(
    "config",
    [
        {
            "provider": "rsshub",
            "site": "bilibili",
            "route_key": "user_video",
            "params": {"uid": "abc"},
        },
        {
            "provider": "rsshub",
            "site": "bilibili",
            "route_key": "followings_video",
            "params": {"uid": "39627524"},
        },
        {
            "provider": "rsshub",
            "site": "bilibili",
            "route_key": "user_video",
            "params": {"uid": "39627524", "cookie": "never"},
        },
    ],
)
def test_managed_bilibili_rss_rejects_uncontrolled_route_inputs(config):
    with pytest.raises(SourceConfigError):
        validate_source_config("rss", config)


def test_source_type_registry_rejects_invalid_configs_and_secret_values():
    with pytest.raises(SourceConfigError):
        validate_source_config("rss", {"url": "ftp://example.com/feed.xml"})
    with pytest.raises(SourceConfigError):
        validate_source_config("github_release", {"owner": "OpenAI"})
    with pytest.raises(SourceConfigError):
        validate_secret_env_name("sk-real-secret-value")
    with pytest.raises(SourceConfigError, match="environment-variable placeholders"):
        validate_source_config(
            "rss",
            {"url": "https://attacker.example/${OPENAI_API_KEY}"},
        )
    with pytest.raises(SourceConfigError, match="credentials"):
        validate_source_config(
            "rss",
            {"url": "https://API_TOKEN@feeds.example.com/private.xml"},
        )


def test_source_type_registry_builds_worker_payload_without_expanding_secret(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "real-token-value")

    payload = build_source_payload(
        {
            "id": "src-release",
            "type": "github_release",
            "display_name": "OpenAI Codex Releases",
            "config": {"owner": "OpenAI", "repo": "Codex"},
            "secret_env": "GITHUB_TOKEN",
        }
    )

    assert payload == {
        "source_type": "github_release",
        "source_id": "src-release",
        "source_display_name": "OpenAI Codex Releases",
        "catalog_source_type": "github_release",
        "type": "repo_releases",
        "owner": "OpenAI",
        "repo": "Codex",
        "enabled": True,
        "token_env": "GITHUB_TOKEN",
    }
    assert "real-token-value" not in repr(payload)
