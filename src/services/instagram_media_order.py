"""Preserve Instagram gallery order in details without trusting external URLs."""


def ordered_instagram_assets(rows, item):
    presentation = item.get("presentation") or {}
    source = presentation.get("source") or {}
    if item.get("source_type") != "instagram" and source.get("platform") != "instagram":
        return rows
    images = (presentation.get("media") or {}).get("images") or []
    urls = [image.get("url") for image in images if isinstance(image, dict)]
    if not urls:
        urls = item.get("media_urls") or []
    positions = {url: index for index, url in enumerate(urls[:6]) if isinstance(url, str)}
    return sorted(rows, key=lambda row: positions.get(f"/api/media/{row['id']}", 6))
