import asyncio
import json
import logging
import stat
import time
from datetime import datetime, timezone

import pytest

from src.logging_utils import (
    configure_logging,
    logging_health_status,
    log_retention_days,
    prune_managed_logs,
    redact_log_text,
)
from src.observability_context import (
    begin_observability_context,
    reset_observability_context,
)
from src.services.operation_log import (
    emit_operation_event,
    safe_emit_operation_event,
)


def _close_managed_handlers() -> None:
    for logger in (logging.getLogger(), logging.getLogger("inteliscope.operations")):
        for handler in tuple(logger.handlers):
            if getattr(handler, "_inteliscope_managed_handler", False):
                logger.removeHandler(handler)
                handler.close()


@pytest.fixture(autouse=True)
def close_logging_handlers():
    yield
    _close_managed_handlers()


def test_configure_logging_writes_private_redacted_runtime_and_operation_jsonl(
    tmp_path,
):
    paths = configure_logging(tmp_path / "logs", service="api", retention_days=30)

    logging.getLogger("test.runtime").error(
        "authorization=Bearer abc@example.com webhook_url=https://example.com/hook"
    )
    event = emit_operation_event(
        category="job",
        action="queue",
        outcome="queued",
        workspace_id="workspace_1",
        actor_user_id="user_1",
        job_id="job_1",
        counts={"attempts": 1},
    )
    for logger in (logging.getLogger(), logging.getLogger("inteliscope.operations")):
        for handler in logger.handlers:
            handler.flush()

    assert stat.S_IMODE(paths["directory"].stat().st_mode) == 0o700
    assert stat.S_IMODE(paths["runtime"].stat().st_mode) == 0o600
    assert stat.S_IMODE(paths["operations"].stat().st_mode) == 0o600
    runtime = paths["runtime"].read_text(encoding="utf-8")
    assert "abc@example.com" not in runtime
    assert "https://example.com/hook" not in runtime
    assert "<redacted" in runtime
    operation = json.loads(paths["operations"].read_text(encoding="utf-8"))
    assert operation == {
        **event,
        "service": "api",
    }
    assert operation["timestamp"].endswith("Z")
    assert datetime.fromisoformat(
        operation["timestamp"].replace("Z", "+00:00")
    ).tzinfo == timezone.utc
    assert "message" not in operation


def test_configure_logging_is_repeatable_without_duplicate_managed_handlers(tmp_path):
    configure_logging(tmp_path / "logs", service="worker")
    configure_logging(tmp_path / "logs", service="worker")
    root = logging.getLogger()
    operation = logging.getLogger("inteliscope.operations")
    assert (
        len(
            [
                handler
                for handler in root.handlers
                if getattr(handler, "_inteliscope_managed_handler", False)
            ]
        )
        == 2
    )
    assert (
        len(
            [
                handler
                for handler in operation.handlers
                if getattr(handler, "_inteliscope_managed_handler", False)
            ]
        )
        == 1
    )


def test_runtime_level_never_suppresses_critical_operation_events(tmp_path):
    paths = configure_logging(
        tmp_path / "logs",
        service="worker",
        level="ERROR",
    )

    logging.getLogger("test.runtime").info("runtime-info")
    emit_operation_event(
        category="job",
        action="claim",
        outcome="running",
        workspace_id="workspace_1",
        subject_user_id="user_1",
        job_id="job_1",
    )
    for logger in (logging.getLogger(), logging.getLogger("inteliscope.operations")):
        for handler in logger.handlers:
            handler.flush()

    assert paths["runtime"].read_text(encoding="utf-8") == ""
    operation = json.loads(paths["operations"].read_text(encoding="utf-8"))
    assert operation["action"] == "claim"
    assert operation["level"] == "info"


