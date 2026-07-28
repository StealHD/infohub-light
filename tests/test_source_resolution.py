from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

import src.storage.service_store as service_store_module
from src.mcp.remote_subscription_service import RemoteMCPSubscriptionService
from src.services.agent_change_proposal import (
    AgentChangeProposalService,
    AgentProposalError,
    DelegatedActor,
)
from src.services.source_resolution import (
    ResolvedSource,
    SourceResolutionError,
    SourceResolutionService,
    YouTubeSourceResolutionAdapter,
)
from src.services.subscription_mutation import SubscriptionMutationService
from src.services.youtube_channel import YouTubeChannelError
from src.storage.service_store import (
    AgentSourceResolutionLimitError,
    ServiceStore,
)


NOW = datetime(2026, 7, 29, 1, 0, tzinfo=timezone.utc)
CHANNEL_ONE = "UCMUnInmOkrWN4gof9KlhNmQ"
CHANNEL_TWO = "UCabcdefghijklmnopqrstuv"


def _feed(channel_id: str) -> str:
    return (
        "https://www.youtube.com/feeds/videos.xml?"
        f"channel_id={channel_id}"
    )


class FakeYouTubeAdapter:
    source_type = "youtube"

    def __init__(self) -> None:
        self.failures: dict[str, YouTubeChannelError] = {}
        self.calls: list[str] = []

    def normalize_direct_input(self, value: str) -> str | None:
        text = value.strip()
        if text.startswith("@"):
            return text
        if "://" in text:
            if not text.startswith("https://www.youtube.com/"):
                raise SourceResolutionError(
                    "invalid_request", "invalid candidate"
                )
            return text
        return None

    def normalize_candidate_url(self, value: str) -> str:
        text = value.strip()
        if not text.startswith("https://www.youtube.com/@"):
            raise SourceResolutionError(
                "invalid_request", "invalid candidate"
            )
        return text

    async def resolve(self, locator: str) -> ResolvedSource:
        self.calls.append(locator)
        if locator in self.failures:
            raise self.failures[locator]
        if "second" in locator:
            return ResolvedSource(
                identity=CHANNEL_TWO,
                display_name="Second Channel",
                public_url=f"https://www.youtube.com/channel/{CHANNEL_TWO}",
                config={
                    "url": _feed(CHANNEL_TWO),
                    "keep_latest_item": True,
                },
            )
        return ResolvedSource(
            identity=CHANNEL_ONE,
            display_name="老高與小茉 Mr & Mrs Gao",
            public_url=f"https://www.youtube.com/channel/{CHANNEL_ONE}",
            config={
                "url": _feed(CHANNEL_ONE),
                "keep_latest_item": True,
            },
        )


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    clock = [NOW]
    monkeypatch.setattr(
        service_store_module,
        "_proposal_utc_now",
        lambda: clock[0],
    )
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    member = store.create_user(
        workspace_id=workspace["id"],
        username="member",
        password="member-password",
        role="member",
    )
    other = store.create_user(
        workspace_id=workspace["id"],
        username="other",
        password="other-password",
        role="member",
    )

    def actor(user: dict[str, Any]) -> DelegatedActor:
        delegation, _token = store.create_agent_delegation(
            workspace_id=workspace["id"],
            user_id=user["id"],
            name=f"{user['username']} writer",
            access="subscriptions_write",
        )
        return DelegatedActor(
            workspace_id=workspace["id"],
            user_id=user["id"],
            role=user["role"],
            delegation_id=delegation["id"],
            scopes=tuple(delegation["scopes"]),
        )

    adapter = FakeYouTubeAdapter()
    resolutions = SourceResolutionService(store, adapters=(adapter,))
    mutations = SubscriptionMutationService(store)
    proposals = AgentChangeProposalService(
        store,
        writes_enabled=True,
        mutations=mutations,
    )
    facade = RemoteMCPSubscriptionService(
        store=store,
        mutations=mutations,
        proposals=proposals,
        secret_is_set=lambda _name: False,
        source_resolutions=resolutions,
    )
    return {
        "store": store,
        "workspace": workspace,
        "member": member,
        "other": other,
        "member_actor": actor(member),
        "other_actor": actor(other),
        "adapter": adapter,
        "resolutions": resolutions,
        "facade": facade,
        "clock": clock,
    }


def _resolve(
    context: dict[str, Any],
    *,
    name: str = "老高和小茉",
    candidates: list[str] | None = None,
) -> dict[str, Any]:
    return asyncio.run(
        context["facade"].resolve_source(
            actor=context["member_actor"],
            source_type="youtube",
            input_value=name,
            candidate_urls=(
                ["https://www.youtube.com/@laogao"]
                if candidates is None
                else candidates
            ),
            limit=5,
        )
    )


