"""Bounded photo and video-cover inventory for one validated Instagram post."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from ....apify_actor_manifest import normalize_http_url


MAX_MEDIA = 100
IMAGE_KEYS = ("displayUrl", "displayURL", "display_url", "imageUrl", "image_url",
              "thumbnailUrl", "thumbnail_url")
CHILD_KEYS = ("childPosts", "children", "carouselMedia", "sidecarChildren")


@dataclass(frozen=True)
class PostImage:
    url: str
    kind: str
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class PostMedia:
    images: tuple[PostImage, ...]
    photo_count: int
    video_count: int
    total_count: int
    bounded: bool = False

    def metadata(self):
        urls = [image.url for image in self.images[:6]]
        result = {"media_urls": urls, "image_url": next(iter(urls), ""),
                  "media_image_count": self.total_count,
                  "media_photo_count": self.photo_count,
                  "media_video_count": self.video_count}
        if self.photo_count + self.video_count > 1:
            result["upstream_content_format"] = "gallery"
        elif self.video_count:
            result["upstream_content_format"] = "video"
        elif self.photo_count:
            result["upstream_content_format"] = "image"
        return result


def image_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        url = normalize_http_url(value)
        parsed = urlsplit(url)
        if parsed.username or parsed.password or parsed.path.lower().endswith(
            (".mp4", ".mov", ".webm", ".m3u8", ".mp3")
        ):
            return None
        return url
    except ValueError:
        return None


def _dimension(value):
    return value if type(value) is int and 0 < value <= 100000 else None


def _video(row):
    return (row.get("isVideo") is True or row.get("is_video") is True
            or row.get("media_type") == 2
            or str(row.get("type", row.get("__typename", ""))).lower()
            in {"video", "reel", "reels", "graphvideo"})


def _best_image(row):
    versions = row.get("image_versions2")
    candidates = versions.get("candidates") if isinstance(versions, Mapping) else None
    ranked = []
    if isinstance(candidates, list):
        for candidate in candidates[:MAX_MEDIA]:
            if not isinstance(candidate, Mapping):
                continue
            url = image_url(candidate.get("url"))
            width, height = _dimension(candidate.get("width")), _dimension(candidate.get("height"))
            if url:
                ranked.append(((width or 0) * (height or 0), url, width, height))
    if ranked:
        _, url, width, height = max(ranked, key=lambda value: value[0])
        return PostImage(url, "video_cover" if _video(row) else "photo", width, height)
    for key in IMAGE_KEYS:
        url = image_url(row.get(key))
        if url:
            return PostImage(url, "video_cover" if _video(row) else "photo",
                             _dimension(row.get("width")), _dimension(row.get("height")))
    return None


def extract_media(row):
    children = next((row[key] for key in CHILD_KEYS
                     if isinstance(row.get(key), list) and row[key]), None)
    array = next((row[key] for key in ("images", "imageUrls", "image_urls")
                  if isinstance(row.get(key), list) and row[key]), None)
    nodes = children if children is not None else array if array is not None else [row]
    images, seen = [], {}
    photos = videos = 0
    for node in nodes[:MAX_MEDIA]:
        if isinstance(node, str):
            node = {"imageUrl": node}
        if not isinstance(node, Mapping):
            continue
        if children is None and _video(row):
            node = {**node, "isVideo": True}
        image = _best_image(node)
        if image is None:
            videos += int(_video(node))
            continue
        parsed = urlsplit(image.url)
        host = (parsed.hostname or "").lower()
        instagram_cdn = any(host == suffix or host.endswith("." + suffix)
                            for suffix in ("cdninstagram.com", "fbcdn.net"))
        identity = urlunsplit((parsed.scheme, parsed.netloc, parsed.path,
                              "" if instagram_cdn else parsed.query, ""))
        if identity in seen:
            index = seen[identity]
            previous = images[index]
            if (image.width or 0) * (image.height or 0) > (previous.width or 0) * (previous.height or 0):
                images[index] = image
            continue
        seen[identity] = len(images)
        videos += int(image.kind == "video_cover")
        photos += int(image.kind == "photo")
        images.append(image)
    total = len(images)
    return PostMedia(tuple(images), photos, videos, total, len(nodes) > MAX_MEDIA)