def test_runtime_log_rotates_daily_in_utc_with_private_files(tmp_path):
    paths = configure_logging(tmp_path / "logs", service="api")
    runtime_handler = next(
        handler
        for handler in logging.getLogger().handlers
        if getattr(handler, "_inteliscope_managed_handler", False)
        and getattr(handler, "baseFilename", "").endswith(
            "runtime-api.jsonl"
        )
    )
    assert runtime_handler.utc is True
    assert runtime_handler.when == "MIDNIGHT"

    logging.getLogger("rotation").info("before rollover")
    runtime_handler.rolloverAt = int(time.time()) - 1
    logging.getLogger("rotation").info("after rollover")
    runtime_handler.flush()

    rotations = list(paths["directory"].glob("runtime-api.jsonl.*"))
    assert len(rotations) == 1
    assert stat.S_IMODE(rotations[0].stat().st_mode) == 0o600
    current = [
        json.loads(line)
        for line in paths["runtime"].read_text(encoding="utf-8").splitlines()
    ]
    assert current[-1]["timestamp"].endswith("Z")
    assert current[-1]["message"] == "after rollover"


def test_runtime_exception_keeps_safe_frames_without_exception_text(tmp_path):
    paths = configure_logging(tmp_path / "logs", service="worker")

    try:
        raise RuntimeError("upstream-private-response")
    except RuntimeError:
        logging.getLogger("exception-test").exception(
            "worker boundary failed"
        )
    for handler in logging.getLogger().handlers:
        handler.flush()

    serialized = paths["runtime"].read_text(encoding="utf-8")
    assert "upstream-private-response" not in serialized
    event = json.loads(serialized)
    assert event["message"] == "worker boundary failed"
    assert event["exception"]["type"] == "RuntimeError"
    assert event["exception"]["frames"][-1]["file"] == "test_logging_utils.py"
    assert "line" in event["exception"]["frames"][-1]


def test_runtime_context_is_isolated_across_concurrent_tasks(tmp_path):
    paths = configure_logging(tmp_path / "logs", service="worker")

    async def write_one(request_id, job_id):
        token = begin_observability_context(
            request_id=request_id,
            job_id=job_id,
            stage="execute",
        )
        try:
            await asyncio.sleep(0)
            logging.getLogger("context-test").info("context-%s", job_id)
        finally:
            reset_observability_context(token)

    async def write_both():
        await asyncio.gather(
            write_one("req_one", "job_one"),
            write_one("req_two", "job_two"),
        )

    asyncio.run(write_both())
    for handler in logging.getLogger().handlers:
        handler.flush()

    events = {
        event["message"]: event
        for event in (
            json.loads(line)
            for line in paths["runtime"].read_text(
                encoding="utf-8"
            ).splitlines()
        )
    }
    assert events["context-job_one"]["request_id"] == "req_one"
    assert events["context-job_one"]["job_id"] == "job_one"
    assert events["context-job_one"]["stage"] == "execute"
    assert events["context-job_two"]["request_id"] == "req_two"
    assert events["context-job_two"]["job_id"] == "job_two"


def test_operation_sink_failure_is_truthful_and_degrades_health(tmp_path):
    configure_logging(tmp_path / "logs", service="api")
    operation_handler = next(
        handler
        for handler in logging.getLogger("inteliscope.operations").handlers
        if getattr(handler, "channel", None) == "operations"
    )

    class FailingStream:
        def write(self, _value):
            raise OSError("simulated disk failure")

        def flush(self):
            return None

        def close(self):
            return None

    operation_handler.stream.close()
    operation_handler.stream = FailingStream()

    assert (
        safe_emit_operation_event(
            category="job",
            action="claim",
            outcome="running",
            workspace_id="workspace_1",
            subject_user_id="user_1",
            job_id="job_1",
        )
        is False
    )
    health = logging_health_status()
    assert health["status"] == "degraded"
    assert health["channels"]["operations"]["status"] == "degraded"
    assert health["channels"]["operations"]["last_failure"] is not None


@pytest.mark.parametrize("value", ["", "0", "366", "1.5", "thirty", True])
def test_log_retention_days_rejects_invalid_values_without_echoing_them(value):
    with pytest.raises(
        ValueError,
        match="HORIZON_LOG_RETENTION_DAYS must be an integer from 1 to 365",
    ) as error:
        log_retention_days(value)
    if str(value):
        assert str(value) not in str(error.value)


