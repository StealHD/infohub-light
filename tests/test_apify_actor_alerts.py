from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from src.services.apify_actor_alerts import (
    ALERT_EVENTS,
    ApifyActorAlertError,
    ApifyActorAlertService,
)
from src.services.apify_actor_monitoring import ApifyActorAlertBridge
from src.services.secret_store import SecretStore
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


def test_alert_provider_and_signing_rotation_is_write_only(tmp_path) -> None:
    store, service, admin_id, _email = _service(tmp_path)
    _configure_webhook(service, admin_id)
    before = service._settings_row(DEFAULT_WORKSPACE_ID)
    assert before is not None
    before_webhook = store.get_apify_actor_alert_channel(
        workspace_id=DEFAULT_WORKSPACE_ID,
        channel="webhook",
    )
    assert before_webhook is not None
    url = (
        "https://oapi.dingtalk.com/robot/send"
        "?access_token=00000000000000000000000000000000"
    )
    signing_secret = "write-only-dingtalk-secret"

    public = service.upsert_settings(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=admin_id,
        webhook_provider="dingtalk",
        webhook_url=url,
        webhook_signing_secret=signing_secret,
    )

    assert public["webhook_provider"] == "dingtalk"
    assert public["webhook_provider_explicit"] is True
    assert public["webhook_signing_secret_configured"] is True
    assert public["webhook_verification_mode"] == "provider_response"
    assert url not in repr(public)
    assert signing_secret not in repr(public)
    internal = service._settings_row(DEFAULT_WORKSPACE_ID)
    assert internal is not None
    assert internal["generation"] == int(before["generation"])
    changed_webhook = store.get_apify_actor_alert_channel(
        workspace_id=DEFAULT_WORKSPACE_ID,
        channel="webhook",
    )
    assert changed_webhook is not None
    assert changed_webhook["generation"] == (
        int(before_webhook["generation"]) + 1
    )
    signing_env = service.webhook_signing_env_name(
        workspace_id=DEFAULT_WORKSPACE_ID
    )
    secrets = SecretStore(tmp_path / "data").read()
    assert secrets[signing_env] == signing_secret
    assert signing_secret.encode() not in store.db_path.read_bytes()

    cleared = service.upsert_settings(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=admin_id,
        webhook_signing_secret=None,
    )
    assert cleared["webhook_signing_secret_configured"] is False
    assert signing_env not in SecretStore(tmp_path / "data").read()

    with pytest.raises(ApifyActorAlertError) as missing_url:
        service.upsert_settings(
            workspace_id=DEFAULT_WORKSPACE_ID,
            actor_user_id=admin_id,
            webhook_provider="slack",
        )
    assert (
        missing_url.value.code
        == "webhook_url_required_for_provider_change"
    )


