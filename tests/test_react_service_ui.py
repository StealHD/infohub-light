from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient

from src.api.server import create_app, resolve_service_static_dir


def test_react_service_ui_serves_deep_links_and_cache_headers(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    static_dir = tmp_path / "service-static"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text("<!doctype html><main>React UI</main>", encoding="utf-8")
    (static_dir / "favicon.svg").write_text("<svg>icon</svg>", encoding="utf-8")
    (static_dir / "site.webmanifest").write_text('{"name":"Inteliscope"}', encoding="utf-8")
    (assets_dir / "app-hash.js").write_text(
        f"const payload = '{'ui' * 2048}'",
        encoding="utf-8",
    )
    client = TestClient(create_app(data_dir=data_dir, static_dir=static_dir))

    deep_link = client.get("/subscriptions")
    assert deep_link.status_code == 200
    assert "React UI" in deep_link.text
    assert deep_link.headers["cache-control"] == "no-cache"

    agents_deep_link = client.get("/agents")
    assert agents_deep_link.status_code == 200
    assert "React UI" in agents_deep_link.text
    assert agents_deep_link.headers["cache-control"] == "no-cache"

    manual_deep_link = client.get("/manual")
    assert manual_deep_link.status_code == 200
    assert "React UI" in manual_deep_link.text
    assert manual_deep_link.headers["cache-control"] == "no-cache"

    unicode_deep_link = client.get("/设置/订阅")
    assert unicode_deep_link.status_code == 200
    assert "React UI" in unicode_deep_link.text
    assert unicode_deep_link.headers["cache-control"] == "no-cache"

    asset = client.get("/assets/app-hash.js")
    assert asset.status_code == 200
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert asset.headers["content-type"].startswith("text/javascript")
    assert asset.headers["content-encoding"] == "gzip"
    assert "Accept-Encoding" in asset.headers["vary"]

    favicon = client.get("/favicon.svg")
    assert favicon.status_code == 200
    assert favicon.headers["content-type"].startswith("image/svg+xml")
    assert favicon.text == "<svg>icon</svg>"

    favicon_head = client.head("/favicon.svg")
    assert favicon_head.status_code == 200
    assert favicon_head.headers["content-type"].startswith("image/svg+xml")
    assert favicon_head.headers["content-length"] == str(len(favicon.content))
    assert favicon_head.content == b""

    manifest = client.get("/site.webmanifest")
    assert manifest.status_code == 200
    assert manifest.headers["content-type"].startswith("application/manifest+json")

    legacy_favicon = client.get("/favicon.ico")
    assert legacy_favicon.status_code == 204
    assert legacy_favicon.content == b""
    assert legacy_favicon.headers["cache-control"] == "public, max-age=86400"

    missing_asset = client.get("/missing.js")
    assert missing_asset.status_code == 404
    assert "React UI" not in missing_asset.text

    nested_missing_asset = client.get("/nested/missing.css")
    assert nested_missing_asset.status_code == 404
    assert "React UI" not in nested_missing_asset.text

    missing_asset_head = client.head("/nested/missing.css")
    assert missing_asset_head.status_code == 404

    missing_hidden_file = client.get("/nested/.missing")
    assert missing_hidden_file.status_code == 404
    assert "React UI" not in missing_hidden_file.text

    missing_api = client.get("/api/not-real")
    assert missing_api.status_code == 404
    assert missing_api.json()["error"]["code"] == "not_found"

    api_root = client.get("/api")
    assert api_root.status_code == 404
    assert api_root.headers["content-type"].startswith("application/json")
    assert api_root.json()["error"]["code"] == "not_found"

    api_head = client.head("/api/not-real")
    assert api_head.status_code == 404
    assert api_head.headers["content-type"].startswith("application/json")

    api_root_head = client.head("/api")
    assert api_root_head.status_code == 404
    assert api_root_head.headers["content-type"].startswith("application/json")

    mcp_root_head = client.head("/mcp")
    assert mcp_root_head.status_code == 404
    assert mcp_root_head.headers["content-type"].startswith("application/json")

    mcp_head = client.head("/mcp/not-real")
    assert mcp_head.status_code == 404
    assert mcp_head.headers["content-type"].startswith("application/json")

    for encoded_missing_asset in (
        "/missing%252Ejs",
        "/nested/missing%252Ecss",
    ):
        encoded_missing_get = client.get(encoded_missing_asset)
        assert encoded_missing_get.status_code == 404
        assert "React UI" not in encoded_missing_get.text
        encoded_missing_head = client.head(encoded_missing_asset)
        assert encoded_missing_head.status_code == 404
        assert "React UI" not in encoded_missing_head.text

    for encoded_reserved_path in (
        "/api%252Fnot-real",
        "/mcp%252Fnot-real",
    ):
        encoded_reserved_get = client.get(encoded_reserved_path)
        assert encoded_reserved_get.status_code == 404
        assert "React UI" not in encoded_reserved_get.text
        encoded_reserved_head = client.head(encoded_reserved_path)
        assert encoded_reserved_head.status_code == 404
        assert "React UI" not in encoded_reserved_head.text

    for traversal_path in (
        "/%252e%252e/private",
        "/%25252e%25252e/private",
    ):
        traversal = client.get(traversal_path)
        assert traversal.status_code == 404
        assert "React UI" not in traversal.text
    deeply_encoded_parent = "%2e%2e"
    for _ in range(12):
        deeply_encoded_parent = quote(deeply_encoded_parent, safe="")
    deep_traversal = client.get(f"/{deeply_encoded_parent}/private")
    assert deep_traversal.status_code == 404
    assert "React UI" not in deep_traversal.text

    overencoded_api = "api/not-real"
    for _ in range(20):
        overencoded_api = quote(overencoded_api, safe="")
    overencoded = client.get(f"/{overencoded_api}")
    assert overencoded.status_code == 404
    assert "React UI" not in overencoded.text

    oversized_path = client.get(f"/{'a' * 8193}")
    assert oversized_path.status_code == 404
    assert "React UI" not in oversized_path.text


def test_service_transport_gzips_large_json_and_keeps_small_responses_plain(
    tmp_path: Path,
) -> None:
    static_dir = tmp_path / "service-static"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (static_dir / "large.json").write_text(
        f'{{"payload":"{"x" * 4096}"}}',
        encoding="utf-8",
    )
    client = TestClient(create_app(data_dir=tmp_path / "data", static_dir=static_dir))

    large_json = client.get("/large.json", headers={"Accept-Encoding": "gzip"})
    assert large_json.status_code == 200
    assert large_json.headers["content-type"].startswith("application/json")
    assert large_json.headers["content-encoding"] == "gzip"
    assert "Accept-Encoding" in large_json.headers["vary"]

    refused_gzip = client.get(
        "/large.json",
        headers={"Accept-Encoding": "br, gzip;q=0"},
    )
    assert refused_gzip.status_code == 200
    assert "content-encoding" not in refused_gzip.headers
    assert "Accept-Encoding" in refused_gzip.headers["vary"]

    wildcard_gzip = client.get(
        "/large.json",
        headers={"Accept-Encoding": "*;q=0.5"},
    )
    assert wildcard_gzip.status_code == 200
    assert wildcard_gzip.headers["content-encoding"] == "gzip"

    favicon = client.get("/favicon.ico", headers={"Accept-Encoding": "gzip"})
    assert favicon.status_code == 204
    assert "content-encoding" not in favicon.headers


def test_service_ui_uses_only_react_directory(tmp_path: Path) -> None:
    react_dir = tmp_path / "react"
    react_dir.mkdir()
    (react_dir / "index.html").write_text("react", encoding="utf-8")

    assert resolve_service_static_dir(react_dir=react_dir) == react_dir


def test_missing_react_build_keeps_api_live_without_ui_fallback(tmp_path: Path) -> None:
    react_dir = tmp_path / "missing-react"
    client = TestClient(create_app(data_dir=tmp_path / "data", static_dir=react_dir))

    assert resolve_service_static_dir(react_dir=react_dir) == react_dir
    assert client.get("/").status_code == 404
    assert client.get("/api/health/live").status_code == 200
