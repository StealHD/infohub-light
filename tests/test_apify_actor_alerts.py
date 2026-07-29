from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from src.services.apify_actor_alerts import (
    ALERT_EVENTS,
    ApifyActorAlertError,
    ApifyActorAlertService,
)
from src.services.apify_actor_monitoring import ApifyActorAlertBridge
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


class _ReadyEmailTransport:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    def is_ready(self, *, workspace_id: str) -> bool:
        return workspace_id == DEFAULT_WORKSPACE_ID

    def send_operational_alert(
        self,
        *,
        workspace_id: str,
        recipient_email: str,
        payload: dict[str, object],
    ) -> None:
        self.sent.append(
            {
                "workspace_id": workspace_id,
                "recipient_email": recipient_email,
                "payload": payload,
            }
        )


def _service(
    tmp_path,
) -> tuple[ServiceStore, ApifyActorAlertService, str, _ReadyEmailTransport]:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    admin = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="alert-admin",
        password="safe-test-password",
        role="admin",
    )
    email = _ReadyEmailTransport()
    service = ApifyActorAlertService(
        store,
        data_dir=str(data_dir),
        email_transport=email,
    )
    return store, service, str(admin["id"]), email


def _configure_webhook(
    service: ApifyActorAlertService,
    admin_id: str,
    *,
    url: str = "https://hooks.example.com/apify",
) -> None:
    service.upsert_settings(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=admin_id,
        enabled=True,
        channel="webhook",
        webhook_url=url,
    )


def _incident_statuses(store: ServiceStore) -> dict[str, str]:
    return {
        str(row["incident_key"]): str(row["status"])
        for row in store.connect().execute(
            """
            SELECT incident_key, status
            FROM apify_actor_alert_incidents
            WHERE workspace_id = ?
            ORDER BY incident_key
            """,
            (DEFAULT_WORKSPACE_ID,),
        ).fetchall()
    }


def test_first_partial_alert_patch_defaults_every_event(tmp_path) -> None:
    _store, service, admin_id, _email = _service(tmp_path)

    state = service.upsert_settings(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=admin_id,
        webhook_url="https://hooks.example.com/apify?token=write-only",
    )

    assert state["enabled"] is False
    assert state["events"] == list(ALERT_EVENTS)
    assert state["webhook_configured"] is True


def test_incident_first_report_and_recovery_are_each_staged_once(tmp_path) -> None:
    store, service, admin_id, _email = _service(tmp_path)
    _configure_webhook(service, admin_id)

    first = service.open_incident(
        workspace_id=DEFAULT_WORKSPACE_ID,
        route_key="x/profile",
        incident_key="route_degraded",
        event_type="actor_switched",
        severity="warning",
        payload={"reason_code": "apify_actor_placeholder"},
    )
    repeated = service.open_incident(
        workspace_id=DEFAULT_WORKSPACE_ID,
        route_key="x/profile",
        incident_key="route_degraded",
        event_type="actor_switched",
        severity="warning",
        payload={"reason_code": "apify_actor_placeholder"},
    )
    recovered = service.resolve_incident(
        workspace_id=DEFAULT_WORKSPACE_ID,
        route_key="x/profile",
        incident_key="route_degraded",
        payload={"reason_code": "recovered"},
    )
    recovered_again = service.resolve_incident(
        workspace_id=DEFAULT_WORKSPACE_ID,
        route_key="x/profile",
        incident_key="route_degraded",
        payload={"reason_code": "recovered"},
    )

    assert first["created"] is True
    assert first["delivery_staged"] is True
    assert repeated["created"] is False
    assert repeated["delivery_staged"] is False
    assert recovered["resolved"] is True
    assert recovered["delivery_staged"] is True
    assert recovered_again["resolved"] is False
    deliveries = store.connect().execute(
        """
        SELECT event_type, status
        FROM apify_actor_alert_deliveries
        ORDER BY created_at, id
        """
    ).fetchall()
    assert [tuple(row) for row in deliveries] == [
        ("actor_switched", "pending"),
        ("recovered", "pending"),
    ]