def test_alert_signing_secret_tampering_fails_closed_at_stage_claim_and_send(
    tmp_path,
    monkeypatch,
) -> None:
    store, service, admin_id, _email = _service(tmp_path)
    service.upsert_settings(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=admin_id,
        enabled=True,
        channel="webhook",
        webhook_provider="dingtalk",
        webhook_url=(
            "https://oapi.dingtalk.com/robot/send"
            "?access_token=00000000000000000000000000000000"
        ),
        webhook_signing_secret="configured-alert-signing-secret",
    )
    staged = service.open_incident(
        workspace_id=DEFAULT_WORKSPACE_ID,
        route_key="x/profile",
        incident_key="route_degraded",
        event_type="actor_switched",
        severity="warning",
    )
    assert staged["delivery_staged"] is True
    settings = service._settings_row(DEFAULT_WORKSPACE_ID)
    assert settings is not None
    signing_env = str(settings["webhook_signing_env_name"])
    SecretStore(tmp_path / "data").set(
        signing_env,
        "tampered-alert-signing-secret",
    )
    assert service.get_public_settings(
        workspace_id=DEFAULT_WORKSPACE_ID
    )["webhook_signing_secret_configured"] is False
    network_called = False

    async def forbidden_post(*_args, **_kwargs) -> httpx.Response:
        nonlocal network_called
        network_called = True
        pytest.fail("tampered alert signing secret reached the network")

    monkeypatch.setattr(
        "src.services.apify_actor_alerts.post_public_http",
        forbidden_post,
    )
    assert service.dispatch_pending(
        workspace_id=DEFAULT_WORKSPACE_ID,
        limit=1,
    ) == {
        "claimed": 1,
        "succeeded": 0,
        "failed": 1,
        "retried": 0,
        "unknown": 0,
    }
    delivery = store.connect().execute(
        """
        SELECT status, error_code
        FROM apify_actor_alert_deliveries
        WHERE incident_id = ?
        """,
        (staged["incident"]["id"],),
    ).fetchone()
    assert tuple(delivery) == (
        "failed",
        "invalid_webhook_signing_secret",
    )
    unstaged = service.open_incident(
        workspace_id=DEFAULT_WORKSPACE_ID,
        route_key="x/profile",
        incident_key="route_exhausted",
        event_type="route_exhausted",
        severity="critical",
    )
    assert unstaged["delivery_staged"] is False

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
    assert exc_info.value.code == "invalid_webhook_signing_secret"
    assert exc_info.value.outcome_unknown is False
    assert network_called is False


def test_alert_secret_compensation_holds_database_write_lock(
    tmp_path,
    monkeypatch,
) -> None:
    store, service, admin_id, _email = _service(tmp_path)
    _configure_webhook(service, admin_id)
    settings = service._settings_row(DEFAULT_WORKSPACE_ID)
    assert settings is not None
    env_name = str(settings["webhook_env_name"])
    old_url = str(SecretStore(tmp_path / "data").read()[env_name])
    store.connect().execute(
        """
        CREATE TRIGGER fail_apify_alert_setting_update
        BEFORE UPDATE ON apify_actor_alert_settings
        BEGIN
            SELECT RAISE(ABORT, 'simulated database update failure');
        END
        """
    )
    store.connect().commit()
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

    with pytest.raises(
        sqlite3.IntegrityError,
        match="simulated database update failure",
    ):
        service.upsert_settings(
            workspace_id=DEFAULT_WORKSPACE_ID,
            actor_user_id=admin_id,
            webhook_url="https://hooks.example.com/replacement",
        )

    assert compensation_transaction_states == [True]
    assert SecretStore(tmp_path / "data").read()[env_name] == old_url


def test_alert_status_is_not_reinterpreted_after_settings_generation_changes(
    tmp_path,
    monkeypatch,
) -> None:
    _store, service, admin_id, _email = _service(tmp_path)
    _configure_webhook(service, admin_id)
    service.open_incident(
        workspace_id=DEFAULT_WORKSPACE_ID,
        route_key="x/profile",
        incident_key="route_degraded",
        event_type="actor_switched",
        severity="warning",
    )
    monkeypatch.setattr(
        service,
        "_send_payload",
        lambda *_args, **_kwargs: None,
    )
    assert service.dispatch_pending(
        workspace_id=DEFAULT_WORKSPACE_ID,
        limit=1,
    )["succeeded"] == 1
    assert service.get_public_settings(
        workspace_id=DEFAULT_WORKSPACE_ID
    )["last_alert_status"] == "sent"

    updated = service.upsert_settings(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=admin_id,
        webhook_provider="slack",
        webhook_url=(
            "https://hooks.slack.com/services/"
            "T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX"
        ),
    )

    assert updated["webhook_verification_mode"] == "provider_response"
    assert updated["last_alert_status"] is None


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


