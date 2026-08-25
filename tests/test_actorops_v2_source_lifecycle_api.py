from __future__ import annotations

from pathlib import Path

from src.apify_actor_identity import source_target_fingerprint
from src.services.actorops.binding_service import (
    ActorOpsBindingError,
    ActorOpsBindingService,
)
from tests.test_actorops_v1_retirement_boundary import (
    install_actorops_v1_deny_authorizer,
)
from tests.api_service_test_support import client as build_client
from tests.api_service_test_support import login


def test_source_catalog_keeps_free_types_available_without_actorops_schema(
    tmp_path: Path, monkeypatch
) -> None:
    client, _data_dir = build_client(tmp_path, monkeypatch)
    login(client)
    connection = client.app.state.service_store.connect()
    connection.execute(
        "ALTER TABLE actor_routes_v2 RENAME TO actor_routes_v2_unavailable"
    )
    connection.commit()

    response = client.get("/api/catalog/source-types")

    assert response.status_code == 200, response.text
    types = {
        item["type"]: item for item in response.json()["data"]["source_types"]
    }
    assert {"rss", "github_release"}.issubset(types)
    assert types["x_profile"]["availability"] == "temporarily_unavailable"
    assert types["instagram_profile"]["availability"] == (
        "temporarily_unavailable"
    )


