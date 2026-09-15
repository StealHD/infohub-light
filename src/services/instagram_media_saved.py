"""Read only explicitly stored, tenant-scoped remote image evidence."""

from .actorops.adapters.instagram.media_inventory import image_url


def saved_media_urls(store, state):
    import json

    record = state["record"]
    stored = json.loads(record["item_json"])
    values = []
    for key in ("remote_media_urls", "media_urls"):
        if isinstance(stored.get(key), list):
            values.extend(stored[key][:100])
    values.extend([stored.get("remote_image_url"), stored.get("image_url")])
    # Asset rows retain the remote address privately, even after Feed sanitization.
    assets = store.connect().execute(
        """SELECT remote_url FROM media_assets WHERE workspace_id=? AND user_id=?
           AND source_id=? AND article_id=? AND asset_kind='content_image'
           ORDER BY created_at, id LIMIT 100""",
        (record["workspace_id"], record["user_id"], record["source_id"], record["article_id"]),
    ).fetchall()
    values.extend(row[0] for row in assets)
    return list(dict.fromkeys(url for value in values if (url := image_url(value))))
