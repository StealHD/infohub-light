"""Visible but disabled identities are not advertised as new sources."""

import pytest

from tests.test_source_resolution import CHANNEL_ONE, _feed, _resolve, context  # noqa: F401


@pytest.mark.parametrize("scope", ["private", "workspace"])
def test_disabled_source_has_no_creation_reference(context, scope):
    store = context["store"]
    store.create_source(
        workspace_id=context["workspace"]["id"], scope=scope,
        owner_user_id=context["member"]["id"], source_type="rss",
        display_name="Disabled channel", config={"url": _feed(CHANNEL_ONE)},
        source_key=f"rss:{_feed(CHANNEL_ONE)}", enabled=False,
    )
    candidate = _resolve(context)["candidates"][0]
    assert candidate["subscription_state"] == "disabled"
    assert "resolution_ref" not in candidate
