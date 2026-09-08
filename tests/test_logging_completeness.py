"""Behavioral regressions for private log completeness and sink isolation."""

import asyncio
import json
import logging

import pytest

from src.logging_diagnostics import log_exception
from src.logging_utils import configure_logging, logging_health_status
from src.observability_context import (
    begin_observability_context, reset_observability_context, update_observability_context,
)
from src.services.operation_log import OperationLogQueryService, safe_emit_operation_event


@pytest.fixture
def logs(tmp_path):
    paths = configure_logging(tmp_path / "logs", service="worker")
    yield paths
    for logger in (logging.getLogger(), logging.getLogger("inteliscope.operations")):
        for handler in tuple(logger.handlers):
            if getattr(handler, "_inteliscope_managed_handler", False):
                logger.removeHandler(handler)
                handler.close()


def _read(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def _emit(**overrides):
    return safe_emit_operation_event(**dict(
        category="job", action="finish", outcome="failed", level="error", **overrides,
    ))


def test_concurrent_operation_context_inherits_and_can_be_cleared(logs):
    async def one(suffix):
        token = begin_observability_context(
            workspace_id="ws_test", request_id=f"req_{suffix}", job_id=f"job_{suffix}",
            source_id=f"source_{suffix}", subscription_id=f"sub_{suffix}",
            stage="execute", error_code="source_failed",
        )
        try:
            await asyncio.sleep(0)
            assert _emit(counts={"attempts": 2})
            update_observability_context(source_id="", subscription_id="", error_code="")
            assert _emit(stage="finish", job_id="job_override")
        finally:
            reset_observability_context(token)

    async def both():
        await asyncio.gather(one("one"), one("two"))

    asyncio.run(both())
    assert _emit(stage="worker_boundary")
    events = _read(logs["operations"])
    for event in events[:4]:
        if event["job_id"] == "job_override":
            assert not {"source_id", "subscription_id", "error_code"} & event.keys()
            assert event["stage"] == "finish"
        else:
            suffix = event["job_id"].removeprefix("job_")
            assert event["request_id"] == f"req_{suffix}"
            assert event["source_id"] == f"source_{suffix}"
            assert event["subscription_id"] == f"sub_{suffix}"
            assert event["error_code"] == "source_failed"
            assert event["counts"]["attempts"] == 2
    assert not {"workspace_id", "request_id", "job_id", "source_id"} & events[-1].keys()


@pytest.mark.parametrize("field,value", [
    ("request_id", "https://example.com/private"), ("source_id", "sk-private-secret"),
    ("job_id", ["private"]), ("subscription_id", {"private": "value"}),
    ("error_code", "PRIVATE_ENV_NAME"), ("stage", "Bearer secret"),
])
def test_invalid_runtime_extra_is_omitted_and_accounted_for(logs, field, value):
    logger = logging.getLogger("completeness")
    logger.warning("safe diagnostic", extra={field: value})
    record = _read(logs["runtime"])[-1]
    assert record["message"] == "safe diagnostic"
    assert field not in record
    health = logging_health_status()["channels"]["runtime"]
    assert health["status"] == "degraded" and health["validation_failures"] == 1
    assert health["write_failures"] == 0
    logger.info("next valid diagnostic")
    assert _read(logs["runtime"])[-1]["logging_recovery"]["last_failure_kind"] == "validation"
    health = logging_health_status()["channels"]["runtime"]
    assert health["status"] == "ready" and health["recovery_count"] == 1


def test_operation_validation_failure_recovery_and_public_projection(logs, monkeypatch):
    monkeypatch.setenv("INTELISCOPE_VERSION", "2.6.11")
    monkeypatch.setenv("INTELISCOPE_BUILD_REVISION", "b6f42227" + "0" * 32)
    assert not _emit(job_id="sk-private-secret")
    assert logging_health_status()["channels"]["operations"]["validation_failures"] == 1
    assert _emit(job_id="job_test", workspace_id="ws_test", actor_user_id="user_test")
    event = _read(logs["operations"])[-1]
    assert event["revision"] == "b6f42227" + "0" * 32 and event["version"] == "2.6.11"
    assert event["logging_recovery"]["validation_failures"] == 1
    runtime = _read(logs["runtime"])[-1]
    assert runtime["revision"] == event["revision"]
    public = OperationLogQueryService(logs["directory"]).query(workspace_id="ws_test", user_id="user_test")
    assert len(public["events"]) == 1
    assert not {"revision", "version", "logging_recovery"} & public["events"][0].keys()
    assert "sk-private-secret" not in logs["operations"].read_text()


@pytest.mark.parametrize("channel, failure", [("runtime", "write"), ("operations", "write"), ("operations", "rotate"), ("operations", "flush")])
def test_sink_failure_and_recovery_preserve_truthful_ack(logs, monkeypatch, channel, failure):
    logger = logging.getLogger() if channel == "runtime" else logging.getLogger("inteliscope.operations")
    handler = next(h for h in logger.handlers if getattr(h, "channel", None) == channel)

    def fail(*_args):
        raise OSError("private-disk-error")

    with monkeypatch.context() as patch:
        if failure == "rotate":
            patch.setattr(handler, "shouldRollover", lambda _: True)
            patch.setattr(handler, "doRollover", fail)
        elif failure == "flush":
            patch.setattr(handler, "flush", fail)
        else:
            patch.setattr(handler.stream, "write", fail)
        if channel == "operations":
            assert not _emit()
        else:
            logger.error("safe failed write")
        state = logging_health_status()["channels"][channel]
        assert state["write_failures"] == 1 and state["status"] == "degraded"
    if channel == "operations":
        assert _emit()
    else:
        logger.info("safe recovery")
    record = _read(logs[channel])[-1]
    assert record["logging_recovery"]["write_failures"] == 1
    assert "private-disk-error" not in logs[channel].read_text()
    assert logging_health_status()["channels"][channel]["recovery_count"] == 1


def test_gathered_exception_has_safe_source_location_without_values(logs):
    import src.logging_metadata as metadata

    filename = str(metadata._SOURCE_ROOT / "services" / "synthetic_probe.py")
    try:
        exec(compile("raise RuntimeError('private-upstream-payload')", filename, "exec"), {})
    except RuntimeError as exception:
        captured = exception
    log_exception(logging.getLogger("probe"), stage="acquisition", error_code="source_failed", exception=captured)
    serialized = logs["runtime"].read_text()
    record = _read(logs["runtime"])[-1]
    assert "private-upstream-payload" not in serialized
    assert str(metadata._SOURCE_ROOT) not in serialized
    assert record["exception"]["frames"][-1]["file"] == "src/services/synthetic_probe.py"
    assert record["exception"]["frames"][-1]["line"] == 1
    assert record["exception"]["type"] == "RuntimeError"
    assert record["error_fingerprint"].startswith("err_")


def test_real_source_fetch_scope_survives_concurrency_and_exception(logs):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from src.orchestrator import HorizonOrchestrator

    class StubOrchestrator:
        _service_attempt_meter = None
        _service_acquisition_coordinator = None

        async def _fetch_with_progress(self, label, scraper, since):
            await asyncio.sleep(0)
            logging.getLogger("fetch-test").info("source fetch diagnostic")
            if label == "bad":
                raise RuntimeError("private-upstream-value")
            return []

        def _capture_service_apify_watermark(self, fetched):
            pass

    async def fetch(label):
        return await HorizonOrchestrator._fetch_service_source(
            StubOrchestrator(), label, None,
            SimpleNamespace(source_id=f"src_{label}", subscription_id=f"sub_{label}"),
            datetime.now(timezone.utc),
        )

    async def both():
        token = begin_observability_context(job_id="job_parent", source_id="src_parent", stage="execute")
        try:
            results = await asyncio.gather(fetch("good"), fetch("bad"), return_exceptions=True)
            assert results[0] == [] and isinstance(results[1], RuntimeError)
            from src.observability_context import current_observability_context
            assert current_observability_context().source_id == "src_parent"
        finally:
            reset_observability_context(token)

    asyncio.run(both())
    records = _read(logs["runtime"])
    fetched = [record for record in records if record["message"] == "source fetch diagnostic"]
    assert {record["source_id"] for record in fetched} == {"src_good", "src_bad"}
    assert all(record["job_id"] == "job_parent" for record in fetched)
    exception = next(record for record in records if "exception" in record)
    assert exception["source_id"] == "src_bad" and exception["subscription_id"] == "sub_bad"
    assert "private-upstream-value" not in logs["runtime"].read_text()


def test_runtime_operation_copy_uses_resolved_event_overrides(logs):
    token = begin_observability_context(job_id="job_parent", source_id="src_parent")
    try:
        assert _emit(job_id="job_child", source_id="")
    finally:
        reset_observability_context(token)
    event = _read(logs["runtime"])[-1]
    assert event["job_id"] == "job_child" and "source_id" not in event
