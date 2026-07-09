"""Smoke the core InfoHub service API without external source access."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any, Callable


def build_report(checks: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [check["name"] for check in checks if not check.get("ok")]
    return {
        "ok": not failed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "failed": failed,
        "checks": checks,
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
                payload = {
                    "ok": False,
                    "error": {"code": f"http_{exc.code}", "message": raw},
                }
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


def _check(name: str, checks: list[dict[str, Any]], func: Callable[[], Any]) -> Any:
    try:
        data = func()
    except Exception as exc:  # pragma: no cover - exercised by manual smoke failures
        checks.append(
            {
                "name": name,
                "ok": False,
                "error": {"code": type(exc).__name__, "message": str(exc)},
            }
        )
        return None
    checks.append({"name": name, "ok": True})
    return data


def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _find_smoke_source(sources: list[dict[str, Any]]) -> dict[str, Any] | None:
    for source in sources:
        config = source.get("config") or {}
        if (
            source.get("type") == "rss"
            and source.get("scope") == "private"
            and config.get("url") == "https://example.com/infohub-service-smoke.xml"
        ):
            return source
    return None


def run_smoke_checks(
    client: Any,
    *,
    username: str,
    password: str,
    mutating: bool = False,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    _check("login", checks, lambda: client.data("POST", "/api/auth/login", {"username": username, "password": password}))
    _check("auth_status", checks, lambda: client.data("GET", "/api/auth/status"))
    _check("config", checks, lambda: client.data("GET", "/api/config"))
    _check("dashboard", checks, lambda: client.data("GET", "/api/dashboard/summary"))
    sources_data = _check("catalog_sources", checks, lambda: client.data("GET", "/api/catalog/sources")) or {}
    feed = _check("feed_latest", checks, lambda: client.data("GET", "/api/feed/latest")) or {}
    _check("jobs", checks, lambda: client.data("GET", "/api/jobs"))

    if mutating:
        sources = sources_data.get("sources") if isinstance(sources_data, dict) else []
        source = _find_smoke_source(sources or [])
        if source is None:
            source = _check(
                "create_private_source",
                checks,
                lambda: client.data(
                    "POST",
                    "/api/catalog/sources",
                    {
                        "scope": "private",
                        "type": "rss",
                        "display_name": "Smoke - Service API Private RSS",
                        "description": "Local API smoke source; not fetched by this script.",
                        "default_channel": "AI",
                        "default_topics": ["Smoke"],
                        "config": {
                            "name": "Smoke - Service API Private RSS",
                            "url": "https://example.com/infohub-service-smoke.xml",
                        },
                    },
                ),
            )
        else:
            checks.append({"name": "create_private_source", "ok": True, "reused": True})

        if source and source.get("id"):
            source_id = str(source["id"])
            _check(
                "subscribe_private_source",
                checks,
                lambda: client.data("POST", f"/api/catalog/sources/{_quote(source_id)}/subscribe"),
            )
            _check(
                "source_test_job",
                checks,
                lambda: client.data("POST", "/api/jobs/source-test", {"source_id": source_id, "payload": {}}),
            )

        items = feed.get("items") if isinstance(feed, dict) else []
        first_item = next((item for item in items or [] if isinstance(item, dict) and item.get("id")), None)
        if first_item:
            article_id = str(first_item["id"])
            _check(
                "item_state",
                checks,
                lambda: client.data("GET", f"/api/me/item-state?article_ids={_quote(article_id)}"),
            )
            _check(
                "item_state_update",
                checks,
                lambda: client.data(
                    "PATCH",
                    f"/api/me/items/{_quote(article_id)}/state",
                    {"is_read": True},
                ),
            )
            _check(
                "item_feedback",
                checks,
                lambda: client.data(
                    "POST",
                    f"/api/me/items/{_quote(article_id)}/feedback",
                    {"feedback_type": "not_relevant", "metadata": {"surface": "service_api_smoke"}},
                ),
            )
        else:
            checks.append({"name": "item_state_skipped", "ok": True, "reason": "no feed items"})

    return build_report(checks)


def write_report(report: dict[str, Any], output: str | None) -> Path | None:
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if output == "-":
        print(text)
        return None
    if output:
        path = Path(output)
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = Path("logs") / f"service-api-smoke-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    print(f"wrote {path}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke the core InfoHub service API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--username", default=os.getenv("HORIZON_AUTH_USER", "admin"))
    parser.add_argument("--password", default=os.getenv("HORIZON_AUTH_PASSWORD"))
    parser.add_argument("--json-output", default=None)
    parser.add_argument("--mutating", action="store_true")
    args = parser.parse_args()

    if not args.password:
        print("--password or HORIZON_AUTH_PASSWORD is required", file=sys.stderr)
        return 2

    report = run_smoke_checks(
        ApiClient(args.base_url),
        username=args.username,
        password=args.password,
        mutating=args.mutating,
    )
    write_report(report, args.json_output)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
