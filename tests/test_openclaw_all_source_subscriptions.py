from __future__ import annotations

import pytest

from src.services.actorops.binding_service import (
    ActorOpsBindingError,
    ActorOpsBindingService,
)
from src.services.agent_change_proposal import AgentProposalError
from src.services.source_type_registry import (
    catalog_source_matches_agent_type,
    get_source_setup_guide,
    normalize_source_setup_input,
    validate_agent_source_type,
    validate_normalized_source_setup,
)
from tests.remote_mcp_subscription_service_test_support import (  # noqa: F401
    _actor,
    _read_actor,
    _source,
    context,
)


@pytest.mark.parametrize(
    ("source_type", "config", "catalog_type", "identity"),
    [
        (
            "github_user",
            {"username": "https://github.com/openai"},
            "github_user",
            {"username": "openai"},
        ),
        (
            "reddit_user",
            {"username": "https://reddit.com/user/spez"},
            "reddit_user",
            {"username": "spez"},
        ),
        (
            "instagram",
            {"handle": "https://www.instagram.com/for_everyoung10/"},
            "apify_social",
            {
                "platform": "instagram",
                "kind": "profile",
                "target": "for_everyoung10",
            },
        ),
        (
            "hackernews",
            {},
            "hackernews",
            {"fetch_top_stories": 30, "min_score": 100},
        ),
    ],
)
def test_agent_extension_types_normalize_and_reverse_validate(
    source_type, config, catalog_type, identity
):
    setup = normalize_source_setup_input(source_type, config)

    assert setup["catalog_source_type"] == catalog_type
    assert setup["policy"] == {
        "resolution_mode": "create_or_existing",
        "self_service": True,
        "requires_web_setup": False,
    }
    assert setup["config"].items() >= identity.items()
    assert validate_normalized_source_setup(
        source_type, catalog_type, setup["config"]
    ) == setup


def test_agent_registry_accepts_platform_aliases_and_lists_all_create_types():
    assert validate_agent_source_type("x_profile") == "twitter"
    assert validate_agent_source_type("instagram_profile") == "instagram"
    assert validate_agent_source_type("youtube_channel") == "youtube"
    public_types = {
        item["type"] for item in get_source_setup_guide()["source_types"]
    }
    assert {
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
    } == public_types
    for source_type in public_types:
        assert get_source_setup_guide(source_type)["source_type"]["type"] == source_type


@pytest.mark.parametrize(
    ("source_type", "config"),
    [
        ("twitter", {"handle": "https://x.com/openai?secret=1"}),
        ("instagram", {"handle": "https://instagram.com//openai"}),
        ("instagram", {"handle": "https://instagram.com:invalid/openai"}),
        ("github_user", {"username": "https://github.com//openai"}),
        ("reddit_user", {"username": "https://reddit.com/user//spez"}),
    ],
)
def test_profile_and_user_locators_reject_noncanonical_urls(source_type, config):
    with pytest.raises(ValueError):
        normalize_source_setup_input(source_type, config)


def test_existing_catalog_filters_separate_profiles_and_user_sources():
    assert catalog_source_matches_agent_type(
        "instagram",
        {
            "type": "apify_social",
            "config": {
                "platform": "instagram",
                "kind": "profile",
                "target": "openai",
            },
        },
    )
    assert catalog_source_matches_agent_type(
        "github_user",
        {"type": "github_user", "config": {"username": "openai"}},
    )
    assert not catalog_source_matches_agent_type(
        "apify",
        {
            "type": "apify_social",
            "config": {
                "platform": "instagram",
                "kind": "profile",
                "target": "openai",
            },
        },
    )


def test_remote_mcp_filters_and_projects_new_public_source_types(context):
    rows = {
        "github_user": _source(
            context,
            name="GitHub user",
            source_type="github_user",
            config={"username": "openai"},
        ),
        "reddit_user": _source(
            context,
            name="Reddit user",
            source_type="reddit_user",
            config={"username": "spez"},
        ),
        "instagram": _source(
            context,
            name="Instagram",
            source_type="apify_social",
            config={
                "platform": "instagram",
                "kind": "profile",
                "target": "openai",
            },
        ),
        "hackernews": _source(
            context,
            name="Hacker News",
            source_type="hackernews",
            config={"fetch_top_stories": 30, "min_score": 100},
        ),
        "apify": _source(
            context,
            name="Generic Apify",
            source_type="apify_social",
            config={
                "platform": "instagram",
                "kind": "hashtag",
                "target": "openai",
            },
        ),
    }
    for public_type, source in rows.items():
        result = context["service"].list_available_sources(
            actor=_read_actor(context),
            source_type=public_type,
            unsubscribed_only=False,
        )
        assert [(item["id"], item["type"]) for item in result["items"]] == [
            (source["id"], public_type)
        ]