def test_alert_send_test_reports_unknown_without_inviting_a_duplicate(
    tmp_path,
    monkeypatch,
) -> None:
    _store, service, admin_id, _email = _service(tmp_path)
    _configure_webhook(service, admin_id)

    def unknown_send(*_args, **_kwargs) -> None:
        raise ApifyActorAlertError(
            "notification_webhook_response_invalid",
            "unsafe upstream body must stay private",
            status_code=502,
            retryable=True,
            outcome_unknown=True,
        )

    monkeypatch.setattr(service, "_send_payload", unknown_send)
    with pytest.raises(ApifyActorAlertError) as exc_info:
        service.send_test(
            workspace_id=DEFAULT_WORKSPACE_ID,
            actor_user_id=admin_id,
        )

    assert (
        exc_info.value.code
        == "apify_actor_alert_test_outcome_unknown"
    )
    assert exc_info.value.retryable is False
    assert exc_info.value.outcome_unknown is True
    assert "unsafe upstream" not in str(exc_info.value)
    internal = service._settings_row(DEFAULT_WORKSPACE_ID)
    assert internal is not None
    assert internal["last_test_status"] == "failed"
    assert (
        internal["last_test_error_code"]
        == "notification_webhook_response_invalid"
    )
    public = service.get_public_settings(
        workspace_id=DEFAULT_WORKSPACE_ID
    )
    assert public["last_test_status"] == "unknown"


@pytest.mark.parametrize(
    ("webhook_host", "event_type", "test", "expected_title"),
    (
        (
            "open.feishu.cn",
            "actor_switched",
            False,
            "Inteliscope Apify 运行告警",
        ),
        (
            "open.feishu.cn",
            "recovered",
            False,
            "Inteliscope Apify 恢复通知",
        ),
        (
            "open.larksuite.com",
            "test",
            True,
            "Inteliscope Apify 运行告警测试",
        ),
        (
            "open。feishu。cn",
            "test",
            True,
            "Inteliscope Apify 运行告警测试",
        ),
    ),
)
def test_feishu_alert_webhook_emits_text_message(
    tmp_path,
    monkeypatch,
    webhook_host,
    event_type,
    test,
    expected_title,
) -> None:
    _store, service, admin_id, _email = _service(tmp_path)
    _configure_webhook(
        service,
        admin_id,
        url=(
            f"https://{webhook_host}/open-apis/bot/v2/hook/"
            "00000000-0000-0000-0000-000000000000"
        ),
    )
    settings = service._settings_row(DEFAULT_WORKSPACE_ID)
    assert settings is not None
    requests: list[dict[str, object]] = []

    async def capture_post(_url: str, **kwargs):
        requests.append(
            {
                "headers": kwargs["headers"],
                "body": json.loads(kwargs["content"].decode("utf-8")),
            }
        )
        return httpx.Response(200, json={"code": 0})

    monkeypatch.setattr(
        "src.services.apify_actor_alerts.post_public_http",
        capture_post,
    )

    service._send_webhook(
        settings,
        {
            "event_type": event_type,
            "condition_event_type": "actor_switched",
            "severity": "warning",
            "route": 'x/profile <at user_id="all">everyone</at>',
            "status": "degraded",
            "actor_name": "ScrapeBadger",
            "active_actor_name": "Xquik",
            "reason_code": "apify_actor_placeholder",
            "occurred_at": "2026-07-29T13:50:46+00:00",
            "resolved_at": "2026-07-29T14:50:46+00:00",
        },
        test=test,
    )

    assert len(requests) == 1
    assert requests[0]["headers"] == {
        "Content-Type": "application/json; charset=utf-8"
    }
    body = requests[0]["body"]
    assert isinstance(body, dict)
    assert body["msg_type"] == "text"
    assert "event" not in body
    text = body["content"]["text"]
    assert expected_title in text
    assert "ScrapeBadger" in text
    assert "Xquik" in text
    assert "apify_actor_placeholder" in text
    assert '＜at user_id="all"＞everyone＜/at＞' in text
    assert "<at" not in text
    assert len(text) <= 3_500
    if event_type == "recovered":
        assert "原告警：自动切换 Actor" in text
        assert "告警时间：2026-07-29T13:50:46+00:00" in text
        assert "恢复时间：2026-07-29T14:50:46+00:00" in text
    if test:
        assert "这是一条模拟告警" in text


