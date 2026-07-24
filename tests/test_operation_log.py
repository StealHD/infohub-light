import json
from datetime import datetime, timedelta, timezone

import pytest

from src.services.operation_log import OperationLogQueryService


NOW = datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc)


def _event(**updates):
    base = {
        "schema_version": 1,
        "event_id": "evt_1",
        "timestamp": (NOW - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        "level": "info",
        "service": "api",
        "category": "job",
        "action": "queue",
        "outcome": "queued",
        "workspace_id": "workspace_1",
        "actor_user_id": "user_1",
        "job_id": "job_1",
    }
    return {**base, **updates}


def _write(path, events):
    path.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
        encoding="utf-8",
    )


def test_query_operation_logs_filters_current_user_and_strips_internal_fields(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    _write(
        log_dir / "operations-api.jsonl",
        [
            _event(),
            _event(
                event_id="evt_other",
                actor_user_id="user_2",
                job_id="job_other",
            ),
            _event(
                event_id="evt_subject",
                actor_user_id="admin_1",
                subject_user_id="user_1",
                category="account",
                action="password_reset",
                outcome="ok",
                job_id=None,
            ),
        ],
    )

    result = OperationLogQueryService(log_dir).query(
        workspace_id="workspace_1",
        user_id="user_1",
        lookback_hours=24,
        now=NOW,
    )

    assert [event["event_id"] for event in result["events"]] == [
        "evt_subject",
        "evt_1",
    ]
    serialized = json.dumps(result, ensure_ascii=False)
    assert "workspace_1" not in serialized
    assert "user_1" not in serialized
    assert "user_2" not in serialized
    assert "admin_1" not in serialized
    assert "job_other" not in serialized


def test_query_operation_logs_applies_filters_bounds_and_newest_first(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    _write(
        log_dir / "operations-worker.jsonl",
        [
            _event(
                event_id="evt_old",
                timestamp=(NOW - timedelta(hours=25)).isoformat(),
            ),
            _event(
                event_id="evt_error",
                timestamp=(NOW - timedelta(minutes=2)).isoformat(),
                level="error",
                category="acquisition",
                action="fetch",
                outcome="failed",
                source_id="source_1",
                error_code="network_timeout",
            ),
            _event(
                event_id="evt_warning",
                timestamp=(NOW - timedelta(minutes=3)).isoformat(),
                level="warning",
                category="acquisition",
                action="fetch",
                outcome="failed",
                source_id="source_2",
            ),
        ],
    )

    result = OperationLogQueryService(log_dir).query(
        workspace_id="workspace_1",
        user_id="user_1",
        category="acquisition",
        outcome="failed",
        minimum_level="error",
        source_id="source_1",
        now=NOW,
    )

    assert [event["event_id"] for event in result["events"]] == ["evt_error"]
    assert result["availability"] == "available"
    assert result["returned"] == 1


def test_query_operation_logs_skips_partial_tampered_and_symlink_files(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    valid = _event(event_id="evt_valid")
    tampered = _event(
        event_id="evt_tampered",
        action="secret from https://example.com",
    )
    credential_shaped = _event(
        event_id="evt_credential",
        error_code="HORIZON_AUTH_PASSWORD",
    )
    target = tmp_path / "outside.jsonl"
    _write(target, [_event(event_id="evt_outside")])
    (log_dir / "operations-cli.jsonl").symlink_to(target)
    (log_dir / "operations-api.jsonl").write_text(
        json.dumps(valid)
        + "\n"
        + json.dumps(tampered)
        + "\n"
        + json.dumps(credential_shaped)
        + "\n"
        + '{"partial":',
        encoding="utf-8",
    )

    result = OperationLogQueryService(log_dir).query(
        workspace_id="workspace_1",
        user_id="user_1",
        now=NOW,
    )

    assert [event["event_id"] for event in result["events"]] == ["evt_valid"]


def test_query_operation_logs_reports_scan_truncation_and_unavailable(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    _write(
        log_dir / "operations-api.jsonl",
        [_event(event_id=f"evt_{index}") for index in range(5)],
    )
    result = OperationLogQueryService(log_dir, max_scan_records=2).query(
        workspace_id="workspace_1",
        user_id="user_1",
        now=NOW,
    )
    assert result["truncated"] is True
    assert result["returned"] == 2

    unsafe = tmp_path / "unsafe"
    unsafe.symlink_to(log_dir, target_is_directory=True)
    unavailable = OperationLogQueryService(unsafe).query(
        workspace_id="workspace_1",
        user_id="user_1",
        now=NOW,
    )
    assert unavailable["availability"] == "unavailable"
    assert unavailable["events"] == []


def test_query_operation_logs_returns_unavailable_when_a_file_cannot_be_read(
    tmp_path,
    monkeypatch,
):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    _write(log_dir / "operations-api.jsonl", [_event()])

    def unreadable(_path):
        raise OSError("permission denied")

    monkeypatch.setattr(
        "src.services.operation_log._reverse_lines",
        unreadable,
    )
    result = OperationLogQueryService(log_dir).query(
        workspace_id="workspace_1",
        user_id="user_1",
        now=NOW,
    )

    assert result["availability"] == "unavailable"
    assert result["events"] == []
    assert result["returned"] == 0


@pytest.mark.parametrize(
    ("argument", "value"),
    [
        ("lookback_hours", 0),
        ("lookback_hours", 721),
        ("limit", 0),
        ("limit", 101),
        ("minimum_level", "debug"),
    ],
)
def test_query_operation_logs_rejects_out_of_contract_inputs(
    tmp_path, argument, value
):
    kwargs = {argument: value}
    with pytest.raises(ValueError):
        OperationLogQueryService(tmp_path / "logs").query(
            workspace_id="workspace_1",
            user_id="user_1",
            **kwargs,
        )
