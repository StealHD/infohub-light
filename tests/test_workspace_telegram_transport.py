from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.services.notification_telegram_transport import TelegramSendResult
from src.services.workspace_telegram_transport import (
    TelegramTransportServiceError,
    WorkspaceTelegramTransportService,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


BOT_TOKEN = "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


def _context(tmp_path):
    store = ServiceStore(tmp_path)
    store.initialize()
    admin = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="telegram-admin",
        password="safe-test-password",
        role="admin",
    )
    member = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="telegram-member",
        password="safe-test-password",
        role="member",
    )
    service = WorkspaceTelegramTransportService(
        store,
        data_dir=str(tmp_path),
    )
    return store, service, admin, member


def test_workspace_telegram_transport_is_write_only_tested_and_admin_owned(
    tmp_path,
    monkeypatch,
) -> None:
    store, service, admin, member = _context(tmp_path)
    with pytest.raises(TelegramTransportServiceError) as forbidden:
        service.upsert(
            workspace_id=DEFAULT_WORKSPACE_ID,
            actor_user_id=member["id"],
            bot_token=BOT_TOKEN,
        )
    assert forbidden.value.code == "forbidden"

    saved = service.upsert(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=admin["id"],
        bot_token=BOT_TOKEN,
    )
    assert saved["token_configured"] is True
    assert saved["enabled"] is False
    assert BOT_TOKEN not in repr(saved)
    assert BOT_TOKEN.encode() not in store.db_path.read_bytes()

    async def fake_send(
        bot_token: str,
        chat_id: str,
        text: str,
        *,
        timeout: float,
    ) -> TelegramSendResult:
        assert bot_token == BOT_TOKEN
        assert chat_id == "-1001234567890"
        assert text and timeout == 5.0
        return TelegramSendResult(
            message_id=42,
            verification="provider_accepted",
        )

    monkeypatch.setattr(
        "src.services.workspace_telegram_transport.send_telegram_message",
        fake_send,
    )
    tested = service.send_test(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=admin["id"],
        chat_id="-1001234567890",
    )
    assert tested["message_id"] == 42
    assert "-1001234567890" not in repr(
        service.get_public_settings(
            workspace_id=DEFAULT_WORKSPACE_ID
        )
    )
    enabled = service.upsert(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=admin["id"],
        enabled=True,
    )
    assert enabled["ready"] is True

    rotated = service.upsert(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=admin["id"],
        bot_token=(
            "987654321:"
            "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
        ),
    )
    assert rotated["enabled"] is False
    assert rotated["last_test_status"] is None
    assert rotated["generation"] == enabled["generation"] + 1

    store.record_workspace_telegram_transport_test(
        workspace_id=DEFAULT_WORKSPACE_ID,
        generation=rotated["generation"],
        status="failed",
        error_code="notification_telegram_outcome_unknown",
    )
    assert service.get_public_settings(
        workspace_id=DEFAULT_WORKSPACE_ID
    )["last_test_status"] == "unknown"
    assert service.delete(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=admin["id"],
    ) is True
    assert service.get_public_settings(
        workspace_id=DEFAULT_WORKSPACE_ID
    )["configured"] is False


def test_transport_rotation_preserves_sending_and_restore_advances_watermark(
    tmp_path,
) -> None:
    store, service, admin, _member = _context(tmp_path)
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="private",
        owner_user_id=admin["id"],
        source_type="rss",
        display_name="Telegram transport test",
        config={"url": "https://example.com/feed.xml"},
    )
    subscription = store.create_subscription(
        user_id=admin["id"],
        source_id=source_id,
        notify_on_new_items=True,
    )
    subscription_id = subscription["id"]
    store.upsert_user_notification_settings(
        workspace_id=DEFAULT_WORKSPACE_ID,
        user_id=admin["id"],
        enabled=True,
        channel="telegram",
    )
    channel = store.get_user_notification_channel(
        workspace_id=DEFAULT_WORKSPACE_ID,
        user_id=admin["id"],
        channel="telegram",
    )
    assert channel is not None
    store.upsert_user_notification_channel(
        workspace_id=DEFAULT_WORKSPACE_ID,
        user_id=admin["id"],
        channel="telegram",
        position=0,
        enabled=True,
        enabled_at="2020-01-01T00:00:00+00:00",
        generation=int(channel["generation"]),
    )
    settings = store.get_user_notification_settings(
        workspace_id=DEFAULT_WORKSPACE_ID,
        user_id=admin["id"],
    )
    assert settings is not None
    now = datetime.now(timezone.utc).isoformat()
    for status in ("pending", "sending"):
        store.connect().execute(
            """
            INSERT INTO preferred_source_notification_deliveries (
                id, workspace_id, user_id, subscription_id, source_id,
                snapshot_id, job_id, article_id, channel, payload_json,
                status, attempts, account_notification_generation,
                channel_notification_generation,
                subscription_notification_generation, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'telegram', '{}', ?, 0, ?, ?, 1, ?, ?)
            """,
            (
                f"telegram-{status}",
                DEFAULT_WORKSPACE_ID,
                admin["id"],
                subscription_id,
                source_id,
                f"snapshot-{status}",
                "job-transport",
                f"article-{status}",
                status,
                int(settings["notification_generation"]),
                int(channel["generation"]),
                now,
                now,
            ),
        )
    store.connect().commit()

    service.upsert(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=admin["id"],
        bot_token=BOT_TOKEN,
    )
    states = {
        row["id"]: row["status"]
        for row in store.connect().execute(
            """
            SELECT id, status
            FROM preferred_source_notification_deliveries
            WHERE job_id = 'job-transport'
            """
        ).fetchall()
    }
    assert states == {
        "telegram-pending": "failed",
        "telegram-sending": "sending",
    }

    generation = service.get_public_settings(
        workspace_id=DEFAULT_WORKSPACE_ID
    )["generation"]
    store.record_workspace_telegram_transport_test(
        workspace_id=DEFAULT_WORKSPACE_ID,
        generation=generation,
        status="sent",
    )
    service.upsert(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=admin["id"],
        enabled=True,
    )
    restored_channel = store.get_user_notification_channel(
        workspace_id=DEFAULT_WORKSPACE_ID,
        user_id=admin["id"],
        channel="telegram",
    )
    assert restored_channel is not None
    assert restored_channel["enabled_at"] > "2020-01-01T00:00:00+00:00"


def test_v15_readiness_rejects_legacy_delivery_uniqueness(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    assert store.multichannel_notifications_v15_migration_required() is False
    store.connect().execute(
        """
        CREATE UNIQUE INDEX legacy_preferred_delivery_identity
        ON preferred_source_notification_deliveries(
            subscription_id, article_id
        )
        """
    )
    store.connect().commit()
    assert store.multichannel_notifications_v15_migration_required() is True
