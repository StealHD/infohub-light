from __future__ import annotations

import smtplib
from pathlib import Path
from typing import Any

import pytest

from src.services.notification_email_transport import (
    EmailProviderRegistry,
    EmailTransportError,
    WorkspaceEmailTransportService,
)
from src.services.secret_store import SecretStore
from src.storage.service_store import ServiceStore


class FakeSMTP:
    instances: list["FakeSMTP"] = []
    failure: BaseException | None = None

    def __init__(
        self,
        host: str,
        port: int,
        *,
        timeout: int,
        context: Any,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.context = context
        self.login_calls: list[tuple[str, str]] = []
        self.messages: list[Any] = []
        type(self).instances.append(self)

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def login(self, username: str, password: str) -> None:
        if type(self).failure is not None:
            raise type(self).failure
        self.login_calls.append((username, password))

    def send_message(self, message: Any) -> None:
        if type(self).failure is not None:
            raise type(self).failure
        self.messages.append(message)


@pytest.fixture
def email_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "owner-password")
    FakeSMTP.instances = []
    FakeSMTP.failure = None
    store = ServiceStore(tmp_path)
    store.initialize()
    owner = store.get_user_by_username("owner")
    workspace = store.get_default_workspace()
    assert owner is not None
    assert workspace is not None
    service = WorkspaceEmailTransportService(
        store,
        data_dir=str(tmp_path),
        smtp_factory=FakeSMTP,
        ssl_context_factory=lambda: object(),
    )
    return {
        "store": store,
        "owner": owner,
        "workspace": workspace,
        "service": service,
        "data_dir": tmp_path,
    }


@pytest.mark.parametrize(
    ("provider", "sender", "region", "smtp_username", "host", "username"),
    [
        (
            "qq",
            "notice@qq.com",
            None,
            None,
            "smtp.qq.com",
            "notice@qq.com",
        ),
        (
            "netease",
            "notice@126.com",
            None,
            None,
            "smtp.163.com",
            "notice@126.com",
        ),
        (
            "gmail",
            "notice@example.com",
            None,
            None,
            "smtp.gmail.com",
            "notice@example.com",
        ),
        (
            "resend",
            "notice@example.com",
            None,
            None,
            "smtp.resend.com",
            "resend",
        ),
        (
            "amazon_ses",
            "notice@example.com",
            "ap-southeast-1",
            "ses-smtp-user",
            "email-smtp.ap-southeast-1.amazonaws.com",
            "ses-smtp-user",
        ),
    ],
)
def test_provider_registry_derives_only_fixed_ssl_endpoints(
    provider: str,
    sender: str,
    region: str | None,
    smtp_username: str | None,
    host: str,
    username: str,
) -> None:
    resolved = EmailProviderRegistry.resolve(
        provider=provider,
        sender_email=sender,
        region=region,
        smtp_username=smtp_username,
    )

    assert resolved.smtp_host == host
    assert resolved.smtp_port == 465
    assert resolved.security == "ssl"
    assert resolved.smtp_username == username


def test_provider_registry_rejects_provider_specific_invalid_fields() -> None:
    with pytest.raises(EmailTransportError) as qq_error:
        EmailProviderRegistry.resolve(
            provider="qq",
            sender_email="notice@example.com",
        )
    assert qq_error.value.code == "invalid_email_transport_sender"

    with pytest.raises(EmailTransportError) as ses_region_error:
        EmailProviderRegistry.resolve(
            provider="amazon_ses",
            sender_email="notice@example.com",
            region="internal.example",
            smtp_username="user",
        )
    assert ses_region_error.value.code == "invalid_email_transport_region"

    with pytest.raises(EmailTransportError) as provider_error:
        EmailProviderRegistry.resolve(
            provider="custom",
            sender_email="notice@example.com",
        )
    assert provider_error.value.code == "invalid_email_transport_provider"


