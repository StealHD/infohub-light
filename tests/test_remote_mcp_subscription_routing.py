from __future__ import annotations

import asyncio

import pytest

from tests.remote_mcp_subscription_routing_cases import (
    CREATE_CASES,
    DIRECT_CONFIG_TYPES,
)
from tests.remote_mcp_subscription_service_test_support import *  # noqa: F403


@pytest.mark.parametrize("source_type", DIRECT_CONFIG_TYPES)
def test_resolver_fallback_can_prepare_and_apply(context, source_type):
    service = context["service"]
    actor = _actor(context, "member")
    response = asyncio.run(
        service.resolve_source(
            actor=actor,
            source_type=source_type,
            input_value="audit public target",
        )
    )

    assert response["status"] == "configuration_required"
    prepared = service.prepare_create_subscription(
        actor=actor,
        source={
            "mode": "private",
            "type": source_type,
            "display_name": "Audit " + source_type,
            "config": CREATE_CASES[source_type],
        },
        subscription={},
        schedule=None,
    )
    assert context["store"].list_user_subscriptions(actor.user_id) == []

    applied = service.apply_subscription_change(
        actor=actor,
        proposal_id=prepared["proposal_id"],
        confirmation_text=prepared["confirmation_text"],
    )

    assert applied["result"]["subscription_id"]
    assert len(context["store"].list_user_subscriptions(actor.user_id)) == 1
    assert (
        context["store"]
        .connect()
        .execute("SELECT COUNT(*) FROM fetch_jobs")
        .fetchone()[0]
        == 0
    )
