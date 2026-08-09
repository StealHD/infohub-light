"""Smoke real catalog sources through the service API.

This script is intentionally stdlib-only so it can run from a fresh local or
Docker checkout without extra client dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any


TERMINAL_STATUSES = {"succeeded", "failed", "partial", "cancelled"}


def default_smoke_sources(*, include_flaky: bool = False) -> list[dict[str, Any]]:
    """Return deterministic real-source smoke definitions."""

    sources: list[dict[str, Any]] = [
        {
            "key": "rss_github_blog",
            "source_type": "rss",
            "display_name": "Smoke - GitHub Blog RSS",
            "description": "Real-source smoke baseline for RSS.",
            "default_channel": "Technology",
            "default_topics": ["GitHub", "Engineering"],
            "config": {"name": "GitHub Blog", "url": "https://github.blog/feed/"},
            "required": True,
            "fetch": True,
        },
        {
            "key": "hackernews_top",
            "source_type": "hackernews",
            "display_name": "Smoke - Hacker News Top",
            "description": "Real-source smoke baseline for Hacker News.",
            "default_channel": "Technology",
            "default_topics": ["Hacker News", "Industry"],
            "config": {"fetch_top_stories": 30, "min_score": 0},
            "required": True,
            "fetch": True,
        },
        {
            "key": "github_openai_codex",
            "source_type": "github_release",
            "display_name": "Smoke - OpenAI Codex Releases",
            "description": "Real-source smoke baseline for GitHub releases.",
            "default_channel": "AI",
            "default_topics": ["Codex", "Developer Tools"],
            "config": {"owner": "openai", "repo": "codex"},
            "required": True,
            "fetch": False,
        },
        {
            "key": "telegram_durov",
            "source_type": "telegram_channel",
            "display_name": "Smoke - Telegram Durov",
            "description": "Real-source smoke baseline for a public Telegram channel.",
            "default_channel": "Social",
            "default_topics": ["Telegram", "Public Channels"],
            "config": {"channel": "durov"},
            "required": True,
            "fetch": False,
        },
    ]

    if include_flaky:
        sources.append(
            {
                "key": "reddit_localllama",
                "source_type": "reddit_subreddit",
                "display_name": "Smoke - Reddit LocalLLaMA",
                "description": "Optional degraded smoke for Reddit public JSON/RSS access.",
                "default_channel": "AI",
                "default_topics": ["Local LLM"],
                "config": {"subreddit": "LocalLLaMA", "sort": "hot", "fetch_limit": 25, "min_score": 0},
                "required": False,
                "expected_degraded": True,
                "fetch": False,
            }
        )
        if os.getenv("APIFY_TOKEN"):
            sources.append(
                {
                    "key": "apify_x_openai",
                    "source_type": "apify_social",
                    "display_name": "Smoke - Apify X OpenAI",
                    "description": "Optional Apify-backed smoke when APIFY_TOKEN exists.",
                    "default_channel": "AI",
                    "default_topics": ["OpenAI", "Social"],
                    "config": {
                        "platform": "x",
                        "kind": "profile",
                        "target": "openai",
                        "fetch_limit": 20,
                    },
                    "secret_env": "APIFY_TOKEN",
                    "required": False,
                    "fetch": False,
                }
            )

    return sources


def _source_failed(result: dict[str, Any]) -> bool:
    for key in ("source_test_status", "source_fetch_status"):
        status = result.get(key)
        if status and status != "succeeded":
            return True
    return False


def _feed_snapshot_ok(feed_latest: dict[str, Any] | None) -> bool:
    if not feed_latest:
        return False
    return (
        feed_latest.get("scope") == "user"
        and bool(feed_latest.get("snapshot_id"))
        and bool(feed_latest.get("items") or [])
    )


def build_report(
    source_results: list[dict[str, Any]],
    *,
    feed_latest: dict[str, Any] | None = None,
    source_health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a stable JSON report and pass/fail summary."""

    required_failed = [
        item["key"]
        for item in source_results
        if item.get("required", False) and _source_failed(item)
    ]
    optional_degraded = [
        item["key"]
        for item in source_results
        if not item.get("required", False)
        and (item.get("expected_degraded") or _source_failed(item))
        and _source_failed(item)
    ]
    feed_ok = _feed_snapshot_ok(feed_latest)
    return {
        "ok": not required_failed and feed_ok,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "required_failed": required_failed,
        "optional_degraded": optional_degraded,
        "feed_latest_ok": feed_ok,
        "sources": source_results,
        "feed_latest": feed_latest or {},
        "source_health": source_health or {},
    }