def test_schema_v10_and_default_transport_are_additive(
    email_context: dict[str, Any],
) -> None:
    store = email_context["store"]
    migration = store.connect().execute(
        """
        SELECT name, checksum
        FROM schema_migrations
        WHERE version = 10
        """
    ).fetchone()

    assert dict(migration) == {
        "name": "workspace_email_transports_v10",
        "checksum": "workspace-email-transports-v10-provider-registry",
    }
    assert (
        store.get_workspace_email_transport(
            workspace_id=email_context["workspace"]["id"]
        )
        is None
    )


def test_secret_is_write_only_and_current_generation_must_test_before_enable(
    email_context: dict[str, Any],
) -> None:
    service = email_context["service"]
    store = email_context["store"]
    owner = email_context["owner"]
    workspace_id = email_context["workspace"]["id"]
    credential = "test-only-qq-authorization-code"

    saved = service.upsert(
        workspace_id=workspace_id,
        actor_user_id=owner["id"],
        provider="qq",
        sender_email="notice@qq.com",
        sender_name="InfoHub",
        credential=credential,
        enabled=True,
    )

    assert saved["enabled"] is False
    assert saved["credential_configured"] is True
    assert saved["can_enable"] is False
    assert saved["generation"] == 1
    assert credential not in repr(saved)
    internal = store.get_workspace_email_transport(
        workspace_id=workspace_id
    )
    assert internal is not None
    assert credential not in repr(internal)
    env_name = service.credential_env_name(workspace_id=workspace_id)
    assert SecretStore(email_context["data_dir"]).read() == {
        env_name: credential
    }
    assert credential.encode() not in store.db_path.read_bytes()

    with pytest.raises(EmailTransportError) as enable_error:
        service.upsert(
            workspace_id=workspace_id,
            actor_user_id=owner["id"],
            enabled=True,
        )
    assert enable_error.value.code == "email_transport_test_required"

    tested = service.send_test(
        workspace_id=workspace_id,
        actor_user_id=owner["id"],
        recipient_email="reader@example.com",
    )
    assert tested["sent"] is True
    assert tested["generation"] == 1
    assert FakeSMTP.instances[-1].host == "smtp.qq.com"
    assert FakeSMTP.instances[-1].timeout == 20
    assert FakeSMTP.instances[-1].login_calls == [
        ("notice@qq.com", credential)
    ]

    enabled = service.upsert(
        workspace_id=workspace_id,
        actor_user_id=owner["id"],
        enabled=True,
    )
    assert enabled["enabled"] is True
    assert enabled["can_enable"] is True
    assert enabled["ready"] is True

    rotated = service.upsert(
        workspace_id=workspace_id,
        actor_user_id=owner["id"],
        credential="replacement-test-credential",
    )
    assert rotated["generation"] == 2
    assert rotated["enabled"] is False
    assert rotated["last_test_status"] is None
    assert rotated["can_enable"] is False


def test_secret_digest_tampering_fails_closed(
    email_context: dict[str, Any],
) -> None:
    service = email_context["service"]
    store = email_context["store"]
    owner = email_context["owner"]
    workspace_id = email_context["workspace"]["id"]
    service.upsert(
        workspace_id=workspace_id,
        actor_user_id=owner["id"],
        provider="gmail",
        sender_email="notice@example.com",
        sender_name="InfoHub",
        credential="test-only-app-password",
    )
    service.send_test(
        workspace_id=workspace_id,
        actor_user_id=owner["id"],
        recipient_email="reader@example.com",
    )
    service.upsert(
        workspace_id=workspace_id,
        actor_user_id=owner["id"],
        enabled=True,
    )

    env_name = service.credential_env_name(workspace_id=workspace_id)
    SecretStore(email_context["data_dir"]).set(
        env_name,
        "tampered-test-secret",
    )

    assert service.is_ready(workspace_id=workspace_id) is False
    public = service.get_public_settings(workspace_id=workspace_id)
    assert public["enabled"] is True
    assert public["credential_configured"] is False
    assert public["ready"] is False
    with pytest.raises(EmailTransportError) as send_error:
        service.send_notification(
            workspace_id=workspace_id,
            recipient_email="reader@example.com",
            payload={"kind": "new_items", "items": [{"title": "New"}]},
        )
    assert send_error.value.code == "notification_channel_unavailable"


