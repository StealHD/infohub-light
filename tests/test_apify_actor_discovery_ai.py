"""Discovery AI Manifest JSON parsing tolerates model prose and fences."""

from __future__ import annotations

import pytest

from src.services.apify_actor_discovery import ActorDiscoveryError
from src.services.worker_actor_discovery_ai import (
    _extract_json_object,
    _parse_ai_manifest,
)


class _Metrics:
    def __init__(self, finish_reason: str | None = None) -> None:
        self.finish_reason = finish_reason


class _FakeOps:
    def __init__(self) -> None:
        self.metrics: list[dict] = []

    def record_discovery_ai_metrics(self, run_id: str, **kwargs: object) -> None:
        self.metrics.append(kwargs)


class _FakeContext:
    def __init__(self) -> None:
        self.ops = _FakeOps()
        self.run_id = "run-1"
        self.output_limit = 1024
        self.ai_client = None


def _parse(raw: str, *, finish_reason: str | None = None) -> dict:
    return _parse_ai_manifest(
        _FakeContext(),
        raw=raw,
        metrics=_Metrics(finish_reason),
    )


def test_extract_json_object_strips_markdown_fence() -> None:
    assert _extract_json_object('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_extract_json_object_extracts_from_prose() -> None:
    assert _extract_json_object('Here is the object: {"a": 1} thanks') == '{"a": 1}'


def test_extract_json_object_keeps_pure_json() -> None:
    assert _extract_json_object('{"a": 1}') == '{"a": 1}'


def test_parse_accepts_markdown_fenced_object() -> None:
    assert _parse('```json\n{"version": 1, "actor_id": "x/foo"}\n```') == {
        "version": 1,
        "actor_id": "x/foo",
    }


def test_parse_accepts_prose_wrapped_object() -> None:
    assert _parse('Sure, here you go: {"version": 1}') == {"version": 1}


def test_parse_accepts_plain_object() -> None:
    assert _parse('{"version": 1}') == {"version": 1}


def test_parse_empty_content_raises_empty() -> None:
    with pytest.raises(ActorDiscoveryError) as exc:
        _parse("   ")
    assert exc.value.code == "discovery_ai_empty_content"


def test_parse_garbage_raises_invalid_json() -> None:
    with pytest.raises(ActorDiscoveryError) as exc:
        _parse("not json at all")
    assert exc.value.code == "discovery_ai_invalid_json"


def test_parse_truncated_raises_output_truncated() -> None:
    with pytest.raises(ActorDiscoveryError) as exc:
        _parse('{"version": 1', finish_reason="length")
    assert exc.value.code == "discovery_ai_output_truncated"


def test_parse_non_object_raises_contract_invalid() -> None:
    with pytest.raises(ActorDiscoveryError) as exc:
        _parse('["a", "b"]')
    assert exc.value.code == "discovery_ai_contract_invalid"
