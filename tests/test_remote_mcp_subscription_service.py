from __future__ import annotations

from tests.remote_mcp_subscription_service_test_support import *  # noqa: F403

def test_setup_guide_is_safe_and_does_not_require_write_scope(context):
    result = context["service"].get_source_setup_guide(
        actor=_read_actor(context), source_type="rss", locale="en"
    )

    assert result["source_type"]["type"] == "rss"
    serialized = repr(result).lower()
    assert "secret_env" not in serialized
    assert "token_env" not in serialized


def test_bilibili_user_search_is_read_scoped_and_projects_resolver_result(
    context,
):
    resolver = Mock()
    resolver.search.return_value = {
        "schema_version": 1,
        "query": "食贫道",
        "availability": "available",
        "match_status": "exact",
        "resolved_user": {
            "uid": "39627524",
            "name": "食贫道",
            "profile_url": "https://space.bilibili.com/39627524",
        },
        "candidates": [],
        "returned": 0,
        "truncated": False,
        "data_trust": "untrusted_public_metadata",
        "error_code": None,
    }
    context["service"].bilibili_user_search = resolver

    result = context["service"].search_bilibili_users(
        actor=_read_actor(context),
        query="食贫道",
        limit=3,
    )

    assert result["resolved_user"]["uid"] == "39627524"
    resolver.search.assert_called_once_with(query="食贫道", limit=3)


def test_bilibili_user_search_maps_invalid_input_to_safe_tool_error(context):
    resolver = Mock()
    resolver.search.side_effect = ValueError("do not expose input")
    context["service"].bilibili_user_search = resolver

    with pytest.raises(AgentProposalError) as error:
        context["service"].search_bilibili_users(
            actor=_read_actor(context),
            query="invalid",
            limit=5,
        )

    assert error.value.code == "invalid_request"
    assert str(error.value) == "Bilibili account query is invalid"
    assert "do not expose" not in repr(error.value)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


def test_available_sources_are_current_user_scoped_and_secret_safe(context):
    public = _source(
        context,
        name="Public",
        scope="public",
        secret_env="VISIBLE_TOKEN",
    )
    shared = _source(context, name="Shared", scope="workspace")
    mine = _source(context, name="Mine", scope="private", owner="member")
    _source(
        context,
        name="Other private",
        scope="private",
        owner="other",
        secret_env="OTHER_TOKEN",
    )
    _source(
        context,
        name="Disabled",
        scope="workspace",
        secret_env="DISABLED_TOKEN",
        enabled=False,
    )

    result = context["service"].list_available_sources(
        actor=_read_actor(context), source_type=None, unsubscribed_only=False
    )

    assert {item["id"] for item in result["items"]} == {
        public["id"],
        shared["id"],
        mine["id"],
    }
    assert all(
        set(item)
        == {
            "id",
            "name",
            "type",
            "scope",
            "enabled",
            "default_channel",
            "default_topics",
            "public_target",
            "secret_configured",
            "subscribed",
        }
        for item in result["items"]
    )
    assert next(item for item in result["items"] if item["id"] == public["id"])[
        "secret_configured"
    ] is True
    assert next(item for item in result["items"] if item["id"] == mine["id"])[
        "public_target"
    ] == "https://example.com/Mine.xml"
    assert context["secret_calls"] == ["VISIBLE_TOKEN"]
    serialized = repr(result)
    assert "secret_env" not in serialized
    assert "owner_user_id" not in serialized
    assert "'config':" not in serialized
    assert "OTHER_TOKEN" not in serialized


def test_available_bilibili_source_exposes_only_semantic_target(context):
    source = _source(
        context,
        name="食贫道",
        config={
            "provider": "rsshub",
            "site": "bilibili",
            "route_key": "user_video",
            "params": {"uid": "39627524"},
            "url": "https://space.bilibili.com/39627524",
            "name": "食贫道",
            "enabled": True,
            "keep_latest_item": False,
        },
    )

    result = context["service"].list_available_sources(
        actor=_read_actor(context),
        source_type="bilibili",
        unsubscribed_only=False,
    )

    assert result["items"] == [
        {
            "id": source["id"],
            "name": "食贫道",
            "type": "bilibili",
            "scope": "workspace",
            "enabled": True,
            "default_channel": None,
            "default_topics": [],
            "public_target": {
                "site": "bilibili",
                "route_key": "user_video",
                "params": {"uid": "39627524"},
            },
            "secret_configured": False,
            "subscribed": False,
        }
    ]
    assert "rsshub" not in repr(result).lower()