@dataclass
class ApiClient:
    base_url: str

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        cookie_jar = CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"ok": False, "error": {"code": f"http_{exc.code}", "message": raw}}
            if payload.get("ok") is False:
                return payload
            raise
        if not isinstance(payload, dict):
            raise RuntimeError(f"unexpected API payload for {method} {path}: {payload!r}")
        return payload

    def data(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        payload = self.request(method, path, body)
        if not payload.get("ok"):
            error = payload.get("error") or {}
            code = error.get("code") or "api_error"
            message = error.get("message") or payload
            raise RuntimeError(f"{method} {path} failed: {code}: {message}")
        return payload.get("data")


def _source_payload(spec: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "type": spec["source_type"],
        "display_name": spec["display_name"],
        "description": spec.get("description") or "",
        "default_channel": spec.get("default_channel"),
        "default_topics": spec.get("default_topics") or [],
        "config": spec.get("config") or {},
        "enabled": True,
    }
    if spec.get("secret_env"):
        payload["secret_env"] = spec["secret_env"]
    return payload


def _find_existing_source(sources: list[dict[str, Any]], spec: dict[str, Any]) -> dict[str, Any] | None:
    expected_type = spec["source_type"]
    expected_config = spec.get("config") or {}
    for source in sources:
        if source.get("type") != expected_type:
            continue
        config = source.get("config") or {}
        if expected_type == "rss" and config.get("url") == expected_config.get("url"):
            return source
        if expected_type == "hackernews":
            return source
        if expected_type == "github_release" and (
            str(config.get("owner", "")).lower(),
            str(config.get("repo", "")).lower(),
        ) == (
            str(expected_config.get("owner", "")).lower(),
            str(expected_config.get("repo", "")).lower(),
        ):
            return source
        if expected_type == "telegram_channel" and str(config.get("channel", "")).lower() == str(
            expected_config.get("channel", "")
        ).lower():
            return source
        if expected_type == "reddit_subreddit" and str(config.get("subreddit", "")).lower() == str(
            expected_config.get("subreddit", "")
        ).lower():
            return source
        if expected_type == "apify_social" and (
            config.get("platform"),
            config.get("kind"),
            str(config.get("target", "")).lower(),
        ) == (
            expected_config.get("platform"),
            expected_config.get("kind"),
            str(expected_config.get("target", "")).lower(),
        ):
            return source
    return None


def upsert_source(client: ApiClient, spec: dict[str, Any]) -> dict[str, Any]:
    sources = client.data("GET", "/api/catalog/sources")["sources"]
    existing = _find_existing_source(sources, spec)
    payload = _source_payload(spec)
    if existing:
        source = client.data("PATCH", f"/api/catalog/sources/{existing['id']}", payload)
    else:
        source = client.data("POST", "/api/catalog/sources", payload)
    client.data("POST", f"/api/catalog/sources/{source['id']}/subscribe")
    return source


def queue_job(client: ApiClient, endpoint: str, source_id: str, *, hours: int) -> dict[str, Any]:
    payload: dict[str, Any] = {"source_id": source_id, "payload": {}}
    if endpoint.endswith("source-fetch"):
        payload["payload"]["hours"] = hours
    return client.data("POST", endpoint, payload)


def poll_job(client: ApiClient, job_id: str, *, timeout_seconds: int = 180) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_job: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        job = client.data("GET", f"/api/jobs/{urllib.parse.quote(job_id)}")
        last_job = job
        if job.get("status") in TERMINAL_STATUSES:
            return job
        time.sleep(1)
    return last_job or {"id": job_id, "status": "timeout"}


def run_worker_once() -> None:
    command = [sys.executable, "-m", "src.services.worker", "--once"]
    subprocess.run(command, check=True)


def run_smoke(
    *,
    base_url: str,
    username: str,
    password: str,
    hours: int,
    run_worker: bool,
    include_flaky: bool,
) -> dict[str, Any]:
    client = ApiClient(base_url)
    client.data("POST", "/api/auth/login", {"username": username, "password": password})

    results: list[dict[str, Any]] = []
    for spec in default_smoke_sources(include_flaky=include_flaky):
        result = {
            "key": spec["key"],
            "source_type": spec["source_type"],
            "required": spec.get("required", False),
            "expected_degraded": spec.get("expected_degraded", False),
        }
        try:
            source = upsert_source(client, spec)
            result["source_id"] = source["id"]
            result["source_key"] = source.get("source_key")
            test_job = queue_job(client, "/api/jobs/source-test", source["id"], hours=hours)
            result["source_test_job_id"] = test_job["id"]
            if run_worker:
                run_worker_once()
                test_job = poll_job(client, test_job["id"])
            result["source_test_status"] = test_job.get("status")
            if test_job.get("error_code"):
                result["source_test_error"] = {
                    "code": test_job.get("error_code"),
                    "message": test_job.get("error_message"),
                }
            if spec.get("fetch"):
                fetch_job = queue_job(client, "/api/jobs/source-fetch", source["id"], hours=hours)
                result["source_fetch_job_id"] = fetch_job["id"]
                if run_worker:
                    run_worker_once()
                    fetch_job = poll_job(client, fetch_job["id"])
                result["source_fetch_status"] = fetch_job.get("status")
                result["source_fetch_result"] = fetch_job.get("result_json") or {}
                if fetch_job.get("error_code"):
                    result["source_fetch_error"] = {
                        "code": fetch_job.get("error_code"),
                        "message": fetch_job.get("error_message"),
                    }
        except Exception as exc:  # pragma: no cover - exercised by manual smoke
            result["source_test_status"] = "failed"
            result["source_test_error"] = {"code": type(exc).__name__, "message": str(exc)}
        results.append(result)

    feed_latest = client.data("GET", "/api/feed/latest")
    source_health = client.data("GET", "/api/me/source-health")
    return build_report(results, feed_latest=feed_latest, source_health=source_health)


def write_report(report: dict[str, Any], output: str | None) -> Path | None:
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if output == "-":
        print(text)
        return None
    if output:
        path = Path(output)
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = Path("logs") / f"service-real-source-smoke-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    print(f"wrote {path}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run real-source smoke through the InfoHub service API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--hours", type=int, default=168)
    parser.add_argument("--run-worker", action="store_true")
    parser.add_argument("--include-flaky", action="store_true")
    parser.add_argument("--json-output", default=None)
    args = parser.parse_args()

    username = os.getenv("HORIZON_AUTH_USER", "admin")
    password = os.getenv("HORIZON_AUTH_PASSWORD")
    if not password:
        print("HORIZON_AUTH_PASSWORD is required for service smoke login", file=sys.stderr)
        return 2

    report = run_smoke(
        base_url=args.base_url,
        username=username,
        password=password,
        hours=args.hours,
        run_worker=args.run_worker,
        include_flaky=args.include_flaky,
    )
    write_report(report, args.json_output)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
