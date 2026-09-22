"""Bounded, semantic media containers shared across Instagram Actor vendors."""

from collections.abc import Mapping
from dataclasses import dataclass

MAX_MEDIA = 100
CHILD_KEYS = ('childPosts', 'children', 'carouselMedia', 'sidecarChildren', 'carousel_media')
ARRAY_KEYS = ('images', 'imageUrls', 'image_urls')


@dataclass(frozen=True)
class MediaNodes:
    nodes: list
    children: bool = False
    malformed: bool = False
    bounded: bool = False


def declared_gallery(row):
    values = (row.get(key) for key in ('type', '__typename', 'mediaType', 'media_type',
                                     'media_type_raw', 'product_type', 'typeName'))
    return any(str(value).lower() in {'8', 'carousel', 'carousel_container', 'sidecar',
                                      'graphsidecar', 'gallery'} for value in values)


def declared_count(row):
    for key in ('carousel_media_count', 'childPostsCount'):
        value = row.get(key)
        if type(value) is int and 1 < value <= MAX_MEDIA:
            return value
    return None


def media_nodes(row):
    malformed = unknown_media_container(row)
    for key in (*CHILD_KEYS, 'edge_sidecar_to_children', 'mediaDownloadUrl', *ARRAY_KEYS):
        raw = row.get(key)
        if raw is None:
            continue
        if key == 'edge_sidecar_to_children':
            raw = raw.get('edges') if isinstance(raw, Mapping) else raw
            if isinstance(raw, list):
                bounded = len(raw) > MAX_MEDIA
                nodes = [node.get('node') if isinstance(node, Mapping) else None
                         for node in raw[:MAX_MEDIA]]
                if nodes:
                    return MediaNodes(nodes, True, malformed, bounded)
        if isinstance(raw, list):
            if raw:
                return MediaNodes(raw[:MAX_MEDIA], key not in ARRAY_KEYS,
                                  malformed, len(raw) > MAX_MEDIA)
        elif key == 'mediaDownloadUrl' and isinstance(raw, str):
            # This is one media file, not an array of carousel slides.
            continue
        else:
            malformed = True
    return MediaNodes([row], False, malformed)


def variants(row):
    """Variants describe ONE media item, regardless of differing URL paths."""
    for key in ('image_versions2', 'image_versions', 'displayResources', 'allImageVariants'):
        raw = row.get(key)
        if isinstance(raw, Mapping):
            raw = raw.get('candidates') or raw.get('items')
        if isinstance(raw, list) and raw:
            return raw[:MAX_MEDIA]
    return []


def unknown_media_container(row):
    """Recognize structural gaps without scraping unknown URL values."""
    known = {*CHILD_KEYS, *ARRAY_KEYS, 'edge_sidecar_to_children', 'mediaDownloadUrl',
             'image_versions2', 'image_versions', 'displayResources', 'allImageVariants',
             'video_versions'}
    return any(
        key not in known and isinstance(value, (Mapping, list)) and bool(value)
        and any(hint in str(key).lower() for hint in ('media', 'carousel', 'sidecar', 'gallery', 'slides', 'attachments'))
        for key, value in row.items()
    )
