"""Public notification target projection kept out of the target service monolith."""

from typing import Any
from .notification_target_topics import get_topic
from .notification_webhook_transport import normalize_stored_webhook_provider, webhook_verification_mode


def public_target(service, target: dict[str, Any], *, actor: dict[str, Any]) -> dict[str, Any]:
    configured = service._destination(target) is not None
    tested = (
        target.get("last_test_status") == "sent"
        and int(target.get("last_test_config_generation") or 0)
        == int(target.get("config_generation") or 0)
    )
    transport_ready = service._transport_ready(target)
    archived = target.get("archived_at") is not None
    available = bool(
        not archived
        and target.get("enabled")
        and configured
        and tested
        and transport_ready
    )
    can_edit = bool(
        not archived
        and str(actor.get("role") or "") != "viewer"
        and (
            (
                target.get("scope") == "private"
                and str(target.get("owner_user_id"))
                == str(actor.get("id"))
            )
            or (
                target.get("scope") == "shared"
                and str(actor.get("role") or "") in {"owner", "admin"}
            )
        )
    )
    usage = service.store.notification_target_usage(
        workspace_id=str(target["workspace_id"]),
        target_id=str(target["id"]),
    )
    test_status = target.get("last_test_status")
    if (
        test_status == "failed"
        and str(target.get("last_test_error_code") or "").endswith(
            ("outcome_unknown", "response_invalid")
        )
    ):
        test_status = "unknown"
    public: dict[str, Any] = {
        "id": str(target["id"]),
        "name": str(target["name"]),
        "scope": str(target["scope"]),
        "channel": str(target["channel"]),
        "configured": configured,
        "enabled": bool(target.get("enabled")),
        "available": available,
        "transport_ready": transport_ready,
        "config_generation": int(
            target.get("config_generation") or 1
        ),
        "activation_generation": int(
            target.get("activation_generation") or 0
        ),
        "enabled_at": target.get("enabled_at"),
        "last_test_status": test_status,
        "last_tested_at": target.get("last_tested_at"),
        "last_test_error_code": target.get("last_test_error_code"),
        "can_edit": can_edit,
        "can_test": bool(can_edit and configured and transport_ready),
        "can_enable": bool(can_edit and configured and tested),
        "usage": usage,
        "updated_at": target.get("updated_at"),
    }
    if target.get("channel") == "webhook":
        provider = normalize_stored_webhook_provider(
            target.get("webhook_provider")
        )
        public.update(
            {
                "webhook_provider": provider,
                "webhook_signing_secret_configured": bool(
                    service._signing_secret(target)
                ),
                "webhook_verification_mode": webhook_verification_mode(
                    provider
                ),
            }
        )
    if target.get("channel") == "telegram":
        public["telegram_topic_configured"] = get_topic(service.store, str(target["id"])) is not None
    return public
