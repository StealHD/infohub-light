from __future__ import annotations

import pytest

from scripts.runtime_health import (
    RuntimeExpectation,
    RuntimeUnhealthy,
    check_once,
    wait_for_runtime,
)


EXPECTATION = RuntimeExpectation(
    base_url="http://local",
    expected_revision="abc123",
    expected_version="2.3.3",
    api_container="api",
    worker_container="worker",
)


def _json(_url: str):
    if _url.endswith("/live"):
        return {"data": {"status": "live", "version": "2.3.3", "revision": "abc123"}}
    return {"data": {"status": "ready", "worker_status": "ready"}}


def _bytes(url: str) -> bytes:
    return b"asset" if url.endswith(".js") else b'<script src="/assets/index.js"></script>'


def test_ready_before_container_healthy_keeps_waiting() -> None:
    states = iter(["starting", "healthy"])
    api_states: list[str] = []

    def check(expectation):
        state = next(states)
        api_states.append(state)
        return check_once(
            expectation,
            fetch_json=_json,
            fetch_bytes=_bytes,
            container_health=lambda _name: state,
        )

    detail = wait_for_runtime(
        EXPECTATION,
        timeout=5,
        interval=0,
        check=check,
        sleep=lambda _value: None,
    )

    assert api_states == ["starting", "healthy"]
    assert "ready revision=abc123" in detail


def test_both_healthy_are_required() -> None:
    health = {"api": "healthy", "worker": "starting"}

    ready, detail = check_once(
        EXPECTATION,
        fetch_json=_json,
        fetch_bytes=_bytes,
        container_health=health.__getitem__,
    )

    assert ready is False
    assert "worker=starting" in detail


def test_exact_source_digest_is_part_of_success() -> None:
    expectation = RuntimeExpectation(
        **{**EXPECTATION.__dict__, "expected_source_digest": "sha256:expected"}
    )

    ready, detail = check_once(
        expectation,
        fetch_json=_json,
        fetch_bytes=_bytes,
        container_health=lambda _name: "healthy",
        container_source_digest=lambda name: (
            "sha256:expected" if name == "api" else "sha256:stale"
        ),
    )

    assert ready is False
    assert detail == "waiting for exact source digest"


def test_unhealthy_fails_immediately() -> None:
    with pytest.raises(RuntimeUnhealthy, match="api=unhealthy"):
        check_once(
            EXPECTATION,
            fetch_json=_json,
            fetch_bytes=_bytes,
            container_health=lambda name: "unhealthy" if name == "api" else "healthy",
        )


def test_timeout_reports_last_pending_reason() -> None:
    clock = iter([0.0, 0.0, 2.0])

    with pytest.raises(TimeoutError, match="still starting"):
        wait_for_runtime(
            EXPECTATION,
            timeout=1,
            interval=0,
            check=lambda _expectation: (False, "still starting"),
            sleep=lambda _value: None,
            monotonic=lambda: next(clock),
        )


def test_public_revision_is_part_of_success() -> None:
    expectation = RuntimeExpectation(
        **{**EXPECTATION.__dict__, "public_url": "https://public.example"}
    )

    def fetch_json(url: str):
        if url.startswith("https://public.example"):
            return {"data": {"status": "live", "revision": "old"}}
        return _json(url)

    ready, detail = check_once(
        expectation,
        fetch_json=fetch_json,
        fetch_bytes=_bytes,
        container_health=lambda _name: "healthy",
    )

    assert ready is False
    assert detail == "waiting for public revision"
