#!/usr/bin/env python3
"""Run the bounded local Remote MCP latency and RSS acceptance check."""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import resource
import sys
import tempfile
import time
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import anyio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from src.api.server import create_app


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def _max_rss_mib() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform != "darwin":
        value *= 1024.0
    return value / (1024.0 * 1024.0)


async def run_benchmark(calls: int) -> dict[str, float | int | bool]:
    if calls != 100:
        raise ValueError("the acceptance check requires exactly 100 calls")
    os.environ.update(
        {
            "HORIZON_AUTH_USER": "benchmark-owner",
            "HORIZON_AUTH_PASSWORD": "benchmark-only-password",
            "HORIZON_AUTH_SESSION_SECRET": "benchmark-only-session-secret",
            "HORIZON_REMOTE_MCP_ENABLED": "true",
            "HORIZON_REMOTE_MCP_PUBLIC_URL": "http://127.0.0.1:8080/mcp",
        }
    )

    with tempfile.TemporaryDirectory(prefix="inteliscope-mcp-benchmark-") as directory:
        root = Path(directory)
        static_dir = root / "static"
        static_dir.mkdir()
        (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
        app = create_app(data_dir=root / "data", static_dir=static_dir)
        store = app.state.service_store
        workspace = store.get_default_workspace()
        credentials: list[tuple[str, str]] = []
        for index in range(10):
            username = f"benchmark-{index}"
            password = "benchmark-only-password"
            user = store.create_user(
                workspace_id=workspace["id"],
                username=username,
                password=password,
                role="viewer",
            )
            _connection, token = store.create_agent_delegation(
                workspace_id=workspace["id"],
                user_id=user["id"],
                name=f"Benchmark {index}",
            )
            credentials.append((username, token))

        transport = httpx.ASGITransport(app=app)
        rest_samples: list[float] = []
        mcp_samples: list[float] = []
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://127.0.0.1:8080",
            ) as rest_client:
                login = await rest_client.post(
                    "/api/auth/login",
                    json={
                        "username": credentials[0][0],
                        "password": "benchmark-only-password",
                    },
                )
                login.raise_for_status()
                for _ in range(5):
                    (await rest_client.get("/api/me/source-health")).raise_for_status()
                for _ in range(calls):
                    started = time.perf_counter()
                    response = await rest_client.get("/api/me/source-health")
                    response.raise_for_status()
                    rest_samples.append((time.perf_counter() - started) * 1000.0)

            rss_before = _max_rss_mib()
            for _username, token in credentials:
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url="http://127.0.0.1:8080",
                    headers={"Authorization": f"Bearer {token}"},
                ) as mcp_client:
                    async with streamable_http_client(
                        "http://127.0.0.1:8080/mcp",
                        http_client=mcp_client,
                        terminate_on_close=False,
                    ) as (read_stream, write_stream, _get_session_id):
                        async with ClientSession(read_stream, write_stream) as session:
                            await session.initialize()
                            for _ in range(calls // len(credentials)):
                                started = time.perf_counter()
                                result = await session.call_tool("source_health", {})
                                mcp_samples.append(
                                    (time.perf_counter() - started) * 1000.0
                                )
                                if result.isError:
                                    raise RuntimeError("Remote MCP benchmark call failed")
            rss_delta = max(0.0, _max_rss_mib() - rss_before)

    rest_p95 = _p95(rest_samples)
    mcp_p95 = _p95(mcp_samples)
    return {
        "calls": calls,
        "rest_p95_ms": round(rest_p95, 3),
        "mcp_p95_ms": round(mcp_p95, 3),
        "mcp_overhead_ms": round(mcp_p95 - rest_p95, 3),
        "rss_delta_mib": round(rss_delta, 3),
        "latency_pass": mcp_p95 <= rest_p95 + 150.0,
        "rss_pass": rss_delta < 80.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calls", type=int, default=100)
    args = parser.parse_args()
    logging.disable(logging.INFO)
    result = anyio.run(run_benchmark, args.calls)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if not result["latency_pass"] or not result["rss_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
