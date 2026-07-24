#!/usr/bin/env python3
"""Run the bounded, credential-safe Remote MCP read-only canary."""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
import os
import time
from contextlib import asynccontextmanager
from functools import partial
from typing import Any
from urllib.parse import urlsplit

import anyio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import LATEST_PROTOCOL_VERSION


ALL_REMOTE_TOOLS = (
    "get_my_feed",
    "get_item",
    "list_subscriptions",
    "source_health",
    "list_jobs",
    "get_job",
    "get_source_setup_guide",
    "list_available_sources",
    "prepare_create_subscription",
    "prepare_update_subscription",
    "prepare_delete_subscription",
    "apply_subscription_change",
    "diagnose_source",
    "diagnose_job",
    "query_operation_logs",
)
SAFE_READ_TOOLS = (
    "get_my_feed",
    "get_item",
    "list_subscriptions",
    "source_health",
    "list_jobs",
    "get_job",
    "get_source_setup_guide",
    "list_available_sources",
    "diagnose_source",
    "diagnose_job",
    "query_operation_logs",
)


class CanaryFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _validated_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/mcp"
        or parsed.query
        or parsed.fragment
    ):
        raise CanaryFailure("invalid_url")
    try:
        loopback = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        loopback = parsed.hostname.lower() == "localhost"
    if not loopback and parsed.scheme != "https":
        raise CanaryFailure("invalid_url")
    return value


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


@asynccontextmanager
async def _session(
    *,
    url: str,
    token: str,
    transport: httpx.AsyncBaseTransport | None,
):
    async with httpx.AsyncClient(
        transport=transport,
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx.Timeout(30.0, connect=10.0),
    ) as client:
        async with streamable_http_client(
            url,
            http_client=client,
            terminate_on_close=False,
        ) as (read_stream, write_stream, _get_session_id):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session


async def _read_call(
    session: ClientSession,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    latencies: list[float],
) -> dict[str, Any]:
    started = time.perf_counter()
    result = await session.call_tool(tool_name, arguments)
    latencies.append((time.perf_counter() - started) * 1000.0)
    if result.isError:
        raise CanaryFailure("read_tool_failed")
    structured = result.structuredContent
    if not isinstance(structured, dict):
        raise CanaryFailure("invalid_tool_result")
    return structured


async def _expect_tool_error(
    session: ClientSession,
    tool_name: str,
    arguments: dict[str, Any],
    expected_code: str,
) -> None:
    result = await session.call_tool(tool_name, arguments)
    if (
        not result.isError
        or not result.content
        or not getattr(result.content[0], "text", "").endswith(
            f": {expected_code}"
        )
    ):
        raise CanaryFailure("unexpected_tool_result")


def _first_identifier(
    payload: dict[str, Any], *, field: str
) -> str:
    items = payload.get("items")
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        raise CanaryFailure("precondition_missing")
    value = items[0].get(field)
    if not isinstance(value, str) or not value:
        raise CanaryFailure("precondition_missing")
    return value


async def _primary_checks(
    primary: ClientSession,
    *,
    latencies: list[float],
    read_status: dict[str, str],
) -> tuple[tuple[str, ...], str, str, str]:
    listed = await primary.list_tools()
    registered_tools = tuple(tool.name for tool in listed.tools)
    if registered_tools != ALL_REMOTE_TOOLS:
        raise CanaryFailure("tool_contract_mismatch")

    feed = await _read_call(
        primary,
        "get_my_feed",
        {"collection": "latest", "limit": 20, "offset": 0},
        latencies=latencies,
    )
    read_status["get_my_feed"] = "ok"
    article_id = _first_identifier(feed, field="article_id")
    await _read_call(
        primary,
        "get_item",
        {"article_id": article_id},
        latencies=latencies,
    )
    read_status["get_item"] = "ok"

    subscriptions = await _read_call(
        primary,
        "list_subscriptions",
        {"include_disabled": True},
        latencies=latencies,
    )
    read_status["list_subscriptions"] = "ok"
    subscription_id = _first_identifier(subscriptions, field="subscription_id")
    await _read_call(primary, "source_health", {}, latencies=latencies)
    read_status["source_health"] = "ok"

    jobs = await _read_call(
        primary, "list_jobs", {"limit": 20}, latencies=latencies
    )
    read_status["list_jobs"] = "ok"
    job_id = _first_identifier(jobs, field="id")
    await _read_call(
        primary, "get_job", {"job_id": job_id}, latencies=latencies
    )
    read_status["get_job"] = "ok"
    await _read_call(
        primary,
        "get_source_setup_guide",
        {"source_type": "rss", "locale": "zh-CN"},
        latencies=latencies,
    )
    read_status["get_source_setup_guide"] = "ok"
    await _read_call(
        primary, "list_available_sources", {}, latencies=latencies
    )
    read_status["list_available_sources"] = "ok"
    await _read_call(
        primary,
        "diagnose_source",
        {"subscription_id": subscription_id},
        latencies=latencies,
    )
    read_status["diagnose_source"] = "ok"
    await _read_call(
        primary, "diagnose_job", {"job_id": job_id}, latencies=latencies
    )
    read_status["diagnose_job"] = "ok"
    # The contract intentionally has eleven read tools while the server keeps a
    # burst of ten; wait for one token rather than weakening the production limit.
    await anyio.sleep(1.05)
    await _read_call(
        primary,
        "query_operation_logs",
        {"lookback_hours": 24, "limit": 10},
        latencies=latencies,
    )
    read_status["query_operation_logs"] = "ok"
    return registered_tools, article_id, subscription_id, job_id


