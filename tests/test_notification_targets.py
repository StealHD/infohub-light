from __future__ import annotations

import pytest

from src.services.notification_targets import (
    NotificationTargetError,
    NotificationTargetService,
)
from src.services.notification_webhook_transport import WebhookSendResult
from src.services.workspace_telegram_transport import (
    WorkspaceTelegramTransportService,
)
from src.services.notification_email_transport import (
    WorkspaceEmailTransportService,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


WEBHOOK_URL = "https://hooks.example.com/notification-target"


def _context(tmp_path):
    store = ServiceStore(tmp_path)
    store.initialize()
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="target-owner",
        password="safe-test-password",
        role="owner",
    )
    member = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="target-member",
        password="safe-test-password",
        role="member",
    )
    other = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="target-other",
        password="safe-test-password",
        role="member",
    )
    viewer = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="target-viewer",
        password="safe-test-password",
        role="viewer",
    )
    service = NotificationTargetService(
        store,
        data_dir=str(tmp_path),
        email_transport=WorkspaceEmailTransportService(
            store,
            data_dir=str(tmp_path),
        ),
        telegram_transport=WorkspaceTelegramTransportService(
            store,
            data_dir=str(tmp_path),
        ),
    )
    return store, service, owner, member, other, viewer


def test_target_lifecycle_is_write_only_and_generation_scoped(
    tmp_path,
    monkeypatch,
) -> None:
    store, service, _owner, member, _other, _viewer = _context(tmp_path)
    created = service.create(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=member["id"],
        name="我的 Webhook",
        scope="private",
        channel="webhook",
        webhook_url=WEBHOOK_URL,
        webhook_provider="generic_event",
    )
    target_id = created["id"]
    assert created["configured"] is True
    assert created["enabled"] is False
    assert WEBHOOK_URL not in repr(created)
    assert WEBHOOK_URL.encode() not in store.db_path.read_bytes()

    async def fake_send(**_kwargs):
        return WebhookSendResult(
            provider="generic_event",
            verification="http_status",
        )

    monkeypatch.setattr(
        "src.services.notification_targets.send_notification_webhook",
        fake_send,
    )
    tested = service.send_test(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=member["id"],
        target_id=target_id,
    )
    assert tested == {
        "sent": True,
        "target_id": target_id,
        "channel": "webhook",
        "provider": "generic_event",
        "verification": "http_status",
    }
    enabled = service.update(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=member["id"],
        target_id=target_id,
        enabled=True,
    )
    assert enabled["enabled"] is True
    generation = enabled["config_generation"]
    activation = enabled["activation_generation"]

    renamed = service.update(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=member["id"],
        target_id=target_id,
        name="主 Webhook",
    )
    assert renamed["config_generation"] == generation
    assert renamed["activation_generation"] == activation
    assert renamed["enabled"] is True

    changed = service.update(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=member["id"],
        target_id=target_id,
        webhook_url="https://hooks.example.com/rotated-target",
    )
    assert changed["enabled"] is False
    assert changed["last_test_status"] is None
    assert changed["config_generation"] == generation + 1


def test_target_scope_binding_isolation_and_archive_guard(tmp_path) -> None:
    store, service, owner, member, other, viewer = _context(tmp_path)
    private_target = service.create(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=member["id"],
        name="私人邮箱",
        scope="private",
        channel="email",
        email_address="member@example.invalid",
    )
    assert private_target["id"] in {
        target["id"]
        for target in service.list_public_targets(
            workspace_id=DEFAULT_WORKSPACE_ID,
            user_id=member["id"],
        )["targets"]
    }
    assert private_target["id"] not in {
        target["id"]
        for target in service.list_public_targets(
            workspace_id=DEFAULT_WORKSPACE_ID,
            user_id=other["id"],
        )["targets"]
    }
    with pytest.raises(NotificationTargetError) as viewer_create:
        service.create(
            workspace_id=DEFAULT_WORKSPACE_ID,
            actor_user_id=viewer["id"],
            name="只读目标",
            scope="private",
            channel="email",
            email_address="viewer@example.invalid",
        )
    assert viewer_create.value.code == "forbidden"
    with pytest.raises(NotificationTargetError) as member_shared:
        service.create(
            workspace_id=DEFAULT_WORKSPACE_ID,
            actor_user_id=member["id"],
            name="共享目标",
            scope="shared",
            channel="email",
            email_address="shared@example.invalid",
        )
    assert member_shared.value.code == "forbidden"

    shared_target = service.create(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=owner["id"],
        name="共享邮箱",
        scope="shared",
        channel="email",
        email_address="shared@example.invalid",
    )
    store.set_user_notification_target_bindings(
        workspace_id=DEFAULT_WORKSPACE_ID,
        user_id=member["id"],
        target_ids=[private_target["id"], shared_target["id"]],
    )
    with pytest.raises(NotificationTargetError) as in_use:
        service.archive(
            workspace_id=DEFAULT_WORKSPACE_ID,
            actor_user_id=member["id"],
            target_id=private_target["id"],
        )
    assert in_use.value.code == "notification_target_in_use"
    store.set_user_notification_target_bindings(
        workspace_id=DEFAULT_WORKSPACE_ID,
        user_id=member["id"],
        target_ids=[shared_target["id"]],
    )
    assert service.archive(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=member["id"],
        target_id=private_target["id"],
    )
    assert "member@example.invalid" not in service.secret_store.path.read_text()

    store.set_apify_actor_alert_target_bindings(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=owner["id"],
        target_ids=[shared_target["id"]],
    )
    with pytest.raises(LookupError):
        store.set_apify_actor_alert_target_bindings(
            workspace_id=DEFAULT_WORKSPACE_ID,
            actor_user_id=owner["id"],
            target_ids=[private_target["id"]],
        )


def test_target_rejects_destination_fields_from_another_channel(tmp_path) -> None:
    _store, service, _owner, member, _other, _viewer = _context(tmp_path)

    with pytest.raises(NotificationTargetError) as create_error:
        service.create(
            workspace_id=DEFAULT_WORKSPACE_ID,
            actor_user_id=member["id"],
            name="混合配置",
            scope="private",
            channel="email",
            email_address="member@example.invalid",
            telegram_chat_id="@must_not_be_ignored",
        )
    assert create_error.value.code == (
        "invalid_notification_target_configuration"
    )

    target = service.create(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=member["id"],
        name="有效邮箱",
        scope="private",
        channel="email",
        email_address="member@example.invalid",
    )
    with pytest.raises(NotificationTargetError) as update_error:
        service.update(
            workspace_id=DEFAULT_WORKSPACE_ID,
            actor_user_id=member["id"],
            target_id=target["id"],
            webhook_url=WEBHOOK_URL,
        )
    assert update_error.value.code == (
        "invalid_notification_target_configuration"
    )
