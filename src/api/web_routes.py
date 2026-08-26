"""React workspace routes."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def _normalize_frontend_path(frontend_path: str) -> str | None:
    if len(frontend_path) > 8192:
        return None
    decoded_path = frontend_path
    for _ in range(16):
        next_path = unquote(decoded_path)
        if next_path == decoded_path:
            break
        decoded_path = next_path
    else:
        if unquote(decoded_path) != decoded_path:
            return None
    if "\x00" in decoded_path or "\\" in decoded_path or decoded_path.startswith("/"):
        return None
    if any(part in {".", ".."} for part in decoded_path.split("/")):
        return None
    return decoded_path


def register_web_routes(app: FastAPI, static_path: Path) -> None:
    """Serve the React workspace."""

    if not static_path.exists():
        return
    assets_path = static_path / "assets"
    if assets_path.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_path)), name="service-assets")
    index_path = static_path / "index.html"
    if not assets_path.exists() or not index_path.exists():
        app.mount("/", StaticFiles(directory=str(static_path), html=True), name="static")
        return

    static_root = static_path.resolve()

    @app.api_route(
        "/{frontend_path:path}",
        methods=["GET", "HEAD"],
        include_in_schema=False,
    )
    async def service_frontend(frontend_path: str) -> Response:
        normalized_path = _normalize_frontend_path(frontend_path)
        if normalized_path is None:
            return Response(status_code=404)
        if normalized_path.split("/", 1)[0] in {"api", "mcp"}:
            return Response(status_code=404)

        try:
            static_file = (static_root / normalized_path).resolve()
            static_file.relative_to(static_root)
        except (OSError, RuntimeError, ValueError):
            return Response(status_code=404)
        if static_file.is_file():
            return FileResponse(static_file)
        if "." in normalized_path.rstrip("/").rsplit("/", 1)[-1]:
            return Response(status_code=404)
        return FileResponse(
            index_path,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )
