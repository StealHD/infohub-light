"""Bounded AI adapter used by the Worker Actor discovery handler."""

from __future__ import annotations

import json
import time
from typing import Any, Protocol

import httpx


class DiscoveryAiContext(Protocol):
    ops: Any
    run_id: str
    output_limit: int
    ai_client: Any


def _ai_error_code(error: Exception) -> str:
    status = getattr(error, "status_code", None)
    name = type(error).__name__.casefold()
    if "timeout" in name or isinstance(error, (TimeoutError, httpx.TimeoutException)):
        return "discovery_ai_timeout"
    if status in {401, 403}:
        return "discovery_ai_authentication_failed"
    if status == 402:
        return "discovery_ai_balance_unavailable"
    if status == 404:
        return "discovery_ai_model_unavailable"
    if status == 429:
        return "discovery_ai_rate_limited"
    return "discovery_ai_transport_unavailable"


async def _complete_ai(
    context: DiscoveryAiContext,
    prompt: dict[str, Any],
    *,
    started: float,
) -> str:
    from .apify_actor_discovery import ActorDiscoveryError

    try:
        return await context.ai_client.complete(
            (
                "Return one strict JSON object only. Follow the supplied "
                "Manifest v1 contract exactly. Never invent Actor IDs, "
                "Build IDs, schema fields, code, templates, credentials, "
                "headers, tokens, or URLs."
            ),
            json.dumps(prompt, ensure_ascii=False, sort_keys=True),
            temperature=0.0,
            max_tokens=context.output_limit,
        )
    except Exception as error:
        context.ops.record_discovery_ai_metrics(
            context.run_id,
            latency_ms=int((time.monotonic() - started) * 1000),
            json_status="unknown",
            manifest_status="not_run",
        )
        raise ActorDiscoveryError(
            _ai_error_code(error),
            "Actor discovery AI request failed",
        ) from error


def _record_completion_metrics(
    context: DiscoveryAiContext,
    *,
    raw: str,
    started: float,
) -> Any:
    metrics = getattr(context.ai_client, "last_completion_metrics", None)
    context.ops.record_discovery_ai_metrics(
        context.run_id,
        input_tokens=(metrics.input_tokens if metrics else None),
        completion_tokens=(metrics.completion_tokens if metrics else None),
        reasoning_tokens=(metrics.reasoning_tokens if metrics else None),
        content_tokens=(metrics.content_tokens if metrics else None),
        finish_reason=(metrics.finish_reason if metrics else None),
        latency_ms=int((time.monotonic() - started) * 1000),
        response_bytes=(metrics.response_bytes if metrics else len(raw.encode("utf-8"))),
        json_status="unknown",
        manifest_status="not_run",
    )
    return metrics


def _parse_ai_manifest(
    context: DiscoveryAiContext,
    *,
    raw: str,
    metrics: Any,
) -> dict[str, Any]:
    from .apify_actor_discovery import ActorDiscoveryError

    if not raw.strip():
        context.ops.record_discovery_ai_metrics(context.run_id, json_status="empty")
        raise ActorDiscoveryError(
            "discovery_ai_empty_content",
            "Actor discovery AI returned no content",
        )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        status = "truncated" if metrics and metrics.finish_reason == "length" else "invalid"
        context.ops.record_discovery_ai_metrics(context.run_id, json_status=status)
        code = (
            "discovery_ai_output_truncated"
            if status == "truncated"
            else "discovery_ai_invalid_json"
        )
        raise ActorDiscoveryError(
            code,
            "Actor discovery AI returned invalid JSON",
        ) from error
    if not isinstance(parsed, dict):
        context.ops.record_discovery_ai_metrics(context.run_id, json_status="invalid")
        raise ActorDiscoveryError(
            "discovery_ai_contract_invalid",
            "Actor discovery AI output must be an object",
        )
    context.ops.record_discovery_ai_metrics(context.run_id, json_status="valid")
    return parsed


async def generate_manifest(
    context: DiscoveryAiContext,
    prompt: dict[str, Any],
) -> dict[str, Any]:
    started = time.monotonic()
    raw = await _complete_ai(context, prompt, started=started)
    metrics = _record_completion_metrics(context, raw=raw, started=started)
    return _parse_ai_manifest(context, raw=raw, metrics=metrics)