async def _secondary_checks(
    secondary: ClientSession,
    *,
    article_id: str,
    subscription_id: str,
    job_id: str,
) -> None:
    await _expect_tool_error(
        secondary, "get_item", {"article_id": article_id}, "not_found"
    )
    await _expect_tool_error(
        secondary, "get_job", {"job_id": job_id}, "not_found"
    )
    await _expect_tool_error(
        secondary,
        "diagnose_source",
        {"subscription_id": subscription_id},
        "not_found",
    )
    await _expect_tool_error(
        secondary,
        "prepare_create_subscription",
        {
            "source": {
                "mode": "private",
                "type": "rss",
                "display_name": "Read-only canary guard",
                "config": {"url": "https://example.com/read-only-canary.xml"},
            }
        },
        "subscription_writes_disabled",
    )


async def verify_canary(
    *,
    url: str,
    primary_token: str,
    secondary_token: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    url = _validated_url(url)
    if not primary_token or not secondary_token:
        raise CanaryFailure("missing_environment")
    latencies: list[float] = []
    read_status = {name: "pending" for name in SAFE_READ_TOOLS}
    primary_failure: CanaryFailure | None = None
    primary_result: tuple[tuple[str, ...], str, str, str] | None = None
    async with _session(
        url=url, token=primary_token, transport=transport
    ) as primary:
        try:
            primary_result = await _primary_checks(
                primary, latencies=latencies, read_status=read_status
            )
        except CanaryFailure as exc:
            primary_failure = exc
    if primary_failure is not None:
        raise primary_failure
    if primary_result is None:
        raise CanaryFailure("internal_error")
    registered_tools, article_id, subscription_id, job_id = primary_result

    secondary_failure: CanaryFailure | None = None
    async with _session(
        url=url, token=secondary_token, transport=transport
    ) as secondary:
        try:
            await _secondary_checks(
                secondary,
                article_id=article_id,
                subscription_id=subscription_id,
                job_id=job_id,
            )
        except CanaryFailure as exc:
            secondary_failure = exc
    if secondary_failure is not None:
        raise secondary_failure

    return {
        "ok": True,
        "mode": "verify",
        "tool_count": len(registered_tools),
        "registered_tools": list(registered_tools),
        "read_tools": read_status,
        "isolation_checks": 3,
        "write_guard": "subscription_writes_disabled",
        "latency_ms": {
            "sample_count": len(latencies),
            "p95": round(_p95(latencies), 3),
            "maximum": round(max(latencies, default=0.0), 3),
        },
    }


async def expect_unauthorized(
    *,
    url: str,
    token: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    url = _validated_url(url)
    if not token:
        raise CanaryFailure("missing_environment")
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": LATEST_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {
                "name": "inteliscope-read-canary",
                "version": "1",
            },
        },
    }
    async with httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(30.0, connect=10.0),
    ) as client:
        response = await client.post(
            url,
            json=payload,
            headers={
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {token}",
            },
        )
    if response.status_code == 401:
        return {"ok": True, "mode": "expect-unauthorized", "status": 401}
    if 200 <= response.status_code < 300:
        raise CanaryFailure("token_still_authorized")
    raise CanaryFailure("unexpected_http_status")


def _required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise CanaryFailure("missing_environment")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify read-only Inteliscope Remote MCP production behavior."
    )
    parser.add_argument("mode", choices=("verify", "expect-unauthorized"))
    args = parser.parse_args(argv)
    try:
        url = _required_environment("INTELISCOPE_MCP_URL")
        primary_token = _required_environment("INTELISCOPE_MCP_TOKEN")
        operation = (
            partial(
                verify_canary,
                url=url,
                primary_token=primary_token,
                secondary_token=_required_environment(
                    "INTELISCOPE_MCP_SECONDARY_TOKEN"
                ),
            )
            if args.mode == "verify"
            else partial(
                expect_unauthorized,
                url=url,
                token=primary_token,
            )
        )
        result = anyio.run(operation)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except CanaryFailure as exc:
        print(
            json.dumps(
                {"ok": False, "error": exc.code},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    except Exception:
        print(
            json.dumps(
                {"ok": False, "error": "internal_error"},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
