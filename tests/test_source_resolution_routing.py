import asyncio
import socket

import pytest

from src.services.source_resolution import SourceResolutionService
from src.services.source_type_registry import (
    SourceConfigError,
    get_source_setup_guide,
)
from tests.remote_mcp_subscription_routing_cases import DIRECT_CONFIG_TYPES


@pytest.mark.parametrize("source_type", DIRECT_CONFIG_TYPES)
def test_wrong_resolver_routes_back_to_configuration(source_type, monkeypatch):
    def deny_connect(*args, **kwargs):
        pytest.fail("unsupported resolver must not connect")

    monkeypatch.setattr(socket.socket, "connect", deny_connect)
    marker = "private-input-that-must-not-be-reflected"
    result = asyncio.run(
        SourceResolutionService(None).resolve(
            actor=None,
            source_type=source_type,
            input_value=marker,
        )
    )

    assert result["status"] == "configuration_required"
    assert result["reason_code"] == "resolver_not_supported"
    assert result["next_step"] == {
        "tool": "get_source_setup_guide",
        "arguments": {"source_type": source_type},
    }
    assert result["candidates"] == [] and result["returned"] == 0
    assert "resolution_ref" not in result
    assert marker not in repr(result)


@pytest.mark.parametrize("source_type", DIRECT_CONFIG_TYPES)
def test_direct_guide_has_explicit_resolution_capability(source_type):
    detail = get_source_setup_guide(source_type)["source_type"]
    summary = next(
        item
        for item in get_source_setup_guide()["source_types"]
        if item["type"] == source_type
    )

    assert detail["resolution"] == summary["resolution"] == {
        "supported": False
    }
    assert detail["self_service"] and not detail["requires_web_setup"]


def test_resolution_capability_isolated_and_matches_default_adapters():
    guide = get_source_setup_guide()
    supported = {
        item["type"]
        for item in guide["source_types"]
        if item["resolution"]["supported"]
    }
    service = SourceResolutionService(None)

    assert supported == set(service.adapters) == {"youtube"}
    youtube = next(
        item for item in guide["source_types"] if item["type"] == "youtube"
    )
    youtube["resolution"]["official_hosts"].append("example.com")
    fresh = next(
        item
        for item in get_source_setup_guide()["source_types"]
        if item["type"] == "youtube"
    )
    assert fresh["resolution"]["official_hosts"] == ["www.youtube.com"]


def test_apify_and_aliases_keep_their_distinct_routing():
    apify = asyncio.run(
        SourceResolutionService(None).resolve(
            actor=None, source_type="apify", input_value="public target"
        )
    )
    assert apify["status"] == "web_setup_required"

    for alias, canonical in (
        ("github_release", "github"),
        ("reddit_subreddit", "reddit"),
        ("telegram_channel", "telegram"),
        ("x_profile", "twitter"),
        ("instagram_profile", "instagram"),
        ("hacker_news", "hackernews"),
    ):
        result = asyncio.run(
            SourceResolutionService(None).resolve(
                actor=None, source_type=alias, input_value="public target"
            )
        )
        assert result["status"] == "configuration_required"
        assert result["source_type"] == canonical


def test_unknown_type_is_still_rejected():
    with pytest.raises(SourceConfigError):
        asyncio.run(
            SourceResolutionService(None).resolve(
                actor=None,
                source_type="unknown",
                input_value="public target",
            )
        )


class _UnrelatedAdapter:
    source_type = "rss"


def test_declared_resolver_without_registered_adapter_is_unavailable():
    service = SourceResolutionService(None, adapters=(_UnrelatedAdapter(),))
    result = asyncio.run(
        service.resolve(
            actor=None,
            source_type="youtube",
            input_value="channel name",
        )
    )

    assert result["status"] == "unavailable"
    assert result["candidates"] == []
