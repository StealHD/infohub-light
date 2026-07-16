from pathlib import Path

from fastapi.testclient import TestClient

from src.api.server import create_app, resolve_service_static_dir


def test_react_service_ui_serves_deep_links_and_cache_headers(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    static_dir = tmp_path / "service-static"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text("<!doctype html><main>React UI</main>", encoding="utf-8")
    (assets_dir / "app-hash.js").write_text("console.log('ui')", encoding="utf-8")
    client = TestClient(create_app(data_dir=data_dir, static_dir=static_dir))

    deep_link = client.get("/subscriptions")
    assert deep_link.status_code == 200
    assert "React UI" in deep_link.text
    assert deep_link.headers["cache-control"] == "no-cache"

    asset = client.get("/assets/app-hash.js")
    assert asset.status_code == 200
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"

    missing_api = client.get("/api/not-real")
    assert missing_api.status_code == 404
    assert missing_api.json()["error"]["code"] == "not_found"


def test_service_ui_variant_prefers_react_and_keeps_explicit_legacy_fallback(tmp_path: Path) -> None:
    react_dir = tmp_path / "react"
    legacy_dir = tmp_path / "legacy"
    react_dir.mkdir()
    legacy_dir.mkdir()
    (react_dir / "index.html").write_text("react", encoding="utf-8")
    (legacy_dir / "index.html").write_text("legacy", encoding="utf-8")

    assert resolve_service_static_dir("react", react_dir=react_dir, legacy_dir=legacy_dir) == react_dir
    assert resolve_service_static_dir("legacy", react_dir=react_dir, legacy_dir=legacy_dir) == legacy_dir


def test_service_ui_variant_falls_back_when_react_build_is_missing(tmp_path: Path) -> None:
    react_dir = tmp_path / "missing-react"
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    (legacy_dir / "index.html").write_text("legacy", encoding="utf-8")

    assert resolve_service_static_dir("react", react_dir=react_dir, legacy_dir=legacy_dir) == legacy_dir
