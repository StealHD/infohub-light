from src.services.apify_actor_ops import ApifyActorOpsService
from src.services.youtube_actor_source import provision_youtube_actor_sources
from src.services.source_type_registry import validate_source_config
from src.storage.service_store import ServiceStore


def test_worker_provisions_bound_free_discovery_for_youtube_channel(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    feed_url = (
        "https://www.youtube.com/feeds/videos.xml?"
        "channel_id=UCabcdefghijklmnopqrstuv"
    )
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Queued YouTube",
        config=validate_source_config("rss", {"url": feed_url}),
    )
    store.create_subscription(user_id=owner["id"], source_id=source_id)

    result = provision_youtube_actor_sources(store)

    ops = ApifyActorOpsService(store, workspace_id=workspace["id"])
    route = next(item for item in ops.list_routes() if item["route_key"] == "youtube/channel/items")
    binding = ops.get_source_binding(source_id)
    assert result == {"bound": 1, "discoveries": 1, "skipped": 0}
    assert binding["route_id"] == route["route_id"]
    run = store.connect().execute(
        """
        SELECT stage FROM apify_actor_discovery_runs
        WHERE workspace_id = ? AND route_id = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (workspace["id"], route["route_id"]),
    ).fetchone()
    assert run["stage"] == "queued"
    assert provision_youtube_actor_sources(store) == {
        "bound": 0,
        "discoveries": 0,
        "skipped": 0,
    }
