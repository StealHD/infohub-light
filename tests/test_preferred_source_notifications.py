from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import httpx
import pytest

import src.services.preferred_source_notifications as notification_module
from src.services.job_queue import JobQueue
from src.services.network_policy import (
    UnsafeNetworkTarget,
    fetch_public_http,
    post_public_http,
    resolve_public_http_url,
)
from src.services.preferred_source_notifications import (
    NotificationServiceError,
    PreferredSourceNotificationService,
)
from src.services.secret_store import SecretStore
from src.services.user_feed_store import UserFeedStore
from src.services.worker import run_worker_once
from src.storage.service_store import ServiceStore


WATERMARK = "2020-01-01T00:00:00+00:00"
NEW_PUBLISHED_AT = "2026-07-24T00:00:01+00:00"
OLD_PUBLISHED_AT = WATERMARK


def _public_dns_answers(
    _host: str,
    port: int,
    *,
    type: int,
) -> list[tuple[int, int, int, str, tuple[str, int]]]:
    assert type == socket.SOCK_STREAM
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", port)),
    ]


def _notification_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    user = store.get_user_by_username("owner")
    assert workspace is not None
    assert user is not None
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=user["id"],
        source_type="rss",
        display_name="Preferred Feed",
        config={"name": "Preferred Feed", "url": "https://example.com/feed.xml"},
    )
    subscription = store.create_subscription(
        user_id=user["id"],
        source_id=source_id,
        notify_on_new_items=True,
    )
    service = PreferredSourceNotificationService(store, data_dir=str(tmp_path))
    service.upsert_settings(
        workspace_id=workspace["id"],
        user_id=user["id"],
        enabled=True,
        channel="webhook",
        webhook_url="https://hooks.example.com/inteliscope",
    )
    store.connect().execute(
        """
        UPDATE user_notification_settings
        SET notification_enabled_at = ?
        WHERE workspace_id = ? AND user_id = ?
        """,
        (WATERMARK, workspace["id"], user["id"]),
    )
    store.connect().execute(
        """
        UPDATE user_subscriptions
        SET notification_enabled_at = ?
        WHERE id = ?
        """,
        (WATERMARK, subscription["id"]),
    )
    store.connect().execute(
        """
        UPDATE user_notification_channels
        SET enabled_at = ?
        WHERE workspace_id = ? AND user_id = ? AND channel = 'webhook'
        """,
        (WATERMARK, workspace["id"], user["id"]),
    )
    store.connect().commit()
    return {
        "store": store,
        "workspace": workspace,
        "user": user,
        "source_id": source_id,
        "subscription_id": subscription["id"],
        "service": service,
    }


def _job(context: dict[str, Any]) -> dict[str, Any]:
    return JobQueue(context["store"]).create_job(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
        source_id=context["source_id"],
        subscription_id=context["subscription_id"],
        job_type="source_fetch",
        payload={},
    )


def _item(
    context: dict[str, Any],
    article_id: str,
    *,
    published_at: str = NEW_PUBLISHED_AT,
    analysis_mode: str = "full",
    url: str | None = None,
) -> dict[str, Any]:
    return {
        "id": article_id,
        "title": f"Title {article_id}",
        "summary_zh": f"Summary {article_id}",
        "url": url or f"https://example.com/articles/{article_id}",
        "published_at": published_at,
        "source_id": context["source_id"],
        "source": "rss",
        "subscription_id": context["subscription_id"],
        "subscription_ids": [context["subscription_id"]],
        "analysis_mode": analysis_mode,
    }


def _save_snapshot(
    context: dict[str, Any],
    job: dict[str, Any],
    items: list[dict[str, Any]],
    *,
    generated_at: str,
) -> dict[str, Any]:
    store = context["store"]
    if not store.connect().in_transaction:
        store.connect().execute("BEGIN IMMEDIATE")
    return UserFeedStore(store).save_snapshot(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
        job_id=job["id"],
        payload={
            "schema_version": 2,
            "run_id": f"run-{job['id']}",
            "run_status": "succeeded",
            "generated_at": generated_at,
            "items": items,
        },
        commit=False,
    )


def _count(store: ServiceStore, table: str) -> int:
    allowed = {
        "fetch_jobs",
        "preferred_source_notification_deliveries",
        "user_feed_snapshots",
    }
    assert table in allowed
    row = store.connect().execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    return int(row["count"])


def test_public_post_never_replays_transport_error_but_get_keeps_failover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns_answers)
    post_hosts: list[str] = []

    def failed_post(request: httpx.Request) -> httpx.Response:
        post_hosts.append(str(request.url.host))
        raise httpx.ConnectError("response was lost", request=request)

    with pytest.raises(httpx.ConnectError):
        asyncio.run(
            post_public_http(
                "https://notify.example.test/hook",
                content=b"{}",
                transport_factory=lambda: httpx.MockTransport(failed_post),
            )
        )

    assert post_hosts == ["93.184.216.34"]

    get_hosts: list[str] = []

    def failover_get(request: httpx.Request) -> httpx.Response:
        host = str(request.url.host)
        get_hosts.append(host)
        if host == "93.184.216.34":
            raise httpx.ConnectError("first address unavailable", request=request)
        return httpx.Response(200, content=b"ok")

    response = asyncio.run(
        fetch_public_http(
            "https://feeds.example.test/feed.xml",
            transport_factory=lambda: httpx.MockTransport(failover_get),
        )
    )

    assert response.status_code == 200
    assert response.content == b"ok"
    assert get_hosts == ["93.184.216.34", "1.1.1.1"]


def test_public_post_accepts_compressed_response_without_reading_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns_answers)
    response_body_read = False

    class MustNotReadBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal response_body_read
            response_body_read = True
            raise AssertionError("POST response body must not be consumed")
            yield b"unreachable"

        async def aclose(self) -> None:
            return None

    def oversized_compressed_response(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(
            200,
            headers={
                "content-encoding": "gzip",
                "content-length": "999999999",
            },
            stream=MustNotReadBody(),
        )

    response = asyncio.run(
        post_public_http(
            "https://notify.example.test/hook",
            content=b'{"event":"new-items"}',
            max_response_bytes=1,
            transport_factory=lambda: httpx.MockTransport(
                oversized_compressed_response
            ),
        )
    )

    assert response.status_code == 200
    assert response.content == b""
    assert response_body_read is False


def test_public_post_accepts_oversized_identity_response_without_reading_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns_answers)
    response_body_read = False

    class MustNotReadBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal response_body_read
            response_body_read = True
            raise AssertionError("POST response body must not be consumed")
            yield b"unreachable"

        async def aclose(self) -> None:
            return None

    def oversized_identity_response(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(
            200,
            headers={
                "content-encoding": "identity",
                "content-length": "999999999",
            },
            stream=MustNotReadBody(),
        )

    response = asyncio.run(
        post_public_http(
            "https://notify.example.test/hook",
            content=b'{"event":"new-items"}',
            max_response_bytes=1,
            transport_factory=lambda: httpx.MockTransport(
                oversized_identity_response
            ),
        )
    )

    assert response.status_code == 200
    assert response.content == b""
    assert response_body_read is False


def test_public_post_rejects_any_private_dns_answer_even_if_rss_allowlisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "HORIZON_MEMBER_RSS_HOST_ALLOWLIST",
        "notify.example.test",
    )

    def mixed_dns_answers(
        _host: str,
        port: int,
        *,
        type: int,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        assert type == socket.SOCK_STREAM
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("93.184.216.34", port),
            ),
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("127.0.0.1", port),
            ),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", mixed_dns_answers)
    transport_created = False

    def forbidden_transport() -> httpx.MockTransport:
        nonlocal transport_created
        transport_created = True
        return httpx.MockTransport(
            lambda _request: pytest.fail(
                "private DNS target reached the network transport"
            )
        )

    with pytest.raises(UnsafeNetworkTarget):
        asyncio.run(
            post_public_http(
                "https://notify.example.test/hook",
                content=b"{}",
                transport_factory=forbidden_transport,
            )
        )

    assert transport_created is False


def test_public_post_dns_resolution_obeys_deadline_without_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver_started = threading.Event()
    release_resolver = threading.Event()
    transport_created = False

    def blocked_dns(
        _host: str,
        port: int,
        *,
        type: int,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        assert type == socket.SOCK_STREAM
        resolver_started.set()
        assert release_resolver.wait(timeout=5)
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("93.184.216.34", port),
            )
        ]

    def forbidden_transport() -> httpx.MockTransport:
        nonlocal transport_created
        transport_created = True
        return httpx.MockTransport(
            lambda _request: pytest.fail(
                "DNS timeout reached the network transport"
            )
        )

    monkeypatch.setattr(socket, "getaddrinfo", blocked_dns)
    started_at = time.monotonic()
    try:
        with pytest.raises(UnsafeNetworkTarget, match="resolution timed out"):
            asyncio.run(
                post_public_http(
                    "https://notify.example.test/hook",
                    content=b"{}",
                    timeout=0.05,
                    transport_factory=forbidden_transport,
                )
            )
    finally:
        release_resolver.set()
    elapsed = time.monotonic() - started_at

    assert resolver_started.is_set()
    assert elapsed < 0.5
    assert transport_created is False


