from src.services.actorops.repository import ActorOpsRepository
from src.services.youtube_actor_source import provision_youtube_actor_sources
from src.services.source_type_registry import validate_source_config
from src.storage.service_store import ServiceStore
from tests.test_actorops_v1_retirement_boundary import (
    install_actorops_v1_deny_authorizer,
)


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

    uninstall = install_actorops_v1_deny_authorizer(store.connect())
    try:
        result = provision_youtube_actor_sources(store)
    finally:
        uninstall()

    repository = ActorOpsRepository(store.connect(), workspace["id"])
    route_id = str(
        store.connect().execute(
            """SELECT route_id FROM actor_routes_v2
               WHERE workspace_id=? AND platform='youtube'""",
            (workspace["id"],),
        ).fetchone()["route_id"]
    )
    route = repository.get_route(route_id)
    binding = repository.get_binding(source_id)
    assert result == {"bound": 1, "discoveries": 1, "skipped": 0}
    assert binding.route_id == route.route_id
    assert binding.status == "pending"
    assert store.get_source(source_id)["enabled"] is False
    run = store.connect().execute(
        """
        SELECT status, stage FROM actor_discovery_jobs_v2
        WHERE workspace_id = ? AND route_id = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (workspace["id"], route.route_id),
    ).fetchone()
    assert run["status"] == "queued"
    assert run["stage"] == "store_search"
    job = store.connect().execute(
        """SELECT job_type FROM fetch_jobs
           WHERE workspace_id=? ORDER BY created_at DESC LIMIT 1""",
        (workspace["id"],),
    ).fetchone()
    assert job["job_type"] == "actorops_v2_discovery"
    uninstall = install_actorops_v1_deny_authorizer(store.connect())
    try:
        assert provision_youtube_actor_sources(store) == {
            "bound": 0,
            "discoveries": 0,
            "skipped": 0,
        }
    finally:
        uninstall()
