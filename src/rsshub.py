"""Pure RSSHub service and managed-route contracts.

RSSHub is a workspace service, not a catalog source type. Catalog RSS rows may
carry one controlled route identity; the runtime resolves that identity against
the workspace-configured service base URL.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit


DEFAULT_RSSHUB_BASE_URL = "http://rsshub:1200"
RSSHUB_PROVIDER = "rsshub"
BILIBILI_SITE = "bilibili"
BILIBILI_USER_VIDEO_ROUTE = "user_video"

_CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x1f\x7f]")
_BILIBILI_UID_RE = re.compile(r"^[0-9]{1,20}$")


class RSSHubConfigError(ValueError):
    """Raised when a service URL or controlled route is invalid."""


@dataclass(frozen=True, slots=True)
class RSSHubRoute:
    site: str
    route_key: str
    required_params: tuple[str, ...]

    def path(self, params: dict[str, str]) -> str:
        if (self.site, self.route_key) == (
            BILIBILI_SITE,
            BILIBILI_USER_VIDEO_ROUTE,
        ):
            # Keep the existing local feeds' `/1` behavior, which disables
            # embedded video HTML in RSSHub's Bilibili route.
            return f"/bilibili/user/video/{params['uid']}/1"
        raise RSSHubConfigError("unsupported RSSHub route")

    def public_page_url(self, params: dict[str, str]) -> str:
        if (self.site, self.route_key) == (
            BILIBILI_SITE,
            BILIBILI_USER_VIDEO_ROUTE,
        ):
            return f"https://space.bilibili.com/{params['uid']}"
        raise RSSHubConfigError("unsupported RSSHub route")


_ROUTES = {
    (BILIBILI_SITE, BILIBILI_USER_VIDEO_ROUTE): RSSHubRoute(
        site=BILIBILI_SITE,
        route_key=BILIBILI_USER_VIDEO_ROUTE,
        required_params=("uid",),
    )
}


def normalize_rsshub_base_url(value: Any) -> str:
    """Validate and canonicalize one active RSSHub HTTP(S) service root."""

    raw = str(value or "").strip()
    if not raw:
        raise RSSHubConfigError("RSSHub Base URL is required")
    if len(raw) > 2048 or "\\" in raw or _CONTROL_CHARACTER_RE.search(raw):
        raise RSSHubConfigError("RSSHub Base URL is invalid")
    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise RSSHubConfigError("RSSHub Base URL is invalid") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise RSSHubConfigError(
            "RSSHub Base URL must be an HTTP(S) origin without credentials, path, query, or fragment"
        )
    host = hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{host}:{port}" if port is not None else host
    return urlunsplit((parsed.scheme.lower(), netloc, "", "", ""))


def _normalize_bilibili_uid(value: Any) -> str:
    if isinstance(value, bool):
        raise RSSHubConfigError("params.uid must be a positive Bilibili UID")
    uid = str(value or "").strip()
    if not _BILIBILI_UID_RE.fullmatch(uid):
        raise RSSHubConfigError("params.uid must be a positive Bilibili UID")
    numeric = int(uid)
    if numeric <= 0 or numeric > 9_223_372_036_854_775_807:
        raise RSSHubConfigError("params.uid must be a positive Bilibili UID")
    return str(numeric)


def normalize_rsshub_route(
    *,
    site: Any,
    route_key: Any,
    params: Any,
) -> dict[str, Any]:
    """Normalize one allowlisted, public, credential-free RSSHub route."""

    normalized_site = str(site or "").strip().lower()
    normalized_route = str(route_key or "").strip().lower()
    route = _ROUTES.get((normalized_site, normalized_route))
    if route is None:
        raise RSSHubConfigError("unsupported RSSHub route")
    if not isinstance(params, dict) or set(params) != set(route.required_params):
        raise RSSHubConfigError(
            "params must contain exactly: " + ", ".join(route.required_params)
        )
    normalized_params = {"uid": _normalize_bilibili_uid(params["uid"])}
    return {
        "site": route.site,
        "route_key": route.route_key,
        "params": normalized_params,
    }


def is_managed_rsshub_config(config: Any) -> bool:
    return isinstance(config, dict) and config.get("provider") == RSSHUB_PROVIDER


def normalize_managed_rsshub_config(config: dict[str, Any]) -> dict[str, Any]:
    """Normalize a catalog RSS config backed by the workspace RSSHub service."""

    route = normalize_rsshub_route(
        site=config.get("site"),
        route_key=config.get("route_key"),
        params=config.get("params"),
    )
    definition = _ROUTES[(route["site"], route["route_key"])]
    return {
        **config,
        "provider": RSSHUB_PROVIDER,
        **route,
        # This public page is safe for UI previews. Runtime Config validation
        # replaces it with the private/third-party RSSHub feed URL.
        "url": definition.public_page_url(route["params"]),
    }


def rsshub_feed_url(base_url: Any, config: dict[str, Any]) -> str:
    """Resolve a normalized managed catalog config to its runtime feed URL."""

    base = normalize_rsshub_base_url(base_url)
    normalized = normalize_managed_rsshub_config(config)
    route = _ROUTES[(normalized["site"], normalized["route_key"])]
    return f"{base}{route.path(normalized['params'])}"


def rsshub_public_target(config: dict[str, Any]) -> dict[str, Any]:
    """Return the MCP-safe semantic target without the configured service URL."""

    normalized = normalize_managed_rsshub_config(config)
    return {
        "site": normalized["site"],
        "route_key": normalized["route_key"],
        "params": dict(normalized["params"]),
    }


def rsshub_source_key(config: dict[str, Any]) -> str:
    normalized = normalize_managed_rsshub_config(config)
    uid = normalized["params"]["uid"]
    return (
        f"rss:rsshub:{normalized['site']}:{normalized['route_key']}:{uid}"
    )