@pytest.mark.parametrize(
    "url",
    (
        "https://hooks.example.com/apify",
        (
            "https://open.feishu.cn.example.com/open-apis/bot/v2/hook/"
            "00000000-0000-0000-0000-000000000000"
        ),
        (
            "https://open.feishu.cn/open-apis/bot/hook/"
            "00000000-0000-0000-0000-000000000000"
        ),
        (
            "https://open.feishu.cn:8443/open-apis/bot/v2/hook/"
            "00000000-0000-0000-0000-000000000000"
        ),
        "https://open.feishu.cn/open-apis/bot/v2/hook/",
        (
            "https://open.feishu.cn/open-apis/bot/v2/hook/"
            "00000000-0000-0000-0000-000000000000/extra"
        ),
        (
            "https://open.feishu.cn/open-apis/bot/v2/hook/"
            "00000000-0000-0000-0000-000000000000?source=test"
        ),
    ),
)
def test_non_v2_feishu_alert_webhook_keeps_generic_envelope(
    tmp_path,
    monkeypatch,
    url,
) -> None:
    _store, service, admin_id, _email = _service(tmp_path)
    _configure_webhook(service, admin_id, url=url)
    settings = service._settings_row(DEFAULT_WORKSPACE_ID)
    assert settings is not None
    requests: list[dict[str, object]] = []

    async def capture_post(_url: str, **kwargs):
        requests.append(json.loads(kwargs["content"].decode("utf-8")))
        return httpx.Response(200)

    monkeypatch.setattr(
        "src.services.apify_actor_alerts.post_public_http",
        capture_post,
    )
    service._send_webhook(
        settings,
        {
            "event_type": "recovered",
            "severity": "info",
            "route": "x/profile",
            "status": "ready",
        },
        test=False,
    )

    assert requests == [
        {
            "event": "inteliscope.apify_actor.recovered",
            "data": {
                "event_type": "recovered",
                "severity": "info",
                "route": "x/profile",
                "status": "ready",
            },
        }
    ]


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


class _ReadyTelegramTransport:
    def is_ready(self, *, workspace_id: str) -> bool:
        return workspace_id == DEFAULT_WORKSPACE_ID


def _configure_three_alert_channels(
    store: ServiceStore,
    service: ApifyActorAlertService,
    admin_id: str,
) -> dict[str, object]:
    service.telegram_transport = _ReadyTelegramTransport()
    public = service.upsert_settings(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=admin_id,
        enabled=True,
        channels=["email", "webhook", "telegram"],
        email_address="ops@example.com",
        webhook_url="https://hooks.example.com/apify",
        telegram_chat_id="@inteliscope_alerts",
    )
    store.connect().execute(
        """
        UPDATE apify_actor_alert_settings
        SET notification_enabled_at = '2020-01-01T00:00:00+00:00'
        WHERE workspace_id = ?
        """,
        (DEFAULT_WORKSPACE_ID,),
    )
    store.connect().execute(
        """
        UPDATE apify_actor_alert_channels
        SET enabled_at = '2020-01-01T00:00:00+00:00'
        WHERE workspace_id = ?
        """,
        (DEFAULT_WORKSPACE_ID,),
    )
    store.connect().commit()
    return public