def test_youtube_channel_is_canonical_idempotent_and_auto_enabled_on_subscribe(
    tmp_path: Path, monkeypatch
) -> None:
    client, _data_dir = build_client(tmp_path, monkeypatch)
    login(client)
    store = client.app.state.service_store
    channel_id = "UCabcdefghijklmnopqrstuv"
    canonical = (
        "https://www.youtube.com/feeds/videos.xml?"
        f"channel_id={channel_id}"
    )
    payload = {
        "type": "youtube_channel",
        "display_name": "YouTube Channel",
        "config": {"url": channel_id},
    }

    first = client.post("/api/catalog/sources", json=payload)
    second = client.post(
        "/api/catalog/sources",
        json={
            **payload,
            "display_name": "Same Channel",
            "config": {"url": f"https://youtube.com/channel/{channel_id}"},
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    source = second.json()["data"]
    assert source["id"] == first.json()["data"]["id"]
    assert source["type"] == "rss"
    assert source["setup_type"] == "youtube_channel"
    assert source["source_key"] == f"rss:{canonical}"
    assert source["config"]["url"] == canonical
    assert source["config"]["keep_latest_item"] is True
    assert store.get_source(source["id"])["enforce_public_network"] is True
    assert source["enabled"] is False
    binding = ActorOpsBindingService(
        store, workspace_id=source["workspace_id"]
    ).repository.get_binding(source["id"])
    assert binding.status == "ready"
    subscribed = client.post(
        f"/api/catalog/sources/{source['id']}/subscribe"
    )
    assert subscribed.status_code == 200, subscribed.text
    assert subscribed.json()["data"]["source_activation"]["state"] == "enabled"
    assert store.get_source(source["id"])["enabled"] is True
    assert client.get("/api/jobs").json()["data"]["jobs"] == []


def test_platform_source_crud_uses_only_v2_bindings_with_v1_denied(
    tmp_path: Path, monkeypatch
) -> None:
    client, _data_dir = build_client(tmp_path, monkeypatch)
    login(client)
    store = client.app.state.service_store
    uninstall = install_actorops_v1_deny_authorizer(store.connect())
    try:
        payloads = (
            (
                "x_profile",
                {"target": "@OpenAI", "fetch_limit": 3},
            ),
            (
                "instagram_profile",
                {"target": "@sooyaaa__"},
            ),
            (
                "youtube_channel",
                {
                    "url": (
                        "https://www.youtube.com/feeds/videos.xml?"
                        "channel_id=UCabcdefghijklmnopqrstuv"
                    )
                },
            ),
        )
        source_ids: list[str] = []
        for setup_type, config in payloads:
            response = client.post(
                "/api/catalog/sources",
                json={
                    "scope": "workspace",
                    "type": setup_type,
                    "display_name": setup_type,
                    "config": config,
                    "enabled": True,
                },
            )
            assert response.status_code == 200, response.text
            source = response.json()["data"]
            source_ids.append(source["id"])
            assert source["enabled"] is False
            if setup_type == "instagram_profile":
                assert source["config"]["fetch_limit"] == 3
            subscribed = client.post(
                f"/api/catalog/sources/{source['id']}/subscribe"
            )
            assert subscribed.status_code == 200, subscribed.text
            assert subscribed.json()["data"]["subscription"]["source_id"] == (
                source["id"]
            )
            binding = store.connect().execute(
                """SELECT status, binding_version
                   FROM actor_source_bindings_v2 WHERE source_id=?""",
                (source["id"],),
            ).fetchone()
            expected_status = "ready" if setup_type == "youtube_channel" else "pending"
            assert dict(binding) == {
                "status": expected_status,
                "binding_version": 1,
            }
            activation = subscribed.json()["data"]["source_activation"]
            assert activation["state"] == (
                "enabled" if setup_type == "youtube_channel" else "preparing"
            )

        x_source_id = source_ids[0]
        metadata_patch = client.patch(
            f"/api/catalog/sources/{x_source_id}",
            json={
                "display_name": "Renamed X",
                "config": {"fetch_limit": 9},
            },
        )
        assert metadata_patch.status_code == 200, metadata_patch.text
        assert store.connect().execute(
            """SELECT binding_version FROM actor_source_bindings_v2
               WHERE source_id=?""",
            (x_source_id,),
        ).fetchone()["binding_version"] == 1

        target_patch = client.patch(
            f"/api/catalog/sources/{x_source_id}",
            json={"config": {"target": "another_user"}},
        )
        assert target_patch.status_code == 200, target_patch.text
        assert store.connect().execute(
            """SELECT status, binding_version FROM actor_source_bindings_v2
               WHERE source_id=?""",
            (x_source_id,),
        ).fetchone()["binding_version"] == 2

        disabled_subscription = store.create_subscription(
            user_id=store.get_user_by_username("owner")["id"],
            source_id=x_source_id,
            enabled=False,
        )
        updated_subscription = client.patch(
            f"/api/me/subscriptions/{disabled_subscription['id']}",
            json={"enabled": True},
        )
        assert updated_subscription.status_code == 200, updated_subscription.text
        assert store.get_source(x_source_id)["enabled"] is False

        deleted = client.delete(f"/api/catalog/sources/{x_source_id}")
        assert deleted.status_code == 200, deleted.text
        final = store.connect().execute(
            """SELECT status, binding_version FROM actor_source_bindings_v2
               WHERE source_id=?""",
            (x_source_id,),
        ).fetchone()
        assert dict(final) == {"status": "disabled", "binding_version": 3}
    finally:
        uninstall()


def test_target_patch_rolls_back_source_and_binding_on_midway_failure(
    tmp_path: Path, monkeypatch
) -> None:
    client, _data_dir = build_client(tmp_path, monkeypatch)
    login(client)
    store = client.app.state.service_store
    created = client.post(
        "/api/catalog/sources",
        json={
            "scope": "workspace",
            "type": "instagram_profile",
            "display_name": "Atomic binding",
            "config": {"target": "openai"},
        },
    ).json()["data"]
    source_before = store.get_source(created["id"])
    binding_before = dict(
        store.connect().execute(
            """SELECT * FROM actor_source_bindings_v2 WHERE source_id=?""",
            (created["id"],),
        ).fetchone()
    )

    def fail_rebind(_self, _source_id):
        raise ActorOpsBindingError("actorops_v2_injected_failure")

    monkeypatch.setattr(ActorOpsBindingService, "rebind", fail_rebind)
    failed = client.patch(
        f"/api/catalog/sources/{created['id']}",
        json={"config": {"target": "another"}},
    )
    assert failed.status_code == 409
    assert store.get_source(created["id"])["config"] == source_before["config"]
    binding_after = dict(
        store.connect().execute(
            """SELECT * FROM actor_source_bindings_v2 WHERE source_id=?""",
            (created["id"],),
        ).fetchone()
    )
    assert binding_after == binding_before


def test_legacy_profile_id_is_normalized_through_existing_v2_binding(
    tmp_path: Path, monkeypatch
) -> None:
    client, _data_dir = build_client(tmp_path, monkeypatch)
    login(client)
    store = client.app.state.service_store
    workspace_id = store.get_default_workspace()["id"]
    source_id = store.create_source(
        workspace_id=workspace_id,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="Migrated X source",
        config={
            "profile_id": "legacy-v1-x-route",
            "target": "OpenAI",
            "fetch_limit": 3,
        },
        enabled=False,
    )
    route_id = str(
        store.connect().execute(
            """SELECT route_id FROM actor_routes_v2
               WHERE workspace_id=? AND platform='x'""",
            (workspace_id,),
        ).fetchone()["route_id"]
    )
    stamp = "2026-08-22T00:00:00+00:00"
    store.connect().execute(
        """INSERT INTO actor_source_bindings_v2 (
               binding_id, workspace_id, source_id, route_id,
               target_fingerprint, status, binding_version, created_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, 'pending', 1, ?, ?)""",
        (
            "migrated-v2-binding",
            workspace_id,
            source_id,
            route_id,
            source_target_fingerprint(
                workspace_id, route_id, "OpenAI", platform="x"
            ),
            stamp,
            stamp,
        ),
    )
    store.connect().commit()

    uninstall = install_actorops_v1_deny_authorizer(store.connect())
    try:
        response = client.patch(
            f"/api/catalog/sources/{source_id}",
            json={"config": {"fetch_limit": 8}},
        )
    finally:
        uninstall()
    assert response.status_code == 200, response.text
    stored = store.get_source(source_id)
    assert "profile_id" not in stored["config"]
    assert stored["config"] | {"enabled": True} == {
        "platform": "x",
        "kind": "profile",
        "target": "OpenAI",
        "fetch_limit": 8,
        "analysis_mode": "full",
        "enabled": True,
    }
    assert store.connect().execute(
        """SELECT binding_version FROM actor_source_bindings_v2
           WHERE source_id=?""",
        (source_id,),
    ).fetchone()["binding_version"] == 1