def test_public_url_resolution_normalizes_invalid_idna_and_dns_oserror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(UnsafeNetworkTarget, match="valid DNS name"):
        resolve_public_http_url("https://\ud800.example/hook")

    def failed_dns(
        _host: str,
        _port: int,
        *,
        type: int,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        assert type == socket.SOCK_STREAM
        raise OSError("resolver unavailable")

    monkeypatch.setattr(socket, "getaddrinfo", failed_dns)

    with pytest.raises(UnsafeNetworkTarget, match="could not be resolved"):
        resolve_public_http_url("https://notify.example.test/hook")


def test_settings_projection_is_value_free_and_webhook_is_secret_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    store = context["store"]
    service = context["service"]
    workspace_id = context["workspace"]["id"]
    user_id = context["user"]["id"]
    secret_url = "https://hooks.example.com/inteliscope"

    public = service.get_public_settings(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    assert set(public) == {
        "schema_version",
        "enabled",
        "target_ids",
        "selected_targets",
        "channels",
        "channel",
        "channel_states",
        "email_configured",
        "email_transport_ready",
        "webhook_configured",
        "webhook_provider",
        "webhook_provider_explicit",
        "webhook_signing_secret_configured",
        "webhook_verification_mode",
        "webhook_provider_options",
        "telegram_configured",
        "telegram_transport_ready",
        "last_test_status",
        "last_tested_at",
        "last_test_error_code",
        "updated_at",
    }
    assert public["schema_version"] == 4
    assert {
        "email_address",
        "webhook_url",
        "webhook_env_name",
        "webhook_secret_digest",
        "webhook_signing_env_name",
        "webhook_signing_secret_digest",
        "notification_enabled_at",
        "notification_generation",
        "last_test_attempted_at",
        "created_at",
    }.isdisjoint(public)
    assert public["webhook_configured"] is True
    assert public["webhook_provider"] == "generic_event"
    assert public["webhook_provider_explicit"] is False
    assert public["webhook_signing_secret_configured"] is False
    assert public["webhook_verification_mode"] == "http_status"
    assert len(public["webhook_provider_options"]) == 7

    internal = store.get_user_notification_settings(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    assert internal is not None
    env_name = str(internal["webhook_env_name"])
    assert env_name.startswith("HORIZON_USER_WEBHOOK_")
    assert secret_url not in repr(internal)
    assert SecretStore(tmp_path).read() == {env_name: secret_url}
    assert secret_url.encode() not in store.db_path.read_bytes()

    with pytest.raises(NotificationServiceError) as exc_info:
        service.upsert_settings(
            workspace_id=workspace_id,
            user_id=user_id,
            webhook_url="http://hooks.example.com/not-tls",
        )
    assert exc_info.value.code == "invalid_notification_destination"
    assert SecretStore(tmp_path).read() == {env_name: secret_url}

    with pytest.raises(NotificationServiceError) as exc_info:
        service.upsert_settings(
            workspace_id=workspace_id,
            user_id=user_id,
            webhook_url="https://\ud800.example/hook",
        )
    assert exc_info.value.code == "invalid_notification_destination"
    assert SecretStore(tmp_path).read() == {env_name: secret_url}


def test_deleted_webhook_secret_never_falls_back_to_process_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    store = context["store"]
    service = context["service"]
    workspace_id = context["workspace"]["id"]
    user_id = context["user"]["id"]
    settings = store.get_user_notification_settings(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    assert settings is not None
    env_name = str(settings["webhook_env_name"])
    stale_url = "https://hooks.example.com/stale-process-value"
    SecretStore(tmp_path).delete(env_name)
    monkeypatch.setenv(env_name, stale_url)

    public = service.get_public_settings(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    assert public["webhook_configured"] is False

    baseline_job = _job(context)
    baseline = _save_snapshot(
        context,
        baseline_job,
        [_item(context, "baseline")],
        generated_at="2026-07-24T00:01:00+00:00",
    )
    assert service.stage_for_job(
        job=baseline_job,
        snapshot_id=baseline["id"],
        snapshot_created=True,
    ) == 0
    store.connect().commit()
    current_job = _job(context)
    current = _save_snapshot(
        context,
        current_job,
        [_item(context, "baseline"), _item(context, "must-not-stage")],
        generated_at="2026-07-24T00:02:00+00:00",
    )
    assert service.stage_for_job(
        job=current_job,
        snapshot_id=current["id"],
        snapshot_created=True,
    ) == 0
    store.connect().commit()
    assert _count(store, "preferred_source_notification_deliveries") == 0
    network_called = False

    async def forbidden_post(*_args: Any, **_kwargs: Any) -> httpx.Response:
        nonlocal network_called
        network_called = True
        pytest.fail("deleted webhook secret fell back to process environment")

    monkeypatch.setattr(
        "src.services.preferred_source_notifications.post_public_http",
        forbidden_post,
    )
    payload = service._delivery_payload(
        {
            "title": "Deleted webhook secret",
            "published_at": NEW_PUBLISHED_AT,
            "url": "https://example.com/safe-article",
        },
        article_id="deleted-webhook-secret",
        source_name="Inteliscope",
        test=True,
    )
    with pytest.raises(NotificationServiceError) as direct_error:
        service._send_webhook(settings, payload)
    assert direct_error.value.code == "notification_destination_required"

    with pytest.raises(NotificationServiceError) as test_error:
        service.send_test(
            workspace_id=workspace_id,
            user_id=user_id,
        )
    assert test_error.value.code == "notification_test_failed"
    stored = store.get_user_notification_settings(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    assert stored is not None
    assert stored["last_test_error_code"] == "notification_destination_required"
    assert network_called is False


def test_provider_and_signing_rotation_is_write_only_and_invalidates_test(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    store = context["store"]
    service = context["service"]
    workspace_id = context["workspace"]["id"]
    user_id = context["user"]["id"]
    before = store.get_user_notification_settings(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    assert before is not None
    before_webhook = store.get_user_notification_channel(
        workspace_id=workspace_id,
        user_id=user_id,
        channel="webhook",
    )
    assert before_webhook is not None
    store.record_user_notification_test(
        workspace_id=workspace_id,
        user_id=user_id,
        status="sent",
    )
    webhook_url = (
        "https://open.feishu.cn/open-apis/bot/v2/hook/"
        "00000000-0000-0000-0000-000000000000"
    )
    signing_secret = "write-only-signing-secret"

    public = service.upsert_settings(
        workspace_id=workspace_id,
        user_id=user_id,
        webhook_provider="feishu_lark_v2",
        webhook_url=webhook_url,
        webhook_signing_secret=signing_secret,
    )

    assert public["webhook_provider"] == "feishu_lark_v2"
    assert public["webhook_provider_explicit"] is True
    assert public["webhook_signing_secret_configured"] is True
    assert public["webhook_verification_mode"] == "provider_response"
    assert public["last_test_status"] is None
    assert webhook_url not in repr(public)
    assert signing_secret not in repr(public)
    internal = store.get_user_notification_settings(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    assert internal is not None
    assert internal["notification_generation"] == int(
        before["notification_generation"]
    )
    changed_webhook = store.get_user_notification_channel(
        workspace_id=workspace_id,
        user_id=user_id,
        channel="webhook",
    )
    assert changed_webhook is not None
    assert changed_webhook["generation"] == (
        int(before_webhook["generation"]) + 1
    )
    signing_env = service.webhook_signing_env_name(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    secrets = SecretStore(tmp_path).read()
    assert secrets[signing_env] == signing_secret
    assert signing_secret.encode() not in store.db_path.read_bytes()

    generation = int(internal["notification_generation"])
    cleared = service.upsert_settings(
        workspace_id=workspace_id,
        user_id=user_id,
        webhook_signing_secret=None,
    )
    assert cleared["webhook_signing_secret_configured"] is False
    after_clear = store.get_user_notification_settings(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    assert after_clear is not None
    assert after_clear["notification_generation"] == generation
    cleared_webhook = store.get_user_notification_channel(
        workspace_id=workspace_id,
        user_id=user_id,
        channel="webhook",
    )
    assert cleared_webhook is not None
    assert cleared_webhook["generation"] == (
        int(changed_webhook["generation"]) + 1
    )
    assert signing_env not in SecretStore(tmp_path).read()

    with pytest.raises(NotificationServiceError) as missing_url:
        service.upsert_settings(
            workspace_id=workspace_id,
            user_id=user_id,
            webhook_provider="slack",
        )
    assert (
        missing_url.value.code
        == "webhook_url_required_for_provider_change"
    )
    assert (
        service.get_public_settings(
            workspace_id=workspace_id,
            user_id=user_id,
        )["webhook_provider"]
        == "feishu_lark_v2"
    )


def test_provider_change_bumps_generation_while_notifications_are_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    service = context["service"]
    store = context["store"]
    workspace_id = context["workspace"]["id"]
    user_id = context["user"]["id"]
    service.upsert_settings(
        workspace_id=workspace_id,
        user_id=user_id,
        enabled=False,
    )
    disabled = store.get_user_notification_settings(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    assert disabled is not None
    disabled_webhook = store.get_user_notification_channel(
        workspace_id=workspace_id,
        user_id=user_id,
        channel="webhook",
    )
    assert disabled_webhook is not None

    service.upsert_settings(
        workspace_id=workspace_id,
        user_id=user_id,
        webhook_provider="generic_text",
        webhook_url="https://notify.example.test/text",
    )

    changed = store.get_user_notification_settings(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    assert changed is not None
    assert changed["enabled"] is False
    assert changed["notification_generation"] == int(
        disabled["notification_generation"]
    )
    changed_webhook = store.get_user_notification_channel(
        workspace_id=workspace_id,
        user_id=user_id,
        channel="webhook",
    )
    assert changed_webhook is not None
    assert changed_webhook["generation"] == (
        int(disabled_webhook["generation"]) + 1
    )


def test_explicit_clear_removes_an_unreferenced_webhook_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    store = context["store"]
    workspace_id = context["workspace"]["id"]
    user_id = context["user"]["id"]
    env_name = context["service"].webhook_env_name(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    assert SecretStore(tmp_path).read().get(env_name)

    store.connect().execute(
        "DELETE FROM user_notification_settings WHERE user_id = ?",
        (user_id,),
    )
    store.connect().commit()

    public = context["service"].upsert_settings(
        workspace_id=workspace_id,
        user_id=user_id,
        webhook_url=None,
    )

    assert public["webhook_configured"] is False
    assert env_name not in SecretStore(tmp_path).read()
    stored = store.get_user_notification_settings(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    assert stored is not None
    assert stored["webhook_env_name"] is None
    assert stored["webhook_secret_digest"] is None


def test_partial_settings_patch_after_disable_does_not_reenable_notifications(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    workspace_id = context["workspace"]["id"]
    user_id = context["user"]["id"]
    admin_store = ServiceStore(tmp_path)
    admin_store.initialize()
    admin_store.upsert_user_notification_settings(
        workspace_id=workspace_id,
        user_id=user_id,
        enabled=False,
    )

    updated = context["service"].upsert_settings(
        workspace_id=workspace_id,
        user_id=user_id,
        email_address="new-reader@example.test",
    )

    assert updated["enabled"] is False
    stored = admin_store.get_user_notification_settings(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    assert stored is not None
    assert stored["enabled"] is False
    assert stored["notification_enabled_at"] is None
    assert stored["email_address"] == "new-reader@example.test"
    admin_store.close()


def test_stale_settings_patch_cannot_restore_notifications_after_user_disable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    workspace_id = context["workspace"]["id"]
    user_id = context["user"]["id"]
    admin_store = ServiceStore(tmp_path)
    admin_store.initialize()
    admin_store.update_user(user_id, enabled=False)

    with pytest.raises(NotificationServiceError) as exc_info:
        context["service"].upsert_settings(
            workspace_id=workspace_id,
            user_id=user_id,
            email_address="stale-reader@example.test",
        )

    assert exc_info.value.code == "notification_channel_unavailable"
    admin_store.update_user(user_id, enabled=True)
    stored = admin_store.get_user_notification_settings(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    assert stored is not None
    assert stored["enabled"] is False
    assert stored["notification_enabled_at"] is None
    assert stored["email_address"] is None
    admin_store.close()


def test_role_downgrade_rejects_patch_before_secret_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    workspace_id = context["workspace"]["id"]
    user_id = context["user"]["id"]
    service = context["service"]
    admin_store = ServiceStore(tmp_path)
    admin_store.initialize()
    before = SecretStore(tmp_path).read()
    admin_store.update_user(user_id, role="viewer")
    secret_mutated = False

    def forbidden_secret_set(_name: str, _value: str) -> None:
        nonlocal secret_mutated
        secret_mutated = True
        pytest.fail("viewer patch mutated SecretStore")

    monkeypatch.setattr(service.secret_store, "set", forbidden_secret_set)

    with pytest.raises(NotificationServiceError) as exc_info:
        service.upsert_settings(
            workspace_id=workspace_id,
            user_id=user_id,
            webhook_url="https://hooks.example.com/viewer-stale-patch",
        )

    assert exc_info.value.code == "notification_channel_unavailable"
    assert secret_mutated is False
    assert SecretStore(tmp_path).read() == before
    admin_store.close()


def test_settings_secret_is_restored_when_database_update_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    store = context["store"]
    service = context["service"]
    workspace_id = context["workspace"]["id"]
    user_id = context["user"]["id"]
    before = store.get_user_notification_settings(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    assert before is not None
    env_name = str(before["webhook_env_name"])
    old_url = str(SecretStore(tmp_path).read()[env_name])
    original_replace_many = service.secret_store.replace_many
    replace_calls = 0
    compensation_transaction_states: list[bool] = []

    def tracked_replace_many(
        updates: dict[str, str | None],
    ) -> None:
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 2:
            compensation_transaction_states.append(
                store.connect().in_transaction
            )
        original_replace_many(updates)

    monkeypatch.setattr(
        service.secret_store,
        "replace_many",
        tracked_replace_many,
    )

    monkeypatch.setattr(
        store,
        "upsert_user_notification_settings",
        lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError("simulated database update failure")
        ),
    )

    with pytest.raises(RuntimeError, match="simulated database update failure"):
        service.upsert_settings(
            workspace_id=workspace_id,
            user_id=user_id,
            webhook_url="https://hooks.example.com/replacement",
        )

    assert compensation_transaction_states == [True]
    assert SecretStore(tmp_path).read()[env_name] == old_url
    verification_store = ServiceStore(tmp_path)
    stored = verification_store.get_user_notification_settings(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    assert stored is not None
    assert stored["webhook_env_name"] == env_name
    verification_store.close()


def test_inflight_settings_patch_finishes_before_admin_disable_and_stays_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    workspace_id = context["workspace"]["id"]
    user_id = context["user"]["id"]
    stale_store = context["store"]
    service = context["service"]
    admin_store = ServiceStore(tmp_path)
    admin_store.initialize()
    patch_holds_lock = threading.Event()
    release_patch = threading.Event()
    disable_started = threading.Event()
    original_upsert = stale_store.upsert_user_notification_settings

    def blocked_upsert(**kwargs: Any) -> dict[str, Any]:
        patch_holds_lock.set()
        assert release_patch.wait(timeout=5)
        return original_upsert(**kwargs)

    def disable_user() -> dict[str, Any]:
        disable_started.set()
        return admin_store.update_user(user_id, enabled=False)

    monkeypatch.setattr(
        stale_store,
        "upsert_user_notification_settings",
        blocked_upsert,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        patch_future = executor.submit(
            service.upsert_settings,
            workspace_id=workspace_id,
            user_id=user_id,
            email_address="inflight-reader@example.test",
        )
        assert patch_holds_lock.wait(timeout=5)
        disable_future = executor.submit(disable_user)
        assert disable_started.wait(timeout=5)
        release_patch.set()
        assert patch_future.result(timeout=5)["enabled"] is True
        assert disable_future.result(timeout=5)["enabled"] is False

    stored = admin_store.get_user_notification_settings(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    assert stored is not None
    assert stored["enabled"] is False
    assert stored["notification_enabled_at"] is None
    admin_store.close()


def test_stage_uses_baseline_watermarks_personal_only_and_job_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    store = context["store"]
    service = context["service"]
    baseline_job = _job(context)
    baseline = _save_snapshot(
        context,
        baseline_job,
        [_item(context, "baseline")],
        generated_at="2026-07-24T00:01:00+00:00",
    )

    assert service.stage_for_job(
        job=baseline_job,
        snapshot_id=baseline["id"],
        snapshot_created=True,
    ) == 0
    store.connect().commit()
    assert _count(store, "preferred_source_notification_deliveries") == 0

    current_job = _job(context)
    unrelated_job = _job(context)
    current = _save_snapshot(
        context,
        current_job,
        [
            _item(context, "baseline"),
            _item(context, "eligible-new"),
            _item(context, "old-at-watermark", published_at=OLD_PUBLISHED_AT),
            _item(context, "private-only", analysis_mode="personal_only"),
        ],
        generated_at="2026-07-24T00:02:00+00:00",
    )

    assert service.stage_for_job(
        job=unrelated_job,
        snapshot_id=current["id"],
        snapshot_created=False,
    ) == 0
    assert service.stage_for_job(
        job=current_job,
        snapshot_id=current["id"],
        snapshot_created=True,
    ) == 1
    store.connect().commit()

    deliveries = store.list_preferred_source_notification_deliveries(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
    )
    assert [(row["article_id"], row["job_id"]) for row in deliveries] == [
        ("eligible-new", current_job["id"])
    ]


def test_same_job_retry_stages_only_new_delta_from_updated_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    store = context["store"]
    service = context["service"]
    baseline_job = _job(context)
    baseline = _save_snapshot(
        context,
        baseline_job,
        [_item(context, "baseline")],
        generated_at="2026-07-24T00:01:00+00:00",
    )
    assert service.stage_for_job(
        job=baseline_job,
        snapshot_id=baseline["id"],
        snapshot_created=True,
    ) == 0
    store.connect().commit()

    current_job = _job(context)
    current = _save_snapshot(
        context,
        current_job,
        [_item(context, "baseline"), _item(context, "first-attempt-new")],
        generated_at="2026-07-24T00:02:00+00:00",
    )
    assert current["snapshot_created"] is True
    assert service.stage_for_job(
        job=current_job,
        snapshot_id=current["id"],
        snapshot_created=True,
    ) == 1
    store.connect().commit()

    store.connect().execute("BEGIN IMMEDIATE")
    retry = UserFeedStore(store).save_snapshot(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
        job_id=current_job["id"],
        payload={
            "schema_version": 2,
            "run_id": f"retry-{current_job['id']}",
            "run_status": "partial",
            "generated_at": "2026-07-24T00:03:00+00:00",
            "items": [
                _item(context, "baseline"),
                _item(context, "first-attempt-new"),
                _item(context, "retry-only-new"),
            ],
        },
        commit=False,
    )
    assert retry["id"] == current["id"]
    assert retry["snapshot_created"] is False
    assert service.stage_for_job(
        job=current_job,
        snapshot_id=retry["id"],
        snapshot_created=False,
    ) == 1
    store.connect().commit()

    store.connect().execute("BEGIN IMMEDIATE")
    assert service.stage_for_job(
        job=current_job,
        snapshot_id=retry["id"],
        snapshot_created=False,
    ) == 0
    store.connect().commit()
    deliveries = store.list_preferred_source_notification_deliveries(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
    )
    assert sorted(delivery["article_id"] for delivery in deliveries) == [
        "first-attempt-new",
        "retry-only-new",
    ]


def test_dispatch_batches_at_most_twenty_and_sanitizes_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    store = context["store"]
    service = context["service"]
    baseline_job = _job(context)
    baseline = _save_snapshot(
        context,
        baseline_job,
        [_item(context, "baseline")],
        generated_at="2026-07-24T00:01:00+00:00",
    )
    assert service.stage_for_job(
        job=baseline_job,
        snapshot_id=baseline["id"],
        snapshot_created=True,
    ) == 0
    store.connect().commit()

    current_job = _job(context)
    new_items = [
        _item(
            context,
            f"new-{index:02d}",
            url=(
                "javascript:alert(document.domain)"
                if index == 0
                else f"https://example.com/new/{index}"
            ),
        )
        for index in range(22)
    ]
    current = _save_snapshot(
        context,
        current_job,
        [_item(context, "baseline"), *new_items],
        generated_at="2026-07-24T00:02:00+00:00",
    )
    assert service.stage_for_job(
        job=current_job,
        snapshot_id=current["id"],
        snapshot_created=True,
    ) == 22
    store.connect().commit()

    sent_payloads: list[dict[str, Any]] = []
    monkeypatch.setattr(
        service,
        "_send_payload",
        lambda _settings, payload: sent_payloads.append(payload),
    )

    summary = service.dispatch_pending(job_id=current_job["id"])

    assert summary == {"claimed": 20, "succeeded": 20, "failed": 0}
    assert len(sent_payloads) == 1
    assert sent_payloads[0]["kind"] == "new_items"
    assert len(sent_payloads[0]["items"]) == 20
    article_ids = [item["article_id"] for item in sent_payloads[0]["items"]]
    assert len(article_ids) == len(set(article_ids))
    malicious = next(
        item for item in sent_payloads[0]["items"] if item["article_id"] == "new-00"
    )
    assert malicious["url"] == ""
    assert [
        row["status"]
        for row in store.list_preferred_source_notification_deliveries(
            workspace_id=context["workspace"]["id"],
            user_id=context["user"]["id"],
        )
    ].count("pending") == 2

    duplicate_payload = service._batch_delivery_payload(
        [
            {"article_id": "same", "payload": {"article_id": "same"}},
            {"article_id": "same", "payload": {"article_id": "same"}},
        ]
    )
    assert duplicate_payload["items"] == [{"article_id": "same"}]


def test_webhook_transport_emits_new_items_event_with_deduplicated_items(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    service = context["service"]
    settings = context["store"].get_user_notification_settings(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
    )
    assert settings is not None
    payload = service._batch_delivery_payload(
        [
            {
                "article_id": "first",
                "payload": {
                    "article_id": "first",
                    "title": "First title",
                    "url": "https://example.com/first",
                },
            },
            {
                "article_id": "first",
                "payload": {
                    "article_id": "first",
                    "title": "Duplicate provenance",
                    "url": "https://example.com/duplicate",
                },
            },
            {
                "article_id": "second",
                "payload": {
                    "article_id": "second",
                    "title": "Second title",
                    "url": "https://example.com/second",
                },
            },
        ]
    )
    requests: list[dict[str, Any]] = []

    async def capture_post(url: str, **kwargs: Any) -> SimpleNamespace:
        requests.append(
            {
                "url": url,
                "headers": kwargs["headers"],
                "body": json.loads(kwargs["content"].decode("utf-8")),
            }
        )
        return SimpleNamespace(status_code=204, headers={})

    monkeypatch.setattr(notification_module, "post_public_http", capture_post)

    service._send_webhook(settings, payload)

    assert len(requests) == 1
    assert requests[0]["url"] == "https://hooks.example.com/inteliscope"
    assert requests[0]["headers"]["Content-Type"] == (
        "application/json; charset=utf-8"
    )
    assert requests[0]["body"] == {
        "event": "inteliscope.preferred_source.new_items",
        "data": {
            "schema_version": 1,
            "items": [
                {
                    "article_id": "first",
                    "title": "First title",
                    "url": "https://example.com/first",
                },
                {
                    "article_id": "second",
                    "title": "Second title",
                    "url": "https://example.com/second",
                },
            ],
        },
    }


def test_webhook_transport_emits_explicit_test_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    requests: list[dict[str, Any]] = []

    async def capture_post(_url: str, **kwargs: Any) -> SimpleNamespace:
        requests.append(json.loads(kwargs["content"].decode("utf-8")))
        return SimpleNamespace(status_code=200, headers={})

    monkeypatch.setattr(notification_module, "post_public_http", capture_post)

    assert context["service"].send_test(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
    ) == {
        "sent": True,
        "channel": "webhook",
        "provider": "generic_event",
        "verification": "http_accepted",
    }

    assert len(requests) == 1
    assert requests[0]["event"] == "inteliscope.preferred_source.test"
    assert requests[0]["data"]["test"] is True
    assert requests[0]["data"]["kind"] == "test"
    assert requests[0]["data"]["article_id"] == "notification-test"


@pytest.mark.parametrize(
    "webhook_host",
    (
        "open.feishu.cn",
        "open.larksuite.com",
        "OPEN.FEISHU.CN.",
        "open。feishu。cn",
    ),
)
def test_feishu_webhook_transport_emits_text_messages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    webhook_host: str,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    service = context["service"]
    service.upsert_settings(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
        webhook_url=(
            f"https://{webhook_host}/open-apis/bot/v2/hook/"
            "00000000-0000-0000-0000-000000000000"
        ),
    )
    settings = context["store"].get_user_notification_settings(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
    )
    assert settings is not None
    requests: list[dict[str, Any]] = []

    async def capture_post(_url: str, **kwargs: Any) -> httpx.Response:
        requests.append(json.loads(kwargs["content"].decode("utf-8")))
        return httpx.Response(200, json={"code": 0})

    monkeypatch.setattr(notification_module, "post_public_http", capture_post)

    service._send_webhook(
        settings,
        service._delivery_payload(
            {
                "title": "Inteliscope 推送测试",
                "summary_zh": "这是一条模拟的新内容通知。",
                "url": "https://example.com/notification-test",
                "published_at": "2026-07-29T13:50:26+00:00",
            },
            article_id="notification-test",
            source_name="Inteliscope",
            test=True,
        ),
    )
    items = [
        {
            "article_id": f"article-{index}",
            "payload": {
                "article_id": f"article-{index}",
                "source_name": "OpenAI News",
                "title": (
                    'A new release <at user_id="all">everyone</at>'
                    if index == 1
                    else f"Release {index}"
                ),
                "summary": "Release notes are available. " + ("x" * 600),
                "published_at": "2026-07-29T14:00:00+00:00",
                "url": f"https://example.com/release/{index}",
            },
        }
        for index in range(1, 21)
    ]
    service._send_webhook(
        settings,
        service._batch_delivery_payload(items),
    )

    assert len(requests) == 2
    assert requests[0]["msg_type"] == "text"
    assert "Inteliscope 新内容通知测试" in requests[0]["content"]["text"]
    assert "这是一条模拟的新内容通知。" in requests[0]["content"]["text"]
    assert "event" not in requests[0]
    assert requests[1]["msg_type"] == "text"
    text = requests[1]["content"]["text"]
    assert "Inteliscope 新内容通知（20 条）" in text
    assert "OpenAI News" in text
    assert "A new release" in text
    assert '＜at user_id="all"＞everyone＜/at＞' in text
    assert "<at" not in text
    assert "20. Release 20" in text
    assert len(text) <= 3_500


def test_email_transport_sends_one_message_containing_every_item(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    service = context["service"]
    sent_messages: list[Any] = []

    class FakeSMTP:
        def __init__(
            self,
            host: str,
            port: int,
            *,
            timeout: int,
            context: Any,
        ) -> None:
            assert (host, port, timeout) == ("smtp.resend.com", 465, 20)
            assert context is not None

        def __enter__(self) -> "FakeSMTP":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def login(self, username: str, password: str) -> None:
            assert username == "resend"
            assert password == "test-only-password"

        def send_message(self, message: Any) -> None:
            sent_messages.append(message)

    service.email_transport.smtp_factory = FakeSMTP
    service.email_transport.ssl_context_factory = lambda: object()
    service.email_transport.upsert(
        workspace_id=context["workspace"]["id"],
        actor_user_id=context["user"]["id"],
        provider="resend",
        sender_email="sender@example.test",
        sender_name="Inteliscope",
        credential="test-only-password",
    )
    service.email_transport.send_test(
        workspace_id=context["workspace"]["id"],
        actor_user_id=context["user"]["id"],
        recipient_email="reader@example.test",
    )
    service.email_transport.upsert(
        workspace_id=context["workspace"]["id"],
        actor_user_id=context["user"]["id"],
        enabled=True,
    )
    sent_messages.clear()

    service._send_email(
        {
            "workspace_id": context["workspace"]["id"],
            "email_address": "reader@example.test",
        },
        {
            "kind": "new_items",
            "items": [
                {
                    "article_id": "first",
                    "source_name": "Source A",
                    "title": "First title",
                    "summary": "First summary",
                    "url": "https://example.com/first",
                },
                {
                    "article_id": "second",
                    "source_name": "Source B",
                    "title": "Second title",
                    "summary": "Second summary",
                    "url": "https://example.com/second",
                },
            ],
        },
    )

    assert len(sent_messages) == 1
    message = sent_messages[0]
    assert message["To"] == "reader@example.test"
    assert message["Subject"] == "[Inteliscope] 2 条偏好来源新内容"
    plain_body = message.get_body(preferencelist=("plain",)).get_content()
    assert "1. [Source A] First title" in plain_body
    assert "First summary" in plain_body
    assert "https://example.com/first" in plain_body
    assert "2. [Source B] Second title" in plain_body
    assert "Second summary" in plain_body
    assert "https://example.com/second" in plain_body


def test_paused_email_transport_skips_outbox_and_does_not_backfill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    service = context["service"]
    store = context["store"]

    class FakeSMTP:
        def __init__(
            self,
            _host: str,
            _port: int,
            *,
            timeout: int,
            context: Any,
        ) -> None:
            assert timeout == 20
            assert context is not None

        def __enter__(self) -> "FakeSMTP":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def login(self, _username: str, _credential: str) -> None:
            return None

        def send_message(self, _message: Any) -> None:
            return None

    service.email_transport.smtp_factory = FakeSMTP
    service.email_transport.ssl_context_factory = lambda: object()
    service.email_transport.upsert(
        workspace_id=context["workspace"]["id"],
        actor_user_id=context["user"]["id"],
        provider="qq",
        sender_email="notice@qq.com",
        sender_name="InfoHub",
        credential="test-only-auth-code",
    )
    service.email_transport.send_test(
        workspace_id=context["workspace"]["id"],
        actor_user_id=context["user"]["id"],
        recipient_email="reader@example.com",
    )
    service.email_transport.upsert(
        workspace_id=context["workspace"]["id"],
        actor_user_id=context["user"]["id"],
        enabled=True,
    )
    service.upsert_settings(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
        channel="email",
        email_address="reader@example.com",
    )

    baseline_job = _job(context)
    baseline = _save_snapshot(
        context,
        baseline_job,
        [_item(context, "baseline")],
        generated_at="2026-07-24T00:01:00+00:00",
    )
    assert service.stage_for_job(
        job=baseline_job,
        snapshot_id=baseline["id"],
        snapshot_created=True,
    ) == 0
    store.connect().commit()

    service.email_transport.upsert(
        workspace_id=context["workspace"]["id"],
        actor_user_id=context["user"]["id"],
        enabled=False,
    )
    paused_settings = service.get_public_settings(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
    )
    assert paused_settings["enabled"] is True
    assert paused_settings["email_transport_ready"] is False

    paused_job = _job(context)
    paused = _save_snapshot(
        context,
        paused_job,
        [_item(context, "baseline"), _item(context, "paused")],
        generated_at="2026-07-24T00:02:00+00:00",
    )
    assert service.stage_for_job(
        job=paused_job,
        snapshot_id=paused["id"],
        snapshot_created=True,
    ) == 0
    store.connect().commit()
    assert _count(store, "preferred_source_notification_deliveries") == 0

    service.email_transport.upsert(
        workspace_id=context["workspace"]["id"],
        actor_user_id=context["user"]["id"],
        enabled=True,
    )
    current_job = _job(context)
    current = _save_snapshot(
        context,
        current_job,
        [
            _item(context, "baseline"),
            _item(context, "paused"),
            _item(
                context,
                "strictly-new",
                published_at=(
                    datetime.fromisoformat(
                        str(
                            store.get_user_notification_channel(
                                workspace_id=context["workspace"]["id"],
                                user_id=context["user"]["id"],
                                channel="email",
                            )["enabled_at"]
                        )
                    )
                    + timedelta(seconds=1)
                ).isoformat(),
            ),
        ],
        generated_at="2026-07-24T00:03:00+00:00",
    )
    assert service.stage_for_job(
        job=current_job,
        snapshot_id=current["id"],
        snapshot_created=True,
    ) == 1
    store.connect().commit()

    deliveries = store.list_preferred_source_notification_deliveries(
        workspace_id=context["workspace"]["id"],
    )
    assert [delivery["article_id"] for delivery in deliveries] == [
        "strictly-new"
    ]


def test_dispatch_keeps_valid_provenance_when_same_article_has_two_ledgers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    store = context["store"]
    service = context["service"]
    second_source_id = store.create_source(
        workspace_id=context["workspace"]["id"],
        scope="private",
        owner_user_id=context["user"]["id"],
        source_type="rss",
        display_name="Second Preferred Feed",
        config={
            "name": "Second Preferred Feed",
            "url": "https://example.com/second.xml",
        },
    )
    second_subscription = store.create_subscription(
        user_id=context["user"]["id"],
        source_id=second_source_id,
        notify_on_new_items=True,
    )
    store.connect().execute(
        """
        UPDATE user_subscriptions
        SET notification_enabled_at = ?
        WHERE id = ?
        """,
        (WATERMARK, second_subscription["id"]),
    )
    store.connect().commit()

    baseline_job = _job(context)
    baseline = _save_snapshot(
        context,
        baseline_job,
        [_item(context, "baseline")],
        generated_at="2026-07-24T00:01:00+00:00",
    )
    assert service.stage_for_job(
        job=baseline_job,
        snapshot_id=baseline["id"],
        snapshot_created=True,
    ) == 0
    store.connect().commit()

    current_job = _job(context)
    shared_article = _item(context, "shared-provenance")
    shared_article["subscription_ids"] = [
        context["subscription_id"],
        second_subscription["id"],
    ]
    shared_article["source_ids"] = [
        context["source_id"],
        second_source_id,
    ]
    current = _save_snapshot(
        context,
        current_job,
        [_item(context, "baseline"), shared_article],
        generated_at="2026-07-24T00:02:00+00:00",
    )
    assert service.stage_for_job(
        job=current_job,
        snapshot_id=current["id"],
        snapshot_created=True,
    ) == 2
    store.connect().commit()

    staged = store.list_preferred_source_notification_deliveries(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
    )
    assert {
        (delivery["subscription_id"], delivery["article_id"])
        for delivery in staged
    } == {
        (context["subscription_id"], "shared-provenance"),
        (second_subscription["id"], "shared-provenance"),
    }

    store.update_subscription(
        context["subscription_id"],
        enabled=False,
    )
    sent_payloads: list[dict[str, Any]] = []
    monkeypatch.setattr(
        service,
        "_send_payload",
        lambda _settings, payload: sent_payloads.append(payload),
    )

    assert service.dispatch_pending(job_id=current_job["id"]) == {
        "claimed": 2,
        "succeeded": 1,
        "failed": 1,
    }
    assert len(sent_payloads) == 1
    assert [
        item["article_id"] for item in sent_payloads[0]["items"]
    ] == ["shared-provenance"]
    finished = {
        delivery["subscription_id"]: delivery
        for delivery in store.list_preferred_source_notification_deliveries(
            workspace_id=context["workspace"]["id"],
            user_id=context["user"]["id"],
        )
    }
    assert finished[context["subscription_id"]]["status"] == "failed"
    assert (
        finished[context["subscription_id"]]["error_code"]
        == "notification_subscription_disabled"
    )
    assert finished[second_subscription["id"]]["status"] == "succeeded"
    assert finished[second_subscription["id"]]["error_code"] is None


def test_disabling_source_clears_all_notification_opt_ins_without_restoring(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    assert workspace is not None
    assert owner is not None
    member = store.create_user(
        workspace_id=workspace["id"],
        username="notification-member",
        password="member-password",
        role="member",
    )
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="workspace",
        owner_user_id=None,
        source_type="rss",
        display_name="Shared Preferred Feed",
        config={
            "name": "Shared Preferred Feed",
            "url": "https://example.com/shared.xml",
        },
    )
    subscriptions = [
        store.create_subscription(
            user_id=user["id"],
            source_id=source_id,
            notify_on_new_items=True,
        )
        for user in (owner, member)
    ]
    assert all(
        subscription["notify_on_new_items"]
        and subscription["notification_enabled_at"] is not None
        for subscription in subscriptions
    )

    disabled = store.update_source(source_id, enabled=False)

    assert disabled["enabled"] is False
    disabled_subscriptions = [
        store.get_subscription(subscription["id"])
        for subscription in subscriptions
    ]
    assert all(subscription is not None for subscription in disabled_subscriptions)
    assert all(
        subscription["notify_on_new_items"] is False
        and subscription["notification_enabled_at"] is None
        for subscription in disabled_subscriptions
        if subscription is not None
    )

    restored_source = store.update_source(source_id, enabled=True)

    assert restored_source["enabled"] is True
    restored_subscriptions = [
        store.get_subscription(subscription["id"])
        for subscription in subscriptions
    ]
    assert all(
        subscription is not None
        and subscription["notify_on_new_items"] is False
        and subscription["notification_enabled_at"] is None
        for subscription in restored_subscriptions
    )


def test_create_subscription_preserves_existing_notification_opt_in_when_omitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    store = context["store"]
    original = store.get_subscription(context["subscription_id"])
    assert original is not None
    original_watermark = original["notification_enabled_at"]

    existing = store.create_subscription(
        user_id=context["user"]["id"],
        source_id=context["source_id"],
        enabled=True,
        analysis_mode="full",
    )

    assert existing["id"] == context["subscription_id"]
    assert existing["notify_on_new_items"] is True
    assert existing["notification_enabled_at"] == original_watermark

    second_source_id = store.create_source(
        workspace_id=context["workspace"]["id"],
        scope="private",
        owner_user_id=context["user"]["id"],
        source_type="rss",
        display_name="New Default-Off Feed",
        config={
            "name": "New Default-Off Feed",
            "url": "https://example.com/default-off.xml",
        },
    )
    new_subscription = store.create_subscription(
        user_id=context["user"]["id"],
        source_id=second_source_id,
        enabled=True,
        analysis_mode="full",
    )

    assert new_subscription["notify_on_new_items"] is False
    assert new_subscription["notification_enabled_at"] is None


@pytest.mark.parametrize(
    ("disable", "expected_code"),
    [
        (
            lambda context: context["store"].update_subscription(
                context["subscription_id"],
                enabled=False,
            ),
            "notification_subscription_disabled",
        ),
        (
            lambda context: context["store"].update_user(
                context["user"]["id"],
                enabled=False,
            ),
            "notification_user_disabled",
        ),
    ],
)
def test_dispatch_rechecks_disabled_targets_without_network_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    disable: Callable[[dict[str, Any]], Any],
    expected_code: str,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    store = context["store"]
    service = context["service"]
    baseline_job = _job(context)
    baseline = _save_snapshot(
        context,
        baseline_job,
        [_item(context, "baseline")],
        generated_at="2026-07-24T00:01:00+00:00",
    )
    assert service.stage_for_job(
        job=baseline_job,
        snapshot_id=baseline["id"],
        snapshot_created=True,
    ) == 0
    store.connect().commit()
    current_job = _job(context)
    current = _save_snapshot(
        context,
        current_job,
        [_item(context, "baseline"), _item(context, "new-after-stage")],
        generated_at="2026-07-24T00:02:00+00:00",
    )
    assert service.stage_for_job(
        job=current_job,
        snapshot_id=current["id"],
        snapshot_created=True,
    ) == 1
    store.connect().commit()

    disable(context)
    monkeypatch.setattr(
        service,
        "_send_payload",
        lambda *_args, **_kwargs: pytest.fail("disabled delivery made an external call"),
    )

    assert service.dispatch_pending(job_id=current_job["id"]) == {
        "claimed": 1,
        "succeeded": 0,
        "failed": 1,
    }
    delivery = store.list_preferred_source_notification_deliveries(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
    )[0]
    assert delivery["status"] == "failed"
    assert delivery["error_code"] == expected_code


def test_ambiguous_delivery_outcome_stays_sending_and_is_never_replayed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    store = context["store"]
    service = context["service"]
    baseline_job = _job(context)
    baseline = _save_snapshot(
        context,
        baseline_job,
        [_item(context, "baseline")],
        generated_at="2026-07-24T00:01:00+00:00",
    )
    assert service.stage_for_job(
        job=baseline_job,
        snapshot_id=baseline["id"],
        snapshot_created=True,
    ) == 0
    store.connect().commit()
    current_job = _job(context)
    current = _save_snapshot(
        context,
        current_job,
        [_item(context, "baseline"), _item(context, "ambiguous-send")],
        generated_at="2026-07-24T00:02:00+00:00",
    )
    assert service.stage_for_job(
        job=current_job,
        snapshot_id=current["id"],
        snapshot_created=True,
    ) == 1
    store.connect().commit()
    send_calls = 0

    def outcome_unknown(
        _settings: dict[str, Any],
        _payload: dict[str, Any],
    ) -> None:
        nonlocal send_calls
        send_calls += 1
        error = NotificationServiceError(
            "notification_webhook_unavailable",
            "webhook response outcome is unknown",
            status_code=502,
            retryable=False,
        )
        error.outcome_unknown = True
        raise error

    monkeypatch.setattr(service, "_send_payload", outcome_unknown)

    first = service.dispatch_pending(job_id=current_job["id"])

    assert first == {"claimed": 1, "succeeded": 0, "failed": 0}
    delivery = store.list_preferred_source_notification_deliveries(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
    )[0]
    assert delivery["status"] == "sending"
    assert delivery["attempts"] == 1
    assert delivery["error_code"] is None
    assert send_calls == 1

    second = service.dispatch_pending(job_id=current_job["id"])

    assert second == {"claimed": 0, "succeeded": 0, "failed": 0}
    delivery = store.get_preferred_source_notification_delivery(delivery["id"])
    assert delivery is not None
    assert delivery["status"] == "sending"
    assert delivery["attempts"] == 1
    assert delivery["error_code"] is None
    assert send_calls == 1


def test_generic_webhook_accepts_non_identity_response_without_reading_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    store = context["store"]
    service = context["service"]
    baseline_job = _job(context)
    baseline = _save_snapshot(
        context,
        baseline_job,
        [_item(context, "baseline")],
        generated_at="2026-07-24T00:01:00+00:00",
    )
    assert service.stage_for_job(
        job=baseline_job,
        snapshot_id=baseline["id"],
        snapshot_created=True,
    ) == 0
    store.connect().commit()
    current_job = _job(context)
    current = _save_snapshot(
        context,
        current_job,
        [_item(context, "baseline"), _item(context, "encoded-response")],
        generated_at="2026-07-24T00:02:00+00:00",
    )
    assert service.stage_for_job(
        job=current_job,
        snapshot_id=current["id"],
        snapshot_created=True,
    ) == 1
    store.connect().commit()
    post_calls = 0

    async def encoded_response(
        _url: str,
        **_kwargs: Any,
    ) -> SimpleNamespace:
        nonlocal post_calls
        post_calls += 1
        return SimpleNamespace(
            status_code=200,
            headers={"content-encoding": "gzip"},
        )

    monkeypatch.setattr(notification_module, "post_public_http", encoded_response)

    assert service.dispatch_pending(job_id=current_job["id"]) == {
        "claimed": 1,
        "succeeded": 1,
        "failed": 0,
    }
    delivery = store.list_preferred_source_notification_deliveries(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
    )[0]
    assert delivery["status"] == "succeeded"
    assert delivery["attempts"] == 1
    assert delivery["error_code"] is None
    assert post_calls == 1

    assert service.dispatch_pending(job_id=current_job["id"]) == {
        "claimed": 0,
        "succeeded": 0,
        "failed": 0,
    }
    assert post_calls == 1


def test_webhook_env_reference_is_bound_to_the_current_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    store = context["store"]
    service = context["service"]
    baseline_job = _job(context)
    baseline = _save_snapshot(
        context,
        baseline_job,
        [_item(context, "baseline")],
        generated_at="2026-07-24T00:01:00+00:00",
    )
    assert service.stage_for_job(
        job=baseline_job,
        snapshot_id=baseline["id"],
        snapshot_created=True,
    ) == 0
    store.connect().commit()
    current_job = _job(context)
    current = _save_snapshot(
        context,
        current_job,
        [_item(context, "baseline"), _item(context, "bound-env")],
        generated_at="2026-07-24T00:02:00+00:00",
    )
    assert service.stage_for_job(
        job=current_job,
        snapshot_id=current["id"],
        snapshot_created=True,
    ) == 1
    store.connect().commit()

    foreign_env_name = "HORIZON_USER_WEBHOOK_FOREIGN"
    SecretStore(tmp_path).set(
        foreign_env_name,
        "https://hooks.example.com/foreign-user",
    )
    store.connect().execute(
        """
        UPDATE user_notification_settings
        SET webhook_env_name = ?
        WHERE workspace_id = ? AND user_id = ?
        """,
        (
            foreign_env_name,
            context["workspace"]["id"],
            context["user"]["id"],
        ),
    )
    store.connect().commit()
    assert service.get_public_settings(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
    )["webhook_configured"] is False
    post_called = False

    async def forbidden_post(*_args: Any, **_kwargs: Any) -> httpx.Response:
        nonlocal post_called
        post_called = True
        pytest.fail("foreign webhook env reference reached the network")

    monkeypatch.setattr(notification_module, "post_public_http", forbidden_post)

    assert service.dispatch_pending(job_id=current_job["id"]) == {
        "claimed": 1,
        "succeeded": 0,
        "failed": 1,
    }
    delivery = store.list_preferred_source_notification_deliveries(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
    )[0]
    assert delivery["status"] == "failed"
    assert delivery["error_code"] == "notification_destination_required"
    assert post_called is False


@pytest.mark.parametrize("epoch_kind", ["account", "subscription"])
def test_dispatch_rejects_delivery_from_previous_notification_epoch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    epoch_kind: str,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    store = context["store"]
    service = context["service"]
    baseline_job = _job(context)
    baseline = _save_snapshot(
        context,
        baseline_job,
        [_item(context, "baseline")],
        generated_at="2026-07-24T00:01:00+00:00",
    )
    assert service.stage_for_job(
        job=baseline_job,
        snapshot_id=baseline["id"],
        snapshot_created=True,
    ) == 0
    store.connect().commit()
    current_job = _job(context)
    current = _save_snapshot(
        context,
        current_job,
        [
            _item(context, "baseline"),
            _item(
                context,
                "previous-epoch-item",
                published_at="2099-01-01T00:00:00+00:00",
            ),
        ],
        generated_at="2026-07-24T00:02:00+00:00",
    )
    assert service.stage_for_job(
        job=current_job,
        snapshot_id=current["id"],
        snapshot_created=True,
    ) == 1
    store.connect().commit()

    if epoch_kind == "account":
        service.upsert_settings(
            workspace_id=context["workspace"]["id"],
            user_id=context["user"]["id"],
            enabled=False,
        )
        service.upsert_settings(
            workspace_id=context["workspace"]["id"],
            user_id=context["user"]["id"],
            enabled=True,
        )
        store.connect().execute(
            """
            UPDATE user_notification_settings
            SET notification_enabled_at = ?
            WHERE workspace_id = ? AND user_id = ?
            """,
            (
                "2098-01-01T00:00:00+00:00",
                context["workspace"]["id"],
                context["user"]["id"],
            ),
        )
    else:
        store.update_subscription(
            context["subscription_id"],
            notify_on_new_items=False,
        )
        store.update_subscription(
            context["subscription_id"],
            notify_on_new_items=True,
        )
        store.connect().execute(
            """
            UPDATE user_subscriptions
            SET notification_enabled_at = ?
            WHERE id = ?
            """,
            (
                "2098-01-01T00:00:00+00:00",
                context["subscription_id"],
            ),
        )
    store.connect().execute(
        """
        UPDATE preferred_source_notification_deliveries
        SET created_at = ?
        WHERE job_id = ?
        """,
        ("2099-06-01T00:00:00+00:00", current_job["id"]),
    )
    store.connect().commit()
    monkeypatch.setattr(
        service,
        "_send_payload",
        lambda *_args, **_kwargs: pytest.fail(
            "stale notification epoch made an external call"
        ),
    )

    assert service.dispatch_pending(job_id=current_job["id"]) == {
        "claimed": 1,
        "succeeded": 0,
        "failed": 1,
    }
    delivery = store.list_preferred_source_notification_deliveries(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
    )[0]
    assert delivery["status"] == "failed"
    assert delivery["error_code"] == "notification_delivery_stale"


@pytest.mark.parametrize(
    "tampered_url",
    [
        "http://127.0.0.1/internal",
        "http://public.example/hook",
        "https://hooks.example.com/uncommitted-secret",
    ],
)
def test_webhook_secret_tampering_is_revalidated_before_network_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tampered_url: str,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    store = context["store"]
    service = context["service"]
    settings = store.get_user_notification_settings(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
    )
    assert settings is not None
    env_name = str(settings["webhook_env_name"])
    SecretStore(tmp_path).set(env_name, tampered_url)
    network_called = False

    async def forbidden_post(*_args: Any, **_kwargs: Any) -> httpx.Response:
        nonlocal network_called
        network_called = True
        pytest.fail("tampered webhook reached the network transport")

    monkeypatch.setattr(
        "src.services.preferred_source_notifications.post_public_http",
        forbidden_post,
    )
    payload = service._delivery_payload(
        {
            "title": "Tampered webhook test",
            "published_at": NEW_PUBLISHED_AT,
            "url": "https://example.com/safe-article",
        },
        article_id="tampered-webhook-test",
        source_name="Inteliscope",
        test=True,
    )

    with pytest.raises(NotificationServiceError) as exc_info:
        service._send_webhook(settings, payload)

    assert exc_info.value.code == "notification_destination_required"
    assert network_called is False


def test_webhook_signing_secret_tampering_fails_closed_at_stage_claim_and_send(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    store = context["store"]
    service = context["service"]
    workspace_id = context["workspace"]["id"]
    user_id = context["user"]["id"]
    service.upsert_settings(
        workspace_id=workspace_id,
        user_id=user_id,
        webhook_provider="dingtalk",
        webhook_url=(
            "https://oapi.dingtalk.com/robot/send"
            "?access_token=00000000000000000000000000000000"
        ),
        webhook_signing_secret="configured-signing-secret",
    )
    settings = store.get_user_notification_settings(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    assert settings is not None

    baseline_job = _job(context)
    baseline = _save_snapshot(
        context,
        baseline_job,
        [_item(context, "baseline")],
        generated_at="2026-07-24T00:01:00+00:00",
    )
    assert service.stage_for_job(
        job=baseline_job,
        snapshot_id=baseline["id"],
        snapshot_created=True,
    ) == 0
    store.connect().commit()
    current_job = _job(context)
    current = _save_snapshot(
        context,
        current_job,
        [_item(context, "baseline"), _item(context, "pending-before-tamper")],
        generated_at="2026-07-24T00:02:00+00:00",
    )
    assert service.stage_for_job(
        job=current_job,
        snapshot_id=current["id"],
        snapshot_created=True,
    ) == 1
    store.connect().commit()
    signing_env = str(settings["webhook_signing_env_name"])
    SecretStore(tmp_path).set(signing_env, "tampered-signing-secret")
    next_job = _job(context)
    next_snapshot = _save_snapshot(
        context,
        next_job,
        [
            _item(context, "baseline"),
            _item(context, "pending-before-tamper"),
            _item(context, "must-not-stage"),
        ],
        generated_at="2026-07-24T00:03:00+00:00",
    )
    assert service.stage_for_job(
        job=next_job,
        snapshot_id=next_snapshot["id"],
        snapshot_created=True,
    ) == 0
    store.connect().commit()
    assert _count(store, "preferred_source_notification_deliveries") == 1

    network_called = False

    async def forbidden_post(*_args: Any, **_kwargs: Any) -> httpx.Response:
        nonlocal network_called
        network_called = True
        pytest.fail("tampered signing secret reached the network transport")

    monkeypatch.setattr(notification_module, "post_public_http", forbidden_post)
    assert service.dispatch_pending(job_id=current_job["id"]) == {
        "claimed": 1,
        "succeeded": 0,
        "failed": 1,
    }
    delivery = store.list_preferred_source_notification_deliveries(
        workspace_id=workspace_id,
        user_id=user_id,
    )[0]
    assert delivery["status"] == "failed"
    assert delivery["error_code"] == "invalid_webhook_signing_secret"
    payload = service._delivery_payload(
        {
            "title": "Tampered signing test",
            "published_at": NEW_PUBLISHED_AT,
            "url": "https://example.com/safe-article",
        },
        article_id="tampered-signing-test",
        source_name="Inteliscope",
        test=True,
    )
    with pytest.raises(NotificationServiceError) as exc_info:
        service._send_webhook(settings, payload)

    assert exc_info.value.code == "invalid_webhook_signing_secret"
    assert exc_info.value.outcome_unknown is False
    assert network_called is False


def test_send_test_is_atomic_rate_limited_and_does_not_touch_feed_or_outbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    store = context["store"]
    workspace_id = context["workspace"]["id"]
    user_id = context["user"]["id"]
    before = {
        table: _count(store, table)
        for table in (
            "fetch_jobs",
            "preferred_source_notification_deliveries",
            "user_feed_snapshots",
        )
    }
    entered_send = threading.Event()
    release_send = threading.Event()

    def blocking_send(
        _self: PreferredSourceNotificationService,
        _settings: dict[str, Any],
        _payload: dict[str, Any],
    ) -> None:
        entered_send.set()
        assert release_send.wait(timeout=5)

    monkeypatch.setattr(
        PreferredSourceNotificationService,
        "_send_payload",
        blocking_send,
    )
    threaded_store = ServiceStore(tmp_path)
    threaded_service = PreferredSourceNotificationService(
        threaded_store,
        data_dir=str(tmp_path),
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(
            threaded_service.send_test,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        assert entered_send.wait(timeout=5)
        with pytest.raises(NotificationServiceError) as exc_info:
            context["service"].send_test(
                workspace_id=workspace_id,
                user_id=user_id,
            )
        assert exc_info.value.code == "notification_test_rate_limited"
        assert exc_info.value.status_code == 429
        release_send.set()
        assert first.result(timeout=5) == {"sent": True, "channel": "webhook"}
    threaded_store.close()

    assert {
        table: _count(store, table)
        for table in (
            "fetch_jobs",
            "preferred_source_notification_deliveries",
            "user_feed_snapshots",
        )
    } == before
    settings = store.get_user_notification_settings(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    assert settings is not None
    assert settings["last_test_status"] == "sent"
    assert settings["last_test_error_code"] is None


def test_send_test_hides_internal_delivery_failure_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    store = context["store"]
    workspace_id = context["workspace"]["id"]
    user_id = context["user"]["id"]
    before = {
        table: _count(store, table)
        for table in (
            "fetch_jobs",
            "preferred_source_notification_deliveries",
            "user_feed_snapshots",
        )
    }

    def blocked_send(
        _settings: dict[str, Any],
        _payload: dict[str, Any],
    ) -> None:
        raise NotificationServiceError(
            "notification_webhook_target_blocked",
            "blocked",
            status_code=400,
        )

    monkeypatch.setattr(context["service"], "_send_payload", blocked_send)
    with pytest.raises(NotificationServiceError) as exc_info:
        context["service"].send_test(
            workspace_id=workspace_id,
            user_id=user_id,
        )

    assert exc_info.value.code == "notification_test_failed"
    assert "blocked" not in str(exc_info.value)
    settings = store.get_user_notification_settings(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    assert settings is not None
    assert settings["last_test_status"] == "failed"
    assert settings["last_test_error_code"] == "notification_webhook_target_blocked"
    assert {
        table: _count(store, table)
        for table in (
            "fetch_jobs",
            "preferred_source_notification_deliveries",
            "user_feed_snapshots",
        )
    } == before


def test_send_test_reports_unknown_without_inviting_a_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    store = context["store"]
    service = context["service"]
    workspace_id = context["workspace"]["id"]
    user_id = context["user"]["id"]

    def unknown_send(
        _settings: dict[str, Any],
        _payload: dict[str, Any],
    ) -> None:
        raise NotificationServiceError(
            "notification_webhook_response_invalid",
            "unsafe upstream body must stay private",
            status_code=502,
            retryable=True,
            outcome_unknown=True,
        )

    monkeypatch.setattr(service, "_send_payload", unknown_send)
    with pytest.raises(NotificationServiceError) as exc_info:
        service.send_test(
            workspace_id=workspace_id,
            user_id=user_id,
        )

    assert exc_info.value.code == "notification_test_outcome_unknown"
    assert exc_info.value.retryable is False
    assert exc_info.value.outcome_unknown is True
    assert "unsafe upstream" not in str(exc_info.value)
    stored = store.get_user_notification_settings(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    assert stored is not None
    assert stored["last_test_status"] == "failed"
    assert (
        stored["last_test_error_code"]
        == "notification_webhook_response_invalid"
    )
    public = service.get_public_settings(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    assert public["last_test_status"] == "unknown"


@pytest.mark.parametrize(
    "user_update",
    [
        {"enabled": False},
        {"role": "viewer"},
    ],
)
def test_send_test_rejects_non_writable_user_before_claim_or_external_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    user_update: dict[str, Any],
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    store = context["store"]
    service = context["service"]
    workspace_id = context["workspace"]["id"]
    user_id = context["user"]["id"]
    before = store.get_user_notification_settings(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    assert before is not None
    assert before["last_test_attempted_at"] is None
    store.update_user(user_id, **user_update)
    monkeypatch.setattr(
        service,
        "_send_payload",
        lambda *_args, **_kwargs: pytest.fail(
            "non-writable user notification test made an external call"
        ),
    )

    with pytest.raises(NotificationServiceError) as exc_info:
        service.send_test(
            workspace_id=workspace_id,
            user_id=user_id,
        )

    assert exc_info.value.code == "notification_channel_unavailable"
    assert exc_info.value.status_code == 409
    after = store.get_user_notification_settings(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    assert after is not None
    assert after["last_test_attempted_at"] is None
    assert after["last_test_status"] is None


def test_worker_notification_stage_failure_does_not_fail_feed_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    store = context["store"]
    job = _job(context)

    def fake_run_job(
        claimed_job: dict[str, Any],
        *,
        data_dir: str,
        store: ServiceStore,
    ) -> dict[str, Any]:
        assert data_dir == str(tmp_path)
        snapshot = UserFeedStore(store).save_snapshot(
            workspace_id=claimed_job["workspace_id"],
            user_id=claimed_job["user_id"],
            job_id=claimed_job["id"],
            payload={
                "schema_version": 2,
                "run_id": f"run-{claimed_job['id']}",
                "run_status": "succeeded",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "items": [],
            },
            commit=False,
        )
        return {
            "ok": True,
            "snapshot_id": snapshot["id"],
            "snapshot_created": True,
        }

    monkeypatch.setattr("src.services.worker._run_job", fake_run_job)
    monkeypatch.setattr(
        PreferredSourceNotificationService,
        "stage_for_job",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("simulated notification staging failure")
        ),
    )
    store.close()

    result = run_worker_once(
        data_dir=str(tmp_path),
        worker_id="notification-stage-test-worker",
        enqueue_schedules=False,
    )

    assert result is not None
    assert result["id"] == job["id"]
    assert result["status"] == "succeeded"
    verification_store = ServiceStore(tmp_path)
    snapshot_row = verification_store.connect().execute(
        "SELECT id FROM user_feed_snapshots WHERE job_id = ?",
        (job["id"],),
    ).fetchone()
    assert snapshot_row is not None
    assert _count(verification_store, "preferred_source_notification_deliveries") == 0
    verification_store.close()


class _ReadyChannelTransport:
    def is_ready(self, *, workspace_id: str) -> bool:
        return bool(workspace_id)


def _configure_three_notification_channels(
    context: dict[str, Any],
) -> dict[str, Any]:
    service = context["service"]
    service.email_transport = _ReadyChannelTransport()
    service.telegram_transport = _ReadyChannelTransport()
    public = service.upsert_settings(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
        channels=["email", "webhook", "telegram"],
        email_address="reader@example.com",
        telegram_chat_id="-1001234567890",
    )
    context["store"].connect().execute(
        """
        UPDATE user_notification_channels
        SET enabled_at = ?
        WHERE workspace_id = ? AND user_id = ?
        """,
        (
            WATERMARK,
            context["workspace"]["id"],
            context["user"]["id"],
        ),
    )
    context["store"].connect().commit()
    return public


def test_three_channels_stage_dispatch_and_isolate_one_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    store = context["store"]
    service = context["service"]
    public = _configure_three_notification_channels(context)
    assert public["channels"] == ["email", "webhook", "telegram"]
    assert "-1001234567890" not in repr(public)
    assert b"-1001234567890" not in store.db_path.read_bytes()

    baseline_job = _job(context)
    baseline = _save_snapshot(
        context,
        baseline_job,
        [_item(context, "baseline")],
        generated_at="2026-07-24T00:01:00+00:00",
    )
    assert service.stage_for_job(
        job=baseline_job,
        snapshot_id=baseline["id"],
        snapshot_created=True,
    ) == 0
    store.connect().commit()
    current_job = _job(context)
    current = _save_snapshot(
        context,
        current_job,
        [_item(context, "baseline"), _item(context, "three-way")],
        generated_at="2026-07-24T00:02:00+00:00",
    )
    assert service.stage_for_job(
        job=current_job,
        snapshot_id=current["id"],
        snapshot_created=True,
    ) == 3
    store.connect().commit()

    attempted: list[str] = []

    def fake_send(settings: dict[str, Any], _payload: dict[str, Any]):
        channel = str(settings["channel"])
        attempted.append(channel)
        if channel == "webhook":
            raise NotificationServiceError(
                "simulated_webhook_failure",
                "simulated",
                status_code=502,
            )
        return None

    monkeypatch.setattr(service, "_send_payload", fake_send)
    summary = service.dispatch_pending(job_id=current_job["id"])
    assert summary == {"claimed": 3, "succeeded": 2, "failed": 1}
    assert set(attempted) == {"email", "webhook", "telegram"}
    statuses = {
        str(row["channel"]): str(row["status"])
        for row in store.connect().execute(
            """
            SELECT channel, status
            FROM preferred_source_notification_deliveries
            WHERE job_id = ?
            """,
            (current_job["id"],),
        ).fetchall()
    }
    assert statuses == {
        "email": "succeeded",
        "webhook": "failed",
        "telegram": "succeeded",
    }


def test_channel_change_preserves_other_config_pending_and_sending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    store = context["store"]
    service = context["service"]
    _configure_three_notification_channels(context)
    before = {
        row["channel"]: row
        for row in store.list_user_notification_channels(
            workspace_id=context["workspace"]["id"],
            user_id=context["user"]["id"],
        )
    }
    now = datetime.now(timezone.utc).isoformat()
    for channel, status in (
        ("email", "sending"),
        ("webhook", "pending"),
        ("telegram", "pending"),
    ):
        store.connect().execute(
            """
            INSERT INTO preferred_source_notification_deliveries (
                id, workspace_id, user_id, subscription_id, source_id,
                snapshot_id, job_id, article_id, channel, payload_json,
                status, attempts, account_notification_generation,
                channel_notification_generation,
                subscription_notification_generation, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, 0, 1, ?, 1, ?, ?)
            """,
            (
                f"delivery-{channel}",
                context["workspace"]["id"],
                context["user"]["id"],
                context["subscription_id"],
                context["source_id"],
                f"snapshot-{channel}",
                "job-channel-change",
                f"article-{channel}",
                channel,
                status,
                int(before[channel]["generation"]),
                now,
                now,
            ),
        )
    store.connect().commit()

    public = service.upsert_settings(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
        email_address="new-reader@example.com",
    )
    after = {
        row["channel"]: row
        for row in store.list_user_notification_channels(
            workspace_id=context["workspace"]["id"],
            user_id=context["user"]["id"],
        )
    }
    assert after["email"]["generation"] == before["email"]["generation"] + 1
    assert after["webhook"]["generation"] == before["webhook"]["generation"]
    assert after["telegram"]["generation"] == before["telegram"]["generation"]
    assert public["webhook_configured"] is True
    assert public["telegram_configured"] is True
    statuses = {
        row["channel"]: row["status"]
        for row in store.connect().execute(
            """
            SELECT channel, status
            FROM preferred_source_notification_deliveries
            WHERE job_id = 'job-channel-change'
            """
        ).fetchall()
    }
    assert statuses == {
        "email": "sending",
        "webhook": "pending",
        "telegram": "pending",
    }


def test_global_resume_does_not_backfill_items_seen_while_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    service = context["service"]
    store = context["store"]
    baseline_job = _job(context)
    baseline = _save_snapshot(
        context,
        baseline_job,
        [_item(context, "baseline")],
        generated_at="2026-07-24T00:01:00+00:00",
    )
    assert service.stage_for_job(
        job=baseline_job,
        snapshot_id=baseline["id"],
        snapshot_created=True,
    ) == 0
    store.connect().commit()
    service.upsert_settings(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
        enabled=False,
    )
    missed_job = _job(context)
    missed = _save_snapshot(
        context,
        missed_job,
        [_item(context, "baseline"), _item(context, "missed")],
        generated_at="2026-07-24T00:02:00+00:00",
    )
    assert service.stage_for_job(
        job=missed_job,
        snapshot_id=missed["id"],
        snapshot_created=True,
    ) == 0
    store.connect().commit()
    service.upsert_settings(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
        enabled=True,
    )
    settings = store.get_user_notification_settings(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
    )
    assert settings is not None
    resumed_at = datetime.fromisoformat(
        str(settings["notification_enabled_at"])
    )
    current_job = _job(context)
    current = _save_snapshot(
        context,
        current_job,
        [
            _item(context, "baseline"),
            _item(
                context,
                "missed",
                published_at=(resumed_at - timedelta(seconds=1)).isoformat(),
            ),
            _item(
                context,
                "strictly-new",
                published_at=(resumed_at + timedelta(seconds=1)).isoformat(),
            ),
        ],
        generated_at="2026-07-24T00:03:00+00:00",
    )
    assert service.stage_for_job(
        job=current_job,
        snapshot_id=current["id"],
        snapshot_created=True,
    ) == 1


def test_notification_test_cooldown_is_per_channel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    service = context["service"]
    _configure_three_notification_channels(context)
    monkeypatch.setattr(
        service,
        "_send_payload",
        lambda _settings, _payload: None,
    )
    assert service.send_test(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
        channel="telegram",
    )["sent"] is True
    assert service.send_test(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
        channel="email",
    )["sent"] is True
    with pytest.raises(NotificationServiceError) as limited:
        service.send_test(
            workspace_id=context["workspace"]["id"],
            user_id=context["user"]["id"],
            channel="telegram",
        )
    assert limited.value.code == "notification_test_rate_limited"


def test_unclassified_notification_test_error_is_unknown_and_not_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    service = context["service"]

    def fail_after_send(
        _settings: dict[str, Any],
        _payload: dict[str, Any],
    ) -> None:
        raise RuntimeError("unclassified post-send failure")

    monkeypatch.setattr(service, "_send_payload", fail_after_send)
    with pytest.raises(NotificationServiceError) as unknown:
        service.send_test(
            workspace_id=context["workspace"]["id"],
            user_id=context["user"]["id"],
            channel="webhook",
        )
    assert unknown.value.code == "notification_test_outcome_unknown"
    assert unknown.value.outcome_unknown is True
    assert unknown.value.retryable is False
    public = service.get_public_settings(
        workspace_id=context["workspace"]["id"],
        user_id=context["user"]["id"],
    )
    assert public["channel_states"]["webhook"]["last_test_status"] == "unknown"


def test_same_channel_notification_targets_stage_and_dispatch_independently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _notification_context(tmp_path, monkeypatch)
    store = context["store"]
    service = context["service"]
    workspace_id = context["workspace"]["id"]
    user_id = context["user"]["id"]
    targets = [
        service.notification_targets.create(
            workspace_id=workspace_id,
            actor_user_id=user_id,
            name=f"Webhook {index}",
            scope="private",
            channel="webhook",
            webhook_url=f"https://hooks.example.com/target-{index}",
            webhook_provider="generic_event",
        )
        for index in (1, 2)
    ]
    store.connect().executemany(
        """
        UPDATE notification_targets
        SET enabled = 1, enabled_at = ?, activation_generation = 1,
            last_test_status = 'sent',
            last_test_config_generation = config_generation,
            last_tested_at = ?, updated_at = ?
        WHERE id = ?
        """,
        [
            (WATERMARK, WATERMARK, WATERMARK, target["id"])
            for target in targets
        ],
    )
    store.connect().commit()
    service.upsert_settings(
        workspace_id=workspace_id,
        user_id=user_id,
        enabled=True,
        target_ids=[target["id"] for target in targets],
    )
    store.connect().execute(
        """
        UPDATE user_notification_settings
        SET notification_enabled_at = ?
        WHERE workspace_id = ? AND user_id = ?
        """,
        (WATERMARK, workspace_id, user_id),
    )
    store.connect().execute(
        """
        UPDATE user_notification_target_bindings
        SET enabled_at = ?
        WHERE workspace_id = ? AND user_id = ?
        """,
        (WATERMARK, workspace_id, user_id),
    )
    store.connect().execute(
        """
        UPDATE user_subscriptions
        SET notification_enabled_at = ?
        WHERE id = ?
        """,
        (WATERMARK, context["subscription_id"]),
    )
    store.connect().commit()

    previous_job = _job(context)
    _save_snapshot(
        context,
        previous_job,
        [],
        generated_at="2026-07-24T00:00:00+00:00",
    )
    store.connect().commit()
    current_job = _job(context)
    current_snapshot = _save_snapshot(
        context,
        current_job,
        [_item(context, "same-channel-target-item")],
        generated_at="2026-07-24T00:00:02+00:00",
    )
    assert service.stage_for_job(
        job=current_job,
        snapshot_id=current_snapshot["id"],
        snapshot_created=True,
    ) == 2
    store.connect().commit()
    rows = store.connect().execute(
        """
        SELECT target_id, channel
        FROM preferred_source_notification_deliveries
        WHERE article_id = 'same-channel-target-item'
        ORDER BY target_id
        """
    ).fetchall()
    assert [str(row["target_id"]) for row in rows] == sorted(
        target["id"] for target in targets
    )
    assert {str(row["channel"]) for row in rows} == {"webhook"}

    attempted: list[str] = []

    def fake_send(
        settings: dict[str, Any],
        _payload: dict[str, Any],
    ) -> None:
        attempted.append(
            str(settings["_notification_target"]["id"])
        )

    monkeypatch.setattr(service, "_send_payload", fake_send)
    summary = service.dispatch_pending(job_id=current_job["id"])
    assert summary == {"claimed": 2, "succeeded": 2, "failed": 0}
    assert set(attempted) == {target["id"] for target in targets}