@pytest.mark.parametrize(
    ("source_type", "handle", "platform"),
    [
        ("twitter", "@dlwlrma", "x"),
        ("instagram", "@for_everyoung10", "instagram"),
    ],
)
def test_remote_mcp_creates_profile_subscription_pending_without_attempt(
    context, source_type, handle, platform
):
    actor = _actor(context, "member")
    side_effect_tables = (
        "actor_attempts_v2",
        "actor_discovery_jobs_v2",
        "fetch_jobs",
    )
    before_side_effects = {
        table: context["store"].connect().execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]
        for table in side_effect_tables
    }
    prepared = context["service"].prepare_create_subscription(
        actor=actor,
        source={
            "mode": "private",
            "type": source_type,
            "display_name": handle,
            "config": {"handle": handle},
        },
        subscription={},
        schedule=None,
    )

    assert prepared["preview"]["source"]["public_target"] == {
        "platform": platform,
        "kind": "profile",
        "target": handle.lstrip("@").lower(),
    }
    assert prepared["preview"]["schedule"]["enabled"] is False
    assert "does not fetch data or start a paid Actor" in prepared["preview"][
        "warnings"
    ][0]

    applied = context["service"].apply_subscription_change(
        actor=actor,
        proposal_id=prepared["proposal_id"],
        confirmation_text=prepared["confirmation_text"],
    )
    source = context["store"].get_source(applied["result"]["source_id"])
    subscription = context["store"].get_subscription(
        applied["result"]["subscription_id"]
    )
    binding = context["store"].connect().execute(
        "SELECT status, binding_version FROM actor_source_bindings_v2 WHERE source_id=?",
        (source["id"],),
    ).fetchone()

    assert source["enabled"] is False
    assert subscription["enabled"] is True
    assert dict(binding) == {"status": "pending", "binding_version": 1}
    assert applied["result"]["schedule_enabled"] is False
    assert {
        table: context["store"].connect().execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]
        for table in side_effect_tables
    } == before_side_effects


def test_profile_binding_failure_rolls_back_business_and_keeps_proposal_pending(
    context, monkeypatch
):
    actor = _actor(context, "member")
    prepared = context["service"].prepare_create_subscription(
        actor=actor,
        source={
            "mode": "private",
            "type": "instagram",
            "display_name": "Rollback profile",
            "config": {"handle": "rollback.profile"},
        },
        subscription={},
        schedule=None,
    )

    def fail_binding(_self, _source_id):
        raise ActorOpsBindingError("actorops_v2_injected_failure")

    monkeypatch.setattr(ActorOpsBindingService, "ensure", fail_binding)
    with pytest.raises(AgentProposalError) as failure:
        context["service"].apply_subscription_change(
            actor=actor,
            proposal_id=prepared["proposal_id"],
            confirmation_text=prepared["confirmation_text"],
        )

    assert failure.value.code == "source_discovery_unavailable"
    assert context["store"].connect().execute(
        "SELECT COUNT(*) FROM source_catalog WHERE display_name='Rollback profile'"
    ).fetchone()[0] == 0
    assert context["store"].get_agent_change_proposal(
        prepared["proposal_id"]
    )["status"] == "pending"


def test_deleting_pending_profile_subscription_disables_its_binding(context):
    actor = _actor(context, "member")
    prepared = context["service"].prepare_create_subscription(
        actor=actor,
        source={
            "mode": "private",
            "type": "instagram",
            "display_name": "Delete pending profile",
            "config": {"handle": "delete.pending"},
        },
        subscription={},
        schedule=None,
    )
    created = context["service"].apply_subscription_change(
        actor=actor,
        proposal_id=prepared["proposal_id"],
        confirmation_text=prepared["confirmation_text"],
    )
    deletion = context["service"].prepare_delete_subscription(
        actor=actor,
        subscription_id=created["result"]["subscription_id"],
        source_disposition="disable_private",
    )

    context["service"].apply_subscription_change(
        actor=actor,
        proposal_id=deletion["proposal_id"],
        confirmation_text=deletion["confirmation_text"],
    )
    binding = context["store"].connect().execute(
        "SELECT status, binding_version FROM actor_source_bindings_v2 WHERE source_id=?",
        (created["result"]["source_id"],),
    ).fetchone()
    assert dict(binding) == {"status": "disabled", "binding_version": 2}


def test_pending_profile_cannot_be_activated_or_retargeted_through_mcp(context):
    actor = _actor(context, "member")
    prepared = context["service"].prepare_create_subscription(
        actor=actor,
        source={
            "mode": "private",
            "type": "instagram",
            "display_name": "Pending profile",
            "config": {"handle": "pending.profile"},
        },
        subscription={},
        schedule=None,
    )
    created = context["service"].apply_subscription_change(
        actor=actor,
        proposal_id=prepared["proposal_id"],
        confirmation_text=prepared["confirmation_text"],
    )
    for source_updates in ({"enabled": True}, {"config": {"target": "other"}}):
        with pytest.raises(AgentProposalError) as closed:
            context["service"].prepare_update_subscription(
                actor=actor,
                subscription_id=created["result"]["subscription_id"],
                source_updates=source_updates,
            )
        assert closed.value.code == "source_requires_web_setup"


def test_generic_apify_creation_remains_closed_but_existing_source_is_subscribable(
    context
):
    actor = _actor(context, "member")
    with pytest.raises(AgentProposalError) as closed:
        context["service"].prepare_create_subscription(
            actor=actor,
            source={
                "mode": "private",
                "type": "apify",
                "display_name": "Generic social",
                "config": {
                    "platform": "instagram",
                    "kind": "hashtag",
                    "target": "codex",
                },
            },
            subscription={},
            schedule=None,
        )
    assert closed.value.code == "source_requires_web_setup"

    source_id = context["store"].create_source(
        workspace_id=context["workspace"]["id"],
        scope="workspace",
        owner_user_id=context["owner"]["id"],
        source_type="hackernews",
        display_name="Existing HN",
        config={"fetch_top_stories": 30, "min_score": 100},
        source_key="hackernews:top",
        enabled=True,
    )
    prepared = context["service"].prepare_create_subscription(
        actor=actor,
        source={"mode": "existing", "source_id": source_id},
        subscription={},
        schedule=None,
    )
    applied = context["service"].apply_subscription_change(
        actor=actor,
        proposal_id=prepared["proposal_id"],
        confirmation_text=prepared["confirmation_text"],
    )
    assert applied["result"]["source_id"] == source_id