def test_test_cooldown_is_workspace_scoped_and_recipient_is_not_stored(
    email_context: dict[str, Any],
) -> None:
    service = email_context["service"]
    store = email_context["store"]
    owner = email_context["owner"]
    workspace_id = email_context["workspace"]["id"]
    service.upsert(
        workspace_id=workspace_id,
        actor_user_id=owner["id"],
        provider="resend",
        sender_email="notice@example.com",
        sender_name="InfoHub",
        credential="re_test_only_api_key",
    )
    service.send_test(
        workspace_id=workspace_id,
        actor_user_id=owner["id"],
        recipient_email="first-reader@example.com",
    )

    with pytest.raises(EmailTransportError) as cooldown_error:
        service.send_test(
            workspace_id=workspace_id,
            actor_user_id=owner["id"],
            recipient_email="second-reader@example.com",
        )

    assert cooldown_error.value.code == "email_transport_test_rate_limited"
    stored = store.get_workspace_email_transport(
        workspace_id=workspace_id
    )
    assert stored is not None
    assert "first-reader@example.com" not in repr(stored)
    assert "second-reader@example.com" not in repr(stored)
    assert b"reader@example.com" not in store.db_path.read_bytes()


def test_admin_authorization_is_rechecked_inside_mutation(
    email_context: dict[str, Any],
) -> None:
    store = email_context["store"]
    service = email_context["service"]
    owner = email_context["owner"]
    workspace_id = email_context["workspace"]["id"]
    member = store.create_user(
        workspace_id=workspace_id,
        username="member",
        password="member-password",
        role="member",
    )
    admin = store.create_user(
        workspace_id=workspace_id,
        username="admin",
        password="admin-password",
        role="admin",
    )

    with pytest.raises(EmailTransportError) as update_error:
        service.upsert(
            workspace_id=workspace_id,
            actor_user_id=member["id"],
            provider="qq",
            sender_email="notice@qq.com",
            sender_name="InfoHub",
            credential="test-only-auth-code",
        )
    assert update_error.value.status_code == 403

    service.upsert(
        workspace_id=workspace_id,
        actor_user_id=admin["id"],
        provider="qq",
        sender_email="notice@qq.com",
        sender_name="InfoHub",
        credential="test-only-auth-code",
    )
    store.update_user(admin["id"], role="member")
    with pytest.raises(EmailTransportError) as delete_error:
        service.delete(
            workspace_id=workspace_id,
            actor_user_id=admin["id"],
        )
    assert delete_error.value.status_code == 403
    assert service.get_public_settings(workspace_id=workspace_id)[
        "configured"
    ] is True


def test_operational_alert_message_uses_bounded_safe_fields() -> None:
    message = WorkspaceEmailTransportService._build_message(
        transport={
            "sender_name": "InfoHub",
            "sender_email": "notice@example.com",
        },
        recipient="admin@example.com",
        payload={
            "kind": "operational_alert",
            "event_type": "actor_switched",
            "severity": "warning",
            "route": "x/profile",
            "status": "degraded",
            "reason_code": "placeholder_record\r\nBcc: attacker@example.com",
            "occurred_at": "2026-07-29T00:00:00+00:00",
        },
    )

    assert "Apify" in str(message["Subject"])
    assert "Bcc" not in message
    body = message.get_body(preferencelist=("plain",)).get_content()
    assert "x/profile" in body
    assert "placeholder_record Bcc: attacker@example.com" in body