def test_route_recovery_resolves_only_matching_incidents(tmp_path) -> None:
    store, service, _admin_id, _email = _service(tmp_path)
    bridge = ApifyActorAlertBridge(
        store,
        service,
        workspace_id=DEFAULT_WORKSPACE_ID,
    )
    bridge(
        "actor_switched",
        {"reason": "apify_actor_placeholder", "status": "degraded"},
    )
    bridge(
        "all_actors_unavailable",
        {"reason": "all_candidates_unavailable", "status": "exhausted"},
    )
    bridge(
        "budget_blocked",
        {"reason": "failed_spend_limit", "status": "budget_blocked"},
    )
    bridge(
        "start_outcome_unknown",
        {"reason": "apify_run_reconcile_required", "status": "blocked"},
    )

    bridge(
        "route_recovered",
        {"reason": "actor_recovered", "status": "degraded"},
    )
    assert _incident_statuses(store) == {
        "budget_blocked": "open",
        "route_degraded": "open",
        "route_exhausted": "resolved",
        "start_outcome_unknown": "open",
    }

    bridge(
        "actor_recovered",
        {"reason": "actor_recovered", "status": "degraded"},
    )
    assert _incident_statuses(store)["route_degraded"] == "open"

    bridge(
        "route_recovered",
        {"reason": "actor_recovered", "status": "ready"},
    )
    bridge(
        "route_recovered",
        {"reason": "budget_fuse_released", "status": "degraded"},
    )
    bridge(
        "route_recovered",
        {"reason": "run_reconciled", "status": "ready"},
    )
    assert set(_incident_statuses(store).values()) == {"resolved"}


def test_quota_unknown_does_not_recover_and_zero_escalates_once(tmp_path) -> None:
    store, service, _admin_id, _email = _service(tmp_path)
    secret = store.create_secret_ref(
        workspace_id=DEFAULT_WORKSPACE_ID,
        owner_user_id=None,
        name="Apify",
        env_name="APIFY_ALERT_QUOTA_TEST",
        kind="provider",
        provider="apify",
    )
    store.initialize()
    bridge = ApifyActorAlertBridge(
        store,
        service,
        workspace_id=DEFAULT_WORKSPACE_ID,
    )
    route_state = {"quota": {"estimated_days_remaining": None}}

    bridge.sync_quota_incident(route_state)
    assert _incident_statuses(store) == {}

    now = datetime.now(timezone.utc).isoformat()
    store.connect().execute(
        """
        UPDATE apify_key_pool_members
        SET remaining_included_credits_usd = 0,
            monthly_included_credits_usd = 10,
            last_checked_at = ?, updated_at = ?
        WHERE workspace_id = ? AND secret_id = ?
        """,
        (now, now, DEFAULT_WORKSPACE_ID, secret["id"]),
    )
    store.connect().commit()
    bridge.sync_quota_incident(route_state)
    bridge.sync_quota_incident(route_state)
    assert _incident_statuses(store) == {"quota_exhausted": "open"}

    store.connect().execute(
        """
        UPDATE apify_key_pool_members
        SET remaining_included_credits_usd = 1, updated_at = ?
        WHERE workspace_id = ? AND secret_id = ?
        """,
        (now, DEFAULT_WORKSPACE_ID, secret["id"]),
    )
    store.connect().commit()
    bridge.sync_quota_incident(route_state)
    assert _incident_statuses(store) == {
        "quota_exhausted": "resolved",
        "quota_low": "open",
    }

    store.connect().execute(
        """
        UPDATE apify_key_pool_members
        SET remaining_included_credits_usd = NULL,
            monthly_included_credits_usd = NULL,
            updated_at = ?
        WHERE workspace_id = ? AND secret_id = ?
        """,
        (now, DEFAULT_WORKSPACE_ID, secret["id"]),
    )
    store.connect().commit()
    bridge.sync_quota_incident(route_state)
    assert _incident_statuses(store)["quota_low"] == "open"


