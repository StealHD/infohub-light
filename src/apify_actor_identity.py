"""Stable, value-free identities shared by ActorOps storage and services."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def source_config_target(
    config: Mapping[str, object], *, platform: str | None = None
) -> str:
    """Return the raw acquisition target across social and native source shapes."""

    value = config.get("target")
    if not str(value or "").strip() and str(platform or "").casefold() == "youtube":
        value = config.get("url")
    return str(value or "").strip()


def source_target_fingerprint(
    workspace_id: str,
    route_id: str,
    target: str,
    *,
    platform: str | None = None,
) -> str:
    """Digest a canonical source target without persisting its value."""

    identity = canonical_source_target_identity(target, platform=platform)
    return hashlib.sha256(
        "\x1f".join((str(workspace_id), str(route_id), identity)).encode(
            "utf-8"
        )
    ).hexdigest()


def canonical_source_target_identity(
    target: str,
    *,
    platform: str | None,
) -> str:
    """Normalize only target parts whose case is platform-insensitive."""

    value = str(target or "").strip()
    normalized_platform = str(platform or "").strip().casefold()
    if normalized_platform in {"x", "instagram"}:
        if "://" in value:
            parsed = urlsplit(value)
            host = str(parsed.hostname or "").rstrip(".").casefold()
            allowed_hosts = (
                {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}
                if normalized_platform == "x"
                else {"instagram.com", "www.instagram.com"}
            )
            path_parts = [part for part in parsed.path.split("/") if part]
            if host in allowed_hosts and path_parts:
                value = path_parts[0]
        return value.lstrip("@").rstrip("/").casefold()
    if normalized_platform == "":
        return value.casefold()
    if normalized_platform != "youtube" or "://" not in value:
        return value
    parsed = urlsplit(value)
    host = str(parsed.hostname or "").rstrip(".").casefold()
    try:
        port = parsed.port
    except ValueError:
        return value
    authority = host
    if port is not None and not (
        parsed.scheme.casefold() == "https" and port == 443
    ):
        authority = f"{host}:{port}"
    query = urlencode(
        sorted(parse_qsl(parsed.query, keep_blank_values=True)),
        doseq=True,
    )
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            authority,
            parsed.path or "/",
            query,
            "",
        )
    )


__all__ = [
    "canonical_source_target_identity",
    "source_config_target",
    "source_target_fingerprint",
]