def test_unique_candidate_mints_idempotent_ref_without_business_write(context):
    before = tuple(
        context["store"].connect().execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]
        for table in (
            "source_catalog",
            "user_subscriptions",
            "user_source_schedules",
        )
    )

    first = _resolve(context)
    second = _resolve(context)

    assert first["status"] == "resolved"
    assert first["returned"] == 1
    candidate = first["candidates"][0]
    assert candidate == second["candidates"][0]
    assert candidate["display_name"] == "老高與小茉 Mr & Mrs Gao"
    assert candidate["subscription_state"] == "new"
    assert candidate["public_url"] == (
        f"https://www.youtube.com/channel/{CHANNEL_ONE}"
    )
    assert candidate["resolution_ref"].startswith("asr_")
    assert "feeds/videos.xml" not in repr(first)
    assert "channel_id" not in repr(first)
    assert int(
        context["store"]
        .connect()
        .execute("SELECT COUNT(*) FROM agent_source_resolutions")
        .fetchone()[0]
    ) == 1
    after = tuple(
        context["store"].connect().execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]
        for table in (
            "source_catalog",
            "user_subscriptions",
            "user_source_schedules",
        )
    )
    assert after == before


def test_name_without_candidates_requires_agent_discovery(context):
    result = _resolve(context, candidates=[])

    assert result["status"] == "discovery_required"
    assert result["candidates"] == []
    assert context["adapter"].calls == []


def test_youtube_adapter_treats_uc_names_as_discovery_and_candidates_as_www_only():
    adapter = YouTubeSourceResolutionAdapter()

    assert adapter.normalize_direct_input("UC Berkeley") is None
    assert (
        adapter.normalize_candidate_url(
            "https://www.youtube.com/@GoogleDevelopers"
        )
        == "@GoogleDevelopers"
    )
    with pytest.raises(SourceResolutionError):
        adapter.normalize_candidate_url(
            "https://youtube.com/@GoogleDevelopers"
        )


def test_multiple_verified_candidates_are_ambiguous(context):
    result = _resolve(
        context,
        candidates=[
            "https://www.youtube.com/@laogao",
            "https://www.youtube.com/@second",
        ],
    )

    assert result["status"] == "ambiguous"
    assert result["returned"] == 2
    assert {
        candidate["display_name"] for candidate in result["candidates"]
    } == {"老高與小茉 Mr & Mrs Gao", "Second Channel"}


def test_retryable_and_terminal_resolution_failures_map_to_stable_statuses(
    context,
):
    candidate = "https://www.youtube.com/@laogao"
    context["adapter"].failures[candidate] = YouTubeChannelError(
        "youtube_channel_resolution_failed",
        "safe",
        status_code=502,
        retryable=True,
        action="retry",
    )
    assert _resolve(context)["status"] == "unavailable"

    context["adapter"].failures[candidate] = YouTubeChannelError(
        "youtube_channel_not_found",
        "safe",
        status_code=404,
        retryable=False,
        action="check",
    )
    assert _resolve(context)["status"] == "not_found"


def test_invalid_candidate_is_rejected_before_network(context):
    with pytest.raises(AgentProposalError) as error:
        _resolve(
            context,
            candidates=["https://example.com/@laogao"],
        )

    assert error.value.code == "invalid_request"
    assert context["adapter"].calls == []


def test_visible_existing_and_subscribed_states_do_not_leak_config(context):
    source_id = context["store"].create_source(
        workspace_id=context["workspace"]["id"],
        scope="workspace",
        owner_user_id=None,
        source_type="rss",
        display_name="Existing YouTube",
        config={
            "url": _feed(CHANNEL_ONE),
            "enabled": True,
            "name": _feed(CHANNEL_ONE),
            "keep_latest_item": True,
        },
        source_key=f"rss:{_feed(CHANNEL_ONE)}",
        enforce_public_network=True,
    )

    available = _resolve(context)["candidates"][0]
    assert available["subscription_state"] == "available"
    assert "resolution_ref" in available
    assert source_id not in repr(available)

    context["store"].create_subscription(
        user_id=context["member"]["id"],
        source_id=source_id,
    )
    subscribed = _resolve(context)["candidates"][0]
    assert subscribed["subscription_state"] == "subscribed"
    assert "resolution_ref" not in subscribed
    assert "expires_at" not in subscribed


def test_same_actor_ref_is_reused_when_canonical_source_becomes_available(
    context,
):
    first = _resolve(context)["candidates"][0]
    source_id = context["store"].create_source(
        workspace_id=context["workspace"]["id"],
        scope="workspace",
        owner_user_id=None,
        source_type="rss",
        display_name="Existing YouTube",
        config={
            "url": _feed(CHANNEL_ONE),
            "enabled": True,
            "name": _feed(CHANNEL_ONE),
            "keep_latest_item": True,
        },
        source_key=f"rss:{_feed(CHANNEL_ONE)}",
        enforce_public_network=True,
    )

    second = _resolve(context)["candidates"][0]

    assert second["subscription_state"] == "available"
    assert second["resolution_ref"] == first["resolution_ref"]
    assert context["resolutions"].resolve_reference(
        actor=context["member_actor"],
        resolution_ref=second["resolution_ref"],
    ) == {
        "mode": "existing",
        "source_id": source_id,
    }


