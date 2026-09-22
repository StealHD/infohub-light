"""Bounded photo and video-cover inventory for one validated Instagram post."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from ....apify_actor_manifest import normalize_http_url
from ...capability_evidence import MediaCapabilityEvidence
from .media_shapes import MAX_MEDIA, declared_count, declared_gallery, media_nodes, variants


IMAGE_KEYS = ("displayUrl", "displayURL", "display_url", "imageUrl", "image_url",
              "thumbnailUrl", "thumbnail_url", "image")


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
    evidence: MediaCapabilityEvidence = MediaCapabilityEvidence()
    gallery: bool = False

    def metadata(self):
        urls = [image.url for image in self.images[:6]]
        result = {"media_urls": urls, "image_url": next(iter(urls), ""),
                  "media_image_count": self.total_count,
                  "media_photo_count": self.photo_count,
                  "media_video_count": self.video_count}
        if self.gallery or self.photo_count + self.video_count > 1:
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
            or row.get("media_type", row.get("media_type_raw")) == 2
            or str(row.get("type", row.get("mediaType", row.get("media_type", row.get("__typename", ""))))).lower()
            in {"video", "reel", "reels", "graphvideo"})


def _best_image(row, *, child=False):
    candidates = variants(row)
    ranked = []
    if isinstance(candidates, list):
        for candidate in candidates[:MAX_MEDIA]:
            if isinstance(candidate, str):
                candidate = {"url": candidate}
            if not isinstance(candidate, Mapping):
                continue
            url = image_url(candidate.get("url", candidate.get("src")))
            width, height = _dimension(candidate.get("width", candidate.get("config_width"))), _dimension(candidate.get("height", candidate.get("config_height")))
            if url:
                ranked.append(((width or 0) * (height or 0), url, width, height))
    if ranked:
        _, url, width, height = max(ranked, key=lambda value: value[0])
        return PostImage(url, "video_cover" if _video(row) else "photo", width, height)
    direct = () if _video(row) else ("mediaDownloadUrl", *(("url", "src") if child else ()))
    keys = (*IMAGE_KEYS, *direct)
    for key in keys:
        url = image_url(row.get(key))
        if url:
            return PostImage(url, "video_cover" if _video(row) else "photo",
                             _dimension(row.get("width")), _dimension(row.get("height")))
    return None


def extract_media(row):
    selection = media_nodes(row)
    nodes = selection.nodes
    child_container = not (len(nodes) == 1 and nodes[0] is row)
    images, seen = [], {}
    photos = videos = missing = 0
    for node in nodes[:MAX_MEDIA]:
        if isinstance(node, str):
            node = {"imageUrl": node}
        if not isinstance(node, Mapping):
            missing += 1
            continue
        if not selection.children and _video(row):
            node = {**node, "isVideo": True}
        image = _best_image(node, child=child_container)
        if image is None:
            videos += int(_video(node))
            missing += int(not _video(node))
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
    if _video(row) and not selection.children and images:
        # Some video Actors expose cover renditions in `images` rather than
        # displayResources. A video post still has only one cover.
        images = [max(images, key=lambda image: (image.width or 0) * (image.height or 0))]
        photos, videos = 0, 1
    gallery = declared_gallery(row) or bool(declared_count(row))
    status, reason = 'unknown', 'no_gallery_sample'
    count = declared_count(row)
    if selection.malformed or (child_container and missing):
        status, reason = 'mapping_gap', 'unmapped_media_items'
    elif gallery and not child_container:
        status, reason = 'upstream_incomplete', 'gallery_cover_only'
    elif count and len(nodes) < count:
        status, reason = 'upstream_incomplete', 'gallery_items_missing'
    elif len(images) > 1:
        status, reason = 'observed_multi', 'multiple_media_observed'
    elif gallery and len(nodes) < 2:
        status, reason = 'upstream_incomplete', 'gallery_items_missing'
    if not images and child_container:
        cover = _best_image(row)
        if cover:
            images.append(cover)
            photos += int(cover.kind == 'photo')
            videos += int(cover.kind == 'video_cover')
    total = len(images)
    evidence = MediaCapabilityEvidence(status, reason, 1, total)
    return PostMedia(tuple(images), photos, videos, total, selection.bounded,
                     evidence, gallery)