def test_message_is_escaped_batched_to_twenty_and_unknown_is_not_definitive(
    email_context: dict[str, Any],
) -> None:
    service = email_context["service"]
    owner = email_context["owner"]
    workspace_id = email_context["workspace"]["id"]
    service.upsert(
        workspace_id=workspace_id,
        actor_user_id=owner["id"],
        provider="amazon_ses",
        sender_email="notice@example.com",
        sender_name="InfoHub",
        region="us-east-1",
        smtp_username="ses-test-user",
        credential="ses-test-only-password",
    )
    service.send_test(
        workspace_id=workspace_id,
        actor_user_id=owner["id"],
        recipient_email="reader@example.com",
    )
    service.upsert(
        workspace_id=workspace_id,
        actor_user_id=owner["id"],
        enabled=True,
    )
    FakeSMTP.instances = []
    items = [
        {
            "source_name": "Source <unsafe>",
            "title": f"Title <{index}>",
            "summary": "Summary & details",
            "url": f"https://example.com/{index}?a=1&b=2",
        }
        for index in range(25)
    ]

    service.send_notification(
        workspace_id=workspace_id,
        recipient_email="reader@example.com",
        payload={"kind": "new_items", "items": items},
    )

    assert len(FakeSMTP.instances) == 1
    smtp = FakeSMTP.instances[0]
    assert smtp.host == "email-smtp.us-east-1.amazonaws.com"
    assert smtp.login_calls == [
        ("ses-test-user", "ses-test-only-password")
    ]
    assert len(smtp.messages) == 1
    message = smtp.messages[0]
    assert message["Subject"] == "[Inteliscope] 20 条偏好来源新内容"
    html_body = message.get_payload()[1].get_content()
    assert "Title &lt;0&gt;" in html_body
    assert "Summary &amp; details" in html_body
    assert "Title &lt;20&gt;" not in html_body

    FakeSMTP.failure = smtplib.SMTPServerDisconnected(
        "test-only disconnect"
    )
    with pytest.raises(EmailTransportError) as disconnected:
        service.send_notification(
            workspace_id=workspace_id,
            recipient_email="reader@example.com",
            payload={"kind": "new_items", "items": items[:1]},
        )
    assert disconnected.value.code == "notification_email_unavailable"
    assert disconnected.value.outcome_unknown is True


def test_rotation_invalidates_pending_email_but_leaves_sending_unknown(
    email_context: dict[str, Any],
) -> None:
    store = email_context["store"]
    service = email_context["service"]
    owner = email_context["owner"]
    workspace_id = email_context["workspace"]["id"]
    source_id = store.create_source(
        workspace_id=workspace_id,
        scope="private",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Preferred",
        config={"url": "https://example.com/feed.xml"},
    )
    subscription = store.create_subscription(
        user_id=owner["id"],
        source_id=source_id,
    )
    service.upsert(
        workspace_id=workspace_id,
        actor_user_id=owner["id"],
        provider="qq",
        sender_email="notice@qq.com",
        sender_name="InfoHub",
        credential="test-only-auth-code",
    )
    now = "2026-07-24T00:00:00+00:00"
    for delivery_id, status in (
        ("delivery-pending", "pending"),
        ("delivery-sending", "sending"),
    ):
        store.connect().execute(
            """
            INSERT INTO preferred_source_notification_deliveries (
                id, workspace_id, user_id, subscription_id, source_id,
                snapshot_id, job_id, article_id, channel, payload_json,
                status, attempts, account_notification_generation,
                subscription_notification_generation, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'email', '{}', ?, 0, 1, 1, ?, ?)
            """,
            (
                delivery_id,
                workspace_id,
                owner["id"],
                subscription["id"],
                source_id,
                "snapshot",
                "job",
                delivery_id,
                status,
                now,
                now,
            ),
        )
    store.connect().commit()

    service.upsert(
        workspace_id=workspace_id,
        actor_user_id=owner["id"],
        credential="replacement-test-auth-code",
    )

    pending = store.get_preferred_source_notification_delivery(
        "delivery-pending"
    )
    sending = store.get_preferred_source_notification_delivery(
        "delivery-sending"
    )
    assert pending is not None
    assert pending["status"] == "failed"
    assert pending["error_code"] == "notification_transport_changed"
    assert sending is not None
    assert sending["status"] == "sending"
    assert sending["error_code"] is None
