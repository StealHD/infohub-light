"""Smoke the static InfoHub UI through the service boundary.

This script is stdlib-only and intentionally checks the UI contract without
starting a browser: it logs in, fetches the static entry page and assets, then
verifies the page uses service API paths instead of local JSON fallbacks.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from scripts.service_api_smoke import ApiClient


FORBIDDEN_LOCAL_JSON_REFERENCES = (
    "./radar-data.json",
    "./history-data.json",
    "./article-graph.json",
    "radar-data.json?ts=",
    "history-data.json?ts=",
    "article-graph.json?ts=",
)


def build_report(checks: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [check["name"] for check in checks if not check.get("ok")]
    return {
        "ok": not failed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "failed": failed,
        "checks": checks,
    }


def _check(name: str, checks: list[dict[str, Any]], func: Callable[[], Any]) -> Any:
    try:
        data = func()
    except Exception as exc:  # pragma: no cover - manual smoke failure path
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


def _normalize_asset_path(raw: str) -> str | None:
    if not raw or raw.startswith(("http://", "https://", "data:")):
        return None
    path = raw.split("?", 1)[0]
    if path.startswith("./"):
        path = path[1:]
    if not path.startswith("/"):
        path = "/" + path
    return path


def _asset_paths(index_html: str) -> list[str]:
    paths: list[str] = []
    for match in re.finditer(r"""(?:src|href)=["']([^"']+)["']""", index_html):
        path = _normalize_asset_path(match.group(1))
        if path and (path.endswith(".js") or path.endswith(".css")) and path not in paths:
            paths.append(path)
    return paths


def _default_fetch_text(base_url: str) -> Callable[[str], str]:
    root = base_url.rstrip("/")

    def fetch_text(path: str) -> str:
        url = root + path
        request = urllib.request.Request(url, headers={"Accept": "text/html,*/*"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")

    return fetch_text


def _assert_static_entrypoints(index_html: str, fetch_text: Callable[[str], str]) -> dict[str, Any]:
    required_markers = [
        'data-view="subscriptions"',
        'data-view="config"',
        'id="readerPanel"',
    ]
    missing_markers = [marker for marker in required_markers if marker not in index_html]
    if missing_markers:
        raise RuntimeError("missing UI markers: " + ", ".join(missing_markers))
    if 'id="authLoginForm"' not in index_html and 'id="configForms"' not in index_html:
        raise RuntimeError('missing UI markers: login gate or config form container')

    assets = _asset_paths(index_html)
    required_assets = {"/auth.js", "/app.js", "/subscriptions.js"}
    missing_assets = sorted(required_assets.difference(assets))
    if missing_assets:
        raise RuntimeError("missing static assets: " + ", ".join(missing_assets))

    asset_texts = {path: fetch_text(path) for path in assets}
    return {"asset_count": len(assets), "asset_texts": asset_texts}


def _assert_no_local_json_references(index_html: str, asset_texts: dict[str, str]) -> None:
    combined = "\n".join([index_html] + list(asset_texts.values()))
    found = [needle for needle in FORBIDDEN_LOCAL_JSON_REFERENCES if needle in combined]
    if found:
        raise RuntimeError("local JSON references found: " + ", ".join(found))


def _find_smoke_source(sources: list[dict[str, Any]]) -> dict[str, Any] | None:
    for source in sources:
        config = source.get("config") or {}
        if (
            source.get("type") == "rss"
            and source.get("scope") == "private"
            and config.get("url") == "https://example.com/infohub-ui-smoke.xml"
        ):
            return source
    return None


def _run_mutating_checks(client: Any, checks: list[dict[str, Any]], feed: dict[str, Any]) -> None:
    sources_data = _check("catalog_sources", checks, lambda: client.data("GET", "/api/catalog/sources")) or {}
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
                    "display_name": "Smoke - Static UI Private RSS",
                    "description": "Local UI smoke source; not fetched by this script.",
                    "default_channel": "AI",
                    "default_topics": ["Smoke"],
                    "config": {
                        "name": "Smoke - Static UI Private RSS",
                        "url": "https://example.com/infohub-ui-smoke.xml",
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
    if not first_item:
        checks.append({"name": "item_state_skipped", "ok": True, "reason": "no feed items"})
        return

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
            {"feedback_type": "not_relevant", "metadata": {"surface": "service_ui_smoke"}},
        ),
    )


def run_ui_smoke(
    client: Any,
    *,
    base_url: str,
    username: str,
    password: str,
    fetch_text: Callable[[str], str] | None = None,
    mutating: bool = False,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    fetch_text = fetch_text or _default_fetch_text(base_url)

    login = _check("login", checks, lambda: client.data("POST", "/api/auth/login", {"username": username, "password": password}))
    if not login:
        return build_report(checks)

    _check("auth_status", checks, lambda: client.data("GET", "/api/auth/status"))
    index_html = _check("fetch_index", checks, lambda: fetch_text("/"))
    if not index_html:
        return build_report(checks)

    entrypoint_data = _check(
        "static_entrypoints",
        checks,
        lambda: _assert_static_entrypoints(index_html, fetch_text),
    ) or {}
    asset_texts = entrypoint_data.get("asset_texts") if isinstance(entrypoint_data, dict) else {}
    _check(
        "local_json_references",
        checks,
        lambda: _assert_no_local_json_references(index_html, asset_texts or {}),
    )
    feed = _check("feed_latest", checks, lambda: client.data("GET", "/api/feed/latest")) or {}

    if mutating:
        _run_mutating_checks(client, checks, feed if isinstance(feed, dict) else {})

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
        path = Path("logs") / f"service-ui-smoke-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    print(f"wrote {path}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke the static InfoHub UI through service APIs.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--username", default=os.getenv("HORIZON_AUTH_USER", "admin"))
    parser.add_argument("--password", default=os.getenv("HORIZON_AUTH_PASSWORD"))
    parser.add_argument("--json-output", default=None)
    parser.add_argument("--mutating", action="store_true")
    args = parser.parse_args()

    if not args.password:
        print("--password or HORIZON_AUTH_PASSWORD is required", file=sys.stderr)
        return 2

    report = run_ui_smoke(
        ApiClient(args.base_url),
        base_url=args.base_url,
        username=args.username,
        password=args.password,
        mutating=args.mutating,
    )
    write_report(report, args.json_output)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