def test_three_alert_channels_fan_out_and_isolate_failure(
    tmp_path,
    monkeypatch,
) -> None:
    store, service, admin_id, _email = _service(tmp_path)
    public = _configure_three_alert_channels(
        store,
        service,
        admin_id,
    )
    assert public["channels"] == ["email", "webhook", "telegram"]
    assert "@inteliscope_alerts" not in repr(public)
    assert b"@inteliscope_alerts" not in store.db_path.read_bytes()
    opened = service.open_incident(
        workspace_id=DEFAULT_WORKSPACE_ID,
        route_key="x/profile",
        incident_key="three-channel",
        event_type="actor_switched",
        severity="warning",
    )
    assert opened["delivery_staged"] is True
    assert {
        delivery["channel"]
        for delivery in opened["incident"]["deliveries"]
    } == {"email", "webhook", "telegram"}

    attempted: list[str] = []

    def fake_send(
        settings: dict[str, object],
        _payload: dict[str, object],
        *,
        test: bool,
    ):
        assert test is False
        channel = str(settings["channel"])
        attempted.append(channel)
        if channel == "webhook":
            raise ApifyActorAlertError(
                "simulated_webhook_failure",
                "simulated",
                status_code=502,
            )
        return None

    monkeypatch.setattr(service, "_send_payload", fake_send)
    summary = service.dispatch_pending(
        workspace_id=DEFAULT_WORKSPACE_ID
    )
    assert summary == {
        "claimed": 3,
        "succeeded": 2,
        "failed": 1,
        "retried": 0,
        "unknown": 0,
    }
    assert set(attempted) == {"email", "webhook", "telegram"}
    incident = service.list_incidents(
        workspace_id=DEFAULT_WORKSPACE_ID
    )[0]
    statuses = {
        delivery["channel"]: delivery["status"]
        for delivery in incident["deliveries"]
    }
    assert statuses == {
        "email": "sent",
        "webhook": "failed",
        "telegram": "sent",
    }


def test_recovery_only_fans_out_to_channels_with_current_opening(
    tmp_path,
) -> None:
    store, service, admin_id, _email = _service(tmp_path)
    _configure_three_alert_channels(store, service, admin_id)
    service.telegram_transport = SimpleNamespace(
        is_ready=lambda **_kwargs: False
    )

    opened = service.open_incident(
        workspace_id=DEFAULT_WORKSPACE_ID,
        route_key="x/profile",
        incident_key="channel-scoped-recovery",
        event_type="actor_switched",
        severity="warning",
    )
    assert {
        delivery["channel"]
        for delivery in opened["incident"]["deliveries"]
    } == {"email", "webhook"}

    service.telegram_transport = _ReadyTelegramTransport()
    recovered = service.resolve_incident(
        workspace_id=DEFAULT_WORKSPACE_ID,
        route_key="x/profile",
        incident_key="channel-scoped-recovery",
    )
    assert recovered["delivery_staged"] is True
    recovery_channels = {
        delivery["channel"]
        for delivery in recovered["incident"]["deliveries"]
        if delivery["event_type"] == "recovered"
    }
    assert recovery_channels == {"email", "webhook"}