def test_explicit_delivery_failures_retry_three_times_but_unknown_never_replays(
    tmp_path,
    monkeypatch,
) -> None:
    store, service, admin_id, _email = _service(tmp_path)
    _configure_webhook(service, admin_id)
    service.open_incident(
        workspace_id=DEFAULT_WORKSPACE_ID,
        route_key="x/profile",
        incident_key="route_degraded",
        event_type="actor_switched",
        severity="warning",
    )

    def explicitly_failed(*_args, **_kwargs) -> None:
        raise ApifyActorAlertError(
            "notification_webhook_unavailable",
            "connect failed",
            status_code=502,
            retryable=True,
        )

    monkeypatch.setattr(service, "_send_payload", explicitly_failed)
    for attempt in range(1, 4):
        summary = service.dispatch_pending(
            workspace_id=DEFAULT_WORKSPACE_ID,
            limit=1,
        )
        row = store.connect().execute(
            """
            SELECT status, attempts
            FROM apify_actor_alert_deliveries
            WHERE event_type = 'actor_switched'
            """
        ).fetchone()
        assert int(row["attempts"]) == attempt
        if attempt < 3:
            assert summary["retried"] == 1
            assert row["status"] == "pending"
            store.connect().execute(
                """
                UPDATE apify_actor_alert_deliveries
                SET retry_at = '2000-01-01T00:00:00+00:00'
                WHERE event_type = 'actor_switched'
                """
            )
            store.connect().commit()
        else:
            assert summary["failed"] == 1
            assert row["status"] == "failed"

    service.open_incident(
        workspace_id=DEFAULT_WORKSPACE_ID,
        route_key="x/profile",
        incident_key="route_exhausted",
        event_type="route_exhausted",
        severity="critical",
    )

    def outcome_unknown(*_args, **_kwargs) -> None:
        raise ApifyActorAlertError(
            "notification_delivery_outcome_unknown",
            "response was lost",
            status_code=502,
            outcome_unknown=True,
        )

    monkeypatch.setattr(service, "_send_payload", outcome_unknown)
    summary = service.dispatch_pending(
        workspace_id=DEFAULT_WORKSPACE_ID,
        limit=1,
    )
    assert summary["unknown"] == 1
    public = service.list_incidents(
        workspace_id=DEFAULT_WORKSPACE_ID,
        limit=20,
    )
    exhausted = next(
        incident
        for incident in public
        if incident["event_type"] == "route_exhausted"
    )
    assert exhausted["delivery_status"] == "unknown"
    assert (
        service.get_public_settings(
            workspace_id=DEFAULT_WORKSPACE_ID
        )["last_alert_status"]
        == "unknown"
    )
    assert (
        service.dispatch_pending(
            workspace_id=DEFAULT_WORKSPACE_ID,
            limit=20,
        )["claimed"]
        == 0
    )


def test_webhook_ssrf_is_blocked_before_delivery(tmp_path) -> None:
    _store, service, admin_id, _email = _service(tmp_path)
    _configure_webhook(
        service,
        admin_id,
        url="https://127.0.0.1/private-hook",
    )
    settings = service._settings_row(DEFAULT_WORKSPACE_ID)
    assert settings is not None

    with pytest.raises(ApifyActorAlertError) as exc_info:
        service._send_webhook(
            settings,
            {
                "event_type": "test",
                "severity": "info",
                "route": "x/profile",
                "status": "test",
            },
            test=True,
        )

    assert exc_info.value.code == "notification_webhook_target_blocked"


def test_webhook_connect_failure_retries_but_read_failure_is_unknown(
    tmp_path,
    monkeypatch,
) -> None:
    _store, service, admin_id, _email = _service(tmp_path)
    _configure_webhook(service, admin_id)
    settings = service._settings_row(DEFAULT_WORKSPACE_ID)
    assert settings is not None
    request = httpx.Request("POST", "https://hooks.example.com/apify")

    async def connect_failed(*_args, **_kwargs):
        raise httpx.ConnectError("connect failed", request=request)

    monkeypatch.setattr(
        "src.services.apify_actor_alerts.post_public_http",
        connect_failed,
    )
    with pytest.raises(ApifyActorAlertError) as connect_error:
        service._send_webhook(
            settings,
            {"event_type": "test", "route": "x/profile", "status": "test"},
            test=True,
        )
    assert connect_error.value.retryable is True
    assert connect_error.value.outcome_unknown is False

    async def read_failed(*_args, **_kwargs):
        raise httpx.ReadError("response lost", request=request)

    monkeypatch.setattr(
        "src.services.apify_actor_alerts.post_public_http",
        read_failed,
    )
    with pytest.raises(ApifyActorAlertError) as read_error:
        service._send_webhook(
            settings,
            {"event_type": "test", "route": "x/profile", "status": "test"},
            test=True,
        )
    assert read_error.value.retryable is False
    assert read_error.value.outcome_unknown is True


def test_email_alert_uses_dedicated_operational_payload(tmp_path) -> None:
    _store, service, admin_id, email = _service(tmp_path)
    service.upsert_settings(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=admin_id,
        enabled=True,
        channel="email",
        email_address="ops@example.com",
    )
    settings = service._settings_row(DEFAULT_WORKSPACE_ID)
    assert settings is not None

    service._send_email(
        settings,
        {
            "event_type": "actor_switched",
            "severity": "warning",
            "route": "x/profile",
            "status": "open",
            "actor_name": "ScrapeBadger",
            "active_actor_name": "Dami",
            "reason_code": "apify_actor_placeholder",
            "occurred_at": "2026-07-29T00:00:00+00:00",
        },
        test=False,
    )

    assert len(email.sent) == 1
    payload = email.sent[0]["payload"]
    assert isinstance(payload, dict)
    assert payload["kind"] == "operational_alert"
    assert payload["active_actor_name"] == "Dami"
