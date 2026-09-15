"""Attach media only to the exact validated post, never by array position."""

import logging
from dataclasses import replace

from .....models import SourceType
from ....apify_actor_manifest import parse_actor_manifest
from .._manifest import validate_and_map
from .media_inventory import extract_media, image_url


logger = logging.getLogger(__name__)


def enrich_instagram_media(batch, rows, target, manifest, window):
    indexed = {}
    nested = parse_actor_manifest(manifest.manifest_json).row_extraction
    for row in rows[:100]:
        try:
            checked = validate_and_map((row,), target, manifest, window,
                                       platform="instagram", source_type=SourceType.INSTAGRAM)
        except Exception:
            continue
        if len(checked.items) != 1:
            continue
        item_id = checked.items[0].id
        media_row = row.get("item", {}) if nested and nested.mode == "nested_array" else row
        media = extract_media(media_row)
        logger.info("Instagram media inventory: available=%d total=%d bounded=%d",
                    len(media.images), media.total_count, int(media.bounded))
        if item_id in indexed and indexed[item_id] != media:
            indexed[item_id] = None
        else:
            indexed[item_id] = media
    items = []
    for item in batch.items:
        media = indexed.get(item.id)
        if media is None or not media.images:
            logger.info("Instagram post media unavailable", extra={
                "error_code": "instagram_media_ambiguous" if item.id in indexed and media is None
                else "instagram_media_missing"})
            if media is None and item.id in indexed:
                metadata = {key: value for key, value in item.metadata.items()
                            if key not in {"image_url", "media_urls", "remote_image_url", "remote_media_urls"}}
                items.append(item.model_copy(update={"metadata": metadata}))
            elif media is not None and media.video_count:
                items.append(item.model_copy(update={"metadata": {**item.metadata, **media.metadata()}}))
            else:
                metadata = dict(item.metadata)
                if not image_url(metadata.get("image_url")):
                    metadata.pop("image_url", None)
                items.append(item.model_copy(update={"metadata": metadata}))
            continue
        items.append(item.model_copy(update={"metadata": {**item.metadata, **media.metadata()}}))
    return replace(batch, items=tuple(items))