def test_alert_channel_generation_cooldown_and_sending_are_independent(
    tmp_path,
    monkeypatch,
) -> None:
    store, service, admin_id, _email = _service(tmp_path)
    _configure_three_alert_channels(store, service, admin_id)
    before = {
        row["channel"]: row
        for row in store.list_apify_actor_alert_channels(
            workspace_id=DEFAULT_WORKSPACE_ID
        )
    }
    opened = service.open_incident(
        workspace_id=DEFAULT_WORKSPACE_ID,
        route_key="x/profile",
        incident_key="channel-generation",
        event_type="route_exhausted",
        severity="critical",
    )
    incident_id = opened["incident"]["id"]
    store.connect().execute(
        """
        UPDATE apify_actor_alert_deliveries
        SET status = 'sending'
        WHERE incident_id = ? AND channel = 'telegram'
        """,
        (incident_id,),
    )
    store.connect().commit()

    public = service.upsert_settings(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=admin_id,
        telegram_chat_id="-1009876543210",
    )
    after = {
        row["channel"]: row
        for row in store.list_apify_actor_alert_channels(
            workspace_id=DEFAULT_WORKSPACE_ID
        )
    }
    assert after["telegram"]["generation"] == (
        before["telegram"]["generation"] + 1
    )
    assert after["email"]["generation"] == before["email"]["generation"]
    assert after["webhook"]["generation"] == before["webhook"]["generation"]
    assert "-1009876543210" not in repr(public)
    delivery_states = {
        row["channel"]: row["status"]
        for row in store.connect().execute(
            """
            SELECT channel, status
            FROM apify_actor_alert_deliveries
            WHERE incident_id = ?
            """,
            (incident_id,),
        ).fetchall()
    }
    assert delivery_states == {
        "email": "pending",
        "webhook": "pending",
        "telegram": "sending",
    }

    monkeypatch.setattr(
        service,
        "_send_payload",
        lambda _settings, _payload, *, test: None,
    )
    assert service.send_test(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=admin_id,
        channel="telegram",
    )["sent"] is True
    assert service.send_test(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=admin_id,
        channel="email",
    )["sent"] is True
    with pytest.raises(ApifyActorAlertError) as limited:
        service.send_test(
            workspace_id=DEFAULT_WORKSPACE_ID,
            actor_user_id=admin_id,
            channel="telegram",
        )
    assert limited.value.code == "apify_actor_alert_test_rate_limited"


def test_same_channel_shared_targets_are_isolated_per_incident(
    tmp_path,
    monkeypatch,
) -> None:
    store, service, admin_id, _email = _service(tmp_path)
    targets = [
        service.notification_targets.create(
            workspace_id=DEFAULT_WORKSPACE_ID,
            actor_user_id=admin_id,
            name=f"共享 Webhook {index}",
            scope="shared",
            channel="webhook",
            webhook_url=f"https://hooks.example.com/apify-target-{index}",
            webhook_provider="generic_event",
        )
        for index in (1, 2)
    ]
    watermark = "2020-01-01T00:00:00+00:00"
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
            (watermark, watermark, watermark, target["id"])
            for target in targets
        ],
    )
    store.connect().commit()
    public = service.upsert_settings(
        workspace_id=DEFAULT_WORKSPACE_ID,
        actor_user_id=admin_id,
        enabled=True,
        target_ids=[target["id"] for target in targets],
    )
    assert public["schema_version"] == 4
    assert public["target_ids"] == [target["id"] for target in targets]
    store.connect().execute(
        """
        UPDATE apify_actor_alert_settings
        SET notification_enabled_at = ?
        WHERE workspace_id = ?
        """,
        (watermark, DEFAULT_WORKSPACE_ID),
    )
    store.connect().execute(
        """
        UPDATE apify_actor_alert_target_bindings
        SET enabled_at = ?
        WHERE workspace_id = ?
        """,
        (watermark, DEFAULT_WORKSPACE_ID),
    )
    store.connect().commit()
    opened = service.open_incident(
        workspace_id=DEFAULT_WORKSPACE_ID,
        route_key="x/profile",
        incident_key="target-isolation",
        event_type="actor_switched",
        severity="warning",
    )
    assert opened["delivery_staged"] is True
    deliveries = opened["incident"]["deliveries"]
    assert {delivery["target_id"] for delivery in deliveries} == {
        target["id"] for target in targets
    }
    assert {delivery["channel"] for delivery in deliveries} == {"webhook"}
    assert opened["incident"]["schema_version"] == 3

    attempted: list[str] = []

    def fake_send(settings, _payload, *, test):
        assert test is False
        attempted.append(
            str(settings["_notification_target"]["id"])
        )

    monkeypatch.setattr(service, "_send_payload", fake_send)
    summary = service.dispatch_pending(
        workspace_id=DEFAULT_WORKSPACE_ID,
        limit=10,
    )
    assert summary == {
        "claimed": 2,
        "succeeded": 2,
        "failed": 0,
        "retried": 0,
        "unknown": 0,
    }
    assert set(attempted) == {target["id"] for target in targets}