def test_invalid_environment_configuration_stops_before_creating_log_files(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("HORIZON_LOG_RETENTION_DAYS", "0")
    with pytest.raises(ValueError, match="HORIZON_LOG_RETENTION_DAYS"):
        configure_logging(tmp_path / "logs", service="api")
    assert not (tmp_path / "logs").exists()


def test_invalid_log_level_stops_before_creating_log_files(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("HORIZON_LOG_LEVEL", "verbose")
    with pytest.raises(ValueError, match="HORIZON_LOG_LEVEL is invalid"):
        configure_logging(tmp_path / "logs", service="api")
    assert not (tmp_path / "logs").exists()


def test_configure_logging_refuses_managed_file_symlinks(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    outside = tmp_path / "outside.jsonl"
    outside.write_text("must-not-change", encoding="utf-8")
    (log_dir / "runtime-api.jsonl").symlink_to(outside)

    with pytest.raises(ValueError, match="regular file"):
        configure_logging(log_dir, service="api")

    assert outside.read_text(encoding="utf-8") == "must-not-change"


def test_prune_managed_logs_only_removes_expired_owned_rotations(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    expired = log_dir / "operations-api.jsonl.2026-06-24"
    retained = log_dir / "runtime-worker.jsonl.2026-06-25"
    current = log_dir / "operations-api.jsonl"
    unrelated = log_dir / "service-api-smoke-20260601.json"
    outside = tmp_path / "outside.jsonl"
    linked = log_dir / "runtime-api.jsonl.2026-06-01"
    for path in (expired, retained, current, unrelated):
        path.write_text("data", encoding="utf-8")
    outside.write_text("outside", encoding="utf-8")
    linked.symlink_to(outside)

    removed = prune_managed_logs(
        log_dir,
        30,
        now=datetime(2026, 7, 24, tzinfo=timezone.utc),
    )

    assert removed == [expired]
    assert not expired.exists()
    assert retained.exists() and current.exists() and unrelated.exists()
    assert linked.is_symlink()
    assert outside.read_text(encoding="utf-8") == "outside"


def test_redact_log_text_removes_destinations_and_common_secret_shapes():
    rendered = redact_log_text(
        "authorization=Bearer opaque-value-123 "
        "password=hunter2 token=ih_mcp_v1_abcdefghi "
        "key sk-abcdefghij email dev@example.com url https://example.com/path?q=1 "
        "article_id=private-article HORIZON_AUTH_PASSWORD"
    )
    for secret in (
        "opaque-value-123",
        "hunter2",
        "ih_mcp_v1_abcdefghi",
        "sk-abcdefghij",
        "dev@example.com",
        "https://example.com/path?q=1",
        "private-article",
        "HORIZON_AUTH_PASSWORD",
    ):
        assert secret not in rendered

    assert "private tag" not in redact_log_text(
        'payload={"personal_tags":["private tag"]}'
    )
    assert "basic-private-value" not in redact_log_text(
        "Authorization: Basic basic-private-value"
    )
    assert "two word value" not in redact_log_text(
        "password=two word value"
    )
    assert "private response body" not in redact_log_text(
        "upstream response: private response body"
    )
    assert "private label" not in redact_log_text(
        "personal label: private label"
    )


@pytest.mark.parametrize(
    "unsafe_identifier",
    [
        "https://private.example/path",
        "person@example.com",
        "Bearer-private-value",
        "HORIZON_AUTH_PASSWORD",
        "ih_mcp_v1_private-token",
        "sk-private-key",
    ],
)
def test_operation_schema_rejects_sensitive_identifier_shapes(
    unsafe_identifier,
):
    with pytest.raises(ValueError, match="opaque identifier"):
        emit_operation_event(
            category="job",
            action="queue",
            outcome="queued",
            workspace_id="workspace_1",
            actor_user_id="user_1",
            error_code=unsafe_identifier,
        )