def test_available_source_public_target_hides_unsafe_rss_urls(context):
    unsafe = _source(
        context,
        name="Unsafe private feed",
        scope="private",
        owner="member",
        config={"url": "http://127.0.0.1:1200/bilibili/user/video/123"},
    )

    result = context["service"].list_available_sources(
        actor=_read_actor(context), source_type="rss", unsubscribed_only=False
    )

    item = next(item for item in result["items"] if item["id"] == unsafe["id"])
    assert item["public_target"] == "web_setup_required"
    assert "127.0.0.1" not in repr(item)


def test_available_source_filter_uses_explicit_public_type_matrix(context):
    rows = {
        "rss": _source(
            context,
            name="Z ordinary RSS",
            source_type="rss",
            config={"url": "https://example.com/feed.xml"},
        ),
        "youtube": _source(
            context,
            name="YouTube RSS",
            source_type="rss",
            config={
                "url": (
                    "https://www.youtube.com/feeds/videos.xml?"
                    "channel_id=UCabcdefghijklmnopqrstuv"
                )
            },
        ),
        "github_release": _source(
            context,
            name="Z GitHub release",
            source_type="github_release",
            config={"owner": "openai", "repo": "codex"},
        ),
        "github_user": _source(
            context,
            name="A GitHub user",
            source_type="github_user",
            config={"username": "openai"},
        ),
        "reddit_subreddit": _source(
            context,
            name="Z Reddit subreddit",
            source_type="reddit_subreddit",
            config={"subreddit": "LocalLLaMA"},
        ),
        "reddit_user": _source(
            context,
            name="A Reddit user",
            source_type="reddit_user",
            config={"username": "spez"},
        ),
        "telegram": _source(
            context,
            name="Telegram",
            source_type="telegram_channel",
            config={"channel": "durov"},
        ),
        "twitter": _source(
            context,
            name="Twitter",
            source_type="apify_social",
            config={"platform": "x", "kind": "profile", "target": "openai"},
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
        "hackernews": _source(
            context,
            name="Hacker News",
            source_type="hackernews",
            config={"fetch_top_stories": 30, "min_score": 100},
        ),
    }
    expected = {
        # RSS and Website intentionally share the same non-YouTube RSS set:
        # persisted catalog rows have no discriminator that can separate them.
        "rss": [rows["rss"]["id"]],
        "website": [rows["rss"]["id"]],
        "youtube": [rows["youtube"]["id"]],
        "github": [rows["github_user"]["id"], rows["github_release"]["id"]],
        "reddit": [rows["reddit_user"]["id"], rows["reddit_subreddit"]["id"]],
        "telegram": [rows["telegram"]["id"]],
        "twitter": [rows["twitter"]["id"]],
        "apify": [rows["apify"]["id"]],
    }

    for source_type, expected_ids in expected.items():
        first = context["service"].list_available_sources(
            actor=_read_actor(context),
            source_type=source_type,
            unsubscribed_only=False,
        )
        second = context["service"].list_available_sources(
            actor=_read_actor(context),
            source_type=source_type,
            unsubscribed_only=False,
        )
        result_ids = [item["id"] for item in first["items"]]
        assert result_ids == expected_ids
        assert result_ids == [item["id"] for item in second["items"]]
        assert len(result_ids) == len(set(result_ids))
        assert rows["hackernews"]["id"] not in result_ids


@pytest.mark.parametrize("catalog_populated", [False, True], ids=["empty", "populated"])
def test_available_source_filter_rejects_unknown_public_type_before_catalog_scan(
    context,
    catalog_populated,
):
    if catalog_populated:
        _source(context, name="Visible source")

    with pytest.raises(SourceConfigError, match="unsupported source type"):
        context["service"].list_available_sources(
            actor=_read_actor(context),
            source_type="unknown",
            unsubscribed_only=False,
        )


def test_secret_checker_failure_is_fixed_and_does_not_retain_secret_env(context):
    secret_env = "DO_NOT_EXPOSE_DISCOVERY_TOKEN_ENV"
    _source(
        context,
        name="Secret-backed source",
        secret_env=secret_env,
    )

    def unavailable(name: str) -> bool:
        raise KeyError(name)

    service = RemoteMCPSubscriptionService(
        store=context["store"],
        mutations=context["mutations"],
        proposals=context["proposals"],
        secret_is_set=unavailable,
    )
    with pytest.raises(AgentProposalError) as error:
        service.list_available_sources(
            actor=_read_actor(context),
            source_type="rss",
            unsubscribed_only=False,
        )

    assert error.value.code == "source_discovery_unavailable"
    assert str(error.value) == "source discovery is unavailable"
    assert secret_env not in str(error.value)
    assert secret_env not in repr(error.value)
    assert secret_env not in repr(
        {"code": error.value.code, "message": str(error.value)}
    )
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


def test_unsubscribed_filter_uses_only_the_current_users_subscriptions(context):
    subscribed = _source(context, name="Subscribed")
    other_only = _source(context, name="Other subscribed")
    context["store"].create_subscription(
        user_id=context["member"]["id"], source_id=subscribed["id"]
    )
    context["store"].create_subscription(
        user_id=context["other"]["id"], source_id=other_only["id"]
    )

    result = context["service"].list_available_sources(
        actor=_read_actor(context), source_type=None, unsubscribed_only=True
    )

    assert [item["id"] for item in result["items"]] == [other_only["id"]]
    assert result["items"][0]["subscribed"] is False


@pytest.mark.parametrize(
    ("flag", "actor_factory", "expected_code"),
    [
        (False, _read_actor, "subscription_writes_disabled"),
        (True, _read_actor, "write_scope_required"),
        (True, lambda context: _actor(context, "viewer"), "forbidden"),
    ],
)
def test_prepare_guard_order_fails_before_object_queries(
    context, monkeypatch, flag, actor_factory, expected_code
):
    context["writes_enabled"][0] = flag
    object_query = monkeypatch.setattr(
        context["store"],
        "get_source",
        lambda *_args, **_kwargs: pytest.fail("object query must not run"),
    )
    del object_query

    with pytest.raises(AgentProposalError) as error:
        context["service"].prepare_create_subscription(
            actor=actor_factory(context),
            source={"mode": "existing", "source_id": "src_unknown"},
            subscription={},
            schedule=None,
        )

    assert error.value.code == expected_code
    assert _proposal_count(context) == 0


def test_prepare_rejects_forged_actor_binding_before_object_queries(
    context, monkeypatch
):
    valid = _actor(context, "member")
    forged = DelegatedActor(
        workspace_id=valid.workspace_id,
        user_id=context["other"]["id"],
        role="member",
        delegation_id=valid.delegation_id,
        scopes=valid.scopes,
    )
    monkeypatch.setattr(
        context["store"],
        "get_source",
        lambda *_args, **_kwargs: pytest.fail("object query must not run"),
    )

    with pytest.raises(AgentProposalError) as error:
        context["service"].prepare_create_subscription(
            actor=forged,
            source={"mode": "existing", "source_id": "src_unknown"},
            subscription={},
            schedule=None,
        )

    assert error.value.code == "unauthorized"
    assert _proposal_count(context) == 0


def test_prepare_rejects_forged_write_scope_on_read_delegation(context):
    read = _read_actor(context)
    forged = DelegatedActor(
        workspace_id=read.workspace_id,
        user_id=read.user_id,
        role=read.role,
        delegation_id=read.delegation_id,
        scopes=(AGENT_DELEGATION_READ_SCOPE, AGENT_DELEGATION_WRITE_SCOPE),
    )

    with pytest.raises(AgentProposalError) as error:
        context["service"].prepare_create_subscription(
            actor=forged,
            source={
                "mode": "private",
                "type": "rss",
                "display_name": "Nope",
                "config": {"url": "https://example.com/nope.xml"},
            },
            subscription={},
            schedule=None,
        )

    assert error.value.code == "unauthorized"
    assert _proposal_count(context) == 0


def test_prepare_rechecks_revocation_and_live_user_role(context):
    actor = _actor(context, "member")
    context["store"].connect().execute(
        "UPDATE users SET role = 'viewer' WHERE id = ?", (actor.user_id,)
    )
    context["store"].connect().commit()

    with pytest.raises(AgentProposalError) as downgraded:
        context["service"].prepare_create_subscription(
            actor=actor,
            source={
                "mode": "private",
                "type": "rss",
                "display_name": "Nope",
                "config": {"url": "https://example.com/nope.xml"},
            },
            subscription={},
            schedule=None,
        )
    assert downgraded.value.code == "forbidden"

    context["store"].connect().execute(
        "UPDATE users SET role = 'member' WHERE id = ?", (actor.user_id,)
    )
    context["store"].connect().commit()
    context["store"].revoke_agent_delegation(actor.user_id, actor.delegation_id)
    with pytest.raises(AgentProposalError) as revoked:
        context["service"].prepare_create_subscription(
            actor=actor,
            source={
                "mode": "private",
                "type": "rss",
                "display_name": "Nope",
                "config": {"url": "https://example.com/nope.xml"},
            },
            subscription={},
            schedule=None,
        )
    assert revoked.value.code == "unauthorized"
    assert _proposal_count(context) == 0