def test_resolution_ref_prepares_and_applies_existing_plan_with_canonical_feed(
    context,
):
    result = _resolve(context)
    reference = result["candidates"][0]["resolution_ref"]
    before = context["store"].connect().execute(
        "SELECT COUNT(*) FROM source_catalog"
    ).fetchone()[0]

    prepared = context["facade"].prepare_create_subscription(
        actor=context["member_actor"],
        source={"mode": "resolved", "resolution_ref": reference},
        subscription=None,
        schedule=None,
    )

    assert (
        context["store"]
        .connect()
        .execute("SELECT COUNT(*) FROM source_catalog")
        .fetchone()[0]
        == before
    )
    proposal = context["store"].get_agent_change_proposal(
        prepared["proposal_id"]
    )
    config = proposal["payload"]["plan_snapshot"]["normalized"]["source"][
        "config"
    ]
    assert config["url"] == _feed(CHANNEL_ONE)
    assert config["keep_latest_item"] is True

    applied = context["facade"].apply_subscription_change(
        actor=context["member_actor"],
        proposal_id=prepared["proposal_id"],
        confirmation_text=prepared["confirmation_text"],
    )
    source = context["store"].get_source(applied["result"]["source_id"])
    assert source["config"]["url"] == _feed(CHANNEL_ONE)
    assert source["config"]["keep_latest_item"] is True


def test_resolution_ref_is_actor_bound_and_same_actor_expiry_is_explicit(
    context,
):
    reference = _resolve(context)["candidates"][0]["resolution_ref"]

    with pytest.raises(AgentProposalError) as cross_actor:
        context["facade"].prepare_create_subscription(
            actor=context["other_actor"],
            source={"mode": "resolved", "resolution_ref": reference},
        )
    assert cross_actor.value.code == "not_found"

    context["clock"][0] = NOW + timedelta(minutes=11)
    with pytest.raises(AgentProposalError) as expired:
        context["facade"].prepare_create_subscription(
            actor=context["member_actor"],
            source={"mode": "resolved", "resolution_ref": reference},
        )
    assert expired.value.code == "source_resolution_expired"


def test_hidden_source_key_is_not_projected_and_prepare_conflict_stays_generic(
    context,
):
    context["store"].create_source(
        workspace_id=context["workspace"]["id"],
        scope="private",
        owner_user_id=context["other"]["id"],
        source_type="rss",
        display_name="Hidden",
        config={
            "url": _feed(CHANNEL_ONE),
            "enabled": True,
            "name": _feed(CHANNEL_ONE),
            "keep_latest_item": True,
        },
        source_key=f"rss:{_feed(CHANNEL_ONE)}",
        enforce_public_network=True,
    )

    candidate = _resolve(context)["candidates"][0]
    assert candidate["subscription_state"] == "new"
    assert "Hidden" not in repr(candidate)
    with pytest.raises(AgentProposalError) as error:
        context["facade"].prepare_create_subscription(
            actor=context["member_actor"],
            source={
                "mode": "resolved",
                "resolution_ref": candidate["resolution_ref"],
            },
        )
    assert error.value.code == "source_key_conflict"


def test_resolution_storage_has_v12_marker_and_enforces_active_limit(context):
    store = context["store"]
    marker = store.connect().execute(
        "SELECT name, checksum FROM schema_migrations WHERE version = 12"
    ).fetchone()
    indexes = {
        row["name"]
        for row in store.connect().execute(
            "PRAGMA index_list(agent_source_resolutions)"
        )
    }
    assert marker["name"] == "agent_source_resolutions_v12"
    assert marker["checksum"] == "agent-source-resolutions-v12"
    assert {
        "idx_agent_source_resolutions_delegation_expires",
        "idx_agent_source_resolutions_actor_fingerprint",
    } <= indexes

    actor = context["member_actor"]
    for index in range(20):
        key = f"rss:https://www.youtube.com/feed/{index}"
        store.create_or_reuse_agent_source_resolution(
            workspace_id=actor.workspace_id,
            user_id=actor.user_id,
            delegation_id=actor.delegation_id,
            source_type="youtube",
            source_fingerprint=hashlib.sha256(key.encode()).hexdigest(),
            envelope={
                "source": {
                    "mode": "private",
                    "type": "youtube",
                    "display_name": f"Channel {index}",
                    "config": {
                        "url": _feed(CHANNEL_ONE),
                        "keep_latest_item": True,
                    },
                }
            },
        )

    with pytest.raises(AgentSourceResolutionLimitError):
        store.create_or_reuse_agent_source_resolution(
            workspace_id=actor.workspace_id,
            user_id=actor.user_id,
            delegation_id=actor.delegation_id,
            source_type="youtube",
            source_fingerprint=hashlib.sha256(b"overflow").hexdigest(),
            envelope={
                "source": {
                    "mode": "private",
                    "type": "youtube",
                    "display_name": "Overflow",
                    "config": {
                        "url": _feed(CHANNEL_TWO),
                        "keep_latest_item": True,
                    },
                }
            },
        )
