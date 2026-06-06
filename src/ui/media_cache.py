"""Same-origin media cache for social images used by the static UI."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from urllib.parse import urlparse

import httpx


LOGGER = logging.getLogger(__name__)
MAX_MEDIA_BYTES = 12 * 1024 * 1024
ALLOWED_MEDIA_HOST_SUFFIXES = (
    "cdninstagram.com",
    "fbcdn.net",
)
MEDIA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
}


def _host_allowed(host: str) -> bool:
    normalized = host.lower().strip(".")
    return any(
        normalized == suffix or normalized.endswith(f".{suffix}")
        for suffix in ALLOWED_MEDIA_HOST_SUFFIXES
    )


def _is_cacheable_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    return _host_allowed(parsed.hostname)


def _media_digest(url: str) -> str:
    parsed = urlparse(url)
    cache_key = f"{parsed.scheme}://{parsed.hostname}{parsed.path}"
    return hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:32]


def _extension_from_content_type(content_type: str) -> str:
    mime = content_type.split(";", 1)[0].strip().lower()
    return {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(mime, "")


def _extension_from_url(url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"} else ""


def _existing_media_path(media_dir: Path, digest: str) -> Path | None:
    for candidate in media_dir.glob(f"{digest}.*"):
        if candidate.is_file():
            return candidate
    return None


def cache_media_url(url: str, site_dir: Path) -> str | None:
    """Download an allowlisted remote image into data/site/media.

    Returns a relative same-origin URL like ``media/<hash>.jpg``. Non-allowlisted
    URLs are ignored so regular RSS media can still be rendered directly.
    """
    clean_url = str(url or "").strip()
    if not _is_cacheable_url(clean_url):
        return None

    media_dir = site_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    digest = _media_digest(clean_url)
    existing = _existing_media_path(media_dir, digest)
    if existing:
        return f"media/{existing.name}"

    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(20.0, connect=8.0),
            headers=MEDIA_HEADERS,
        ) as client:
            response = client.get(clean_url)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if not content_type.lower().startswith("image/"):
                LOGGER.warning("media cache skipped non-image response: %s", clean_url)
                return None

            extension = _extension_from_content_type(content_type) or _extension_from_url(clean_url)
            if not extension:
                extension = ".jpg"
            target = media_dir / f"{digest}{extension}"
            tmp = target.with_suffix(f"{target.suffix}.tmp")

            total = 0
            with tmp.open("wb") as fh:
                for chunk in response.iter_bytes():
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_MEDIA_BYTES:
                        raise ValueError("media response exceeds size limit")
                    fh.write(chunk)
            tmp.replace(target)
            return f"media/{target.name}"
    except Exception as exc:  # pragma: no cover - exact network failures vary.
        LOGGER.warning("media cache failed for %s: %s", clean_url, exc)
        return None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if isinstance(item, str) and str(item).strip()]


def _cache_item_media(item: dict[str, object], site_dir: Path) -> None:
    image_url = str(item.get("image_url") or "").strip()
    media_urls = _string_list(item.get("media_urls"))
    if image_url and image_url not in media_urls:
        media_urls.insert(0, image_url)

    remote_urls = [url for url in media_urls if _is_cacheable_url(url)]
    if not remote_urls:
        return

    if not item.get("remote_image_url"):
        item["remote_image_url"] = image_url
    item["remote_media_urls"] = remote_urls

    replacements: dict[str, str] = {}
    for remote_url in remote_urls:
        cached_url = cache_media_url(remote_url, site_dir)
        if cached_url:
            replacements[remote_url] = cached_url

    if not replacements:
        item["media_cache_error"] = "远端图片可访问但浏览器跨域策略阻止直接展示，且本地缓存失败。"
        return

    if image_url in replacements:
        item["image_url"] = replacements[image_url]
    elif remote_urls[0] in replacements:
        item["image_url"] = replacements[remote_urls[0]]

    item["media_urls"] = [replacements.get(url, url) for url in media_urls]
    item.pop("media_cache_error", None)


def cache_payload_media(payload: dict[str, object], site_dir: Path) -> None:
    """Cache image URLs inside every item list in a site payload in place."""
    for key in ("items", "featured_items", "daily_push_items"):
        values = payload.get(key)
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, dict):
                _cache_item_media(item, site_dir)
