"""Media-only stable-index projection; historical snapshots stay immutable."""

import copy


def repaired_projection(original, metadata):
    result = copy.deepcopy(original)
    presentation = result.setdefault("presentation", {})
    old = presentation.get("media") or {}
    existing = old.get("images") or []
    by_url = {image.get("url"): image for image in existing if isinstance(image, dict)}
    images, seen = [], set()
    for url in metadata.get("media_urls", []):
        if url.startswith("/api/media/") and url not in seen and len(images) < 6:
            images.append(by_url.get(url) or {"url": url, "alt": result.get("title") or "内容图片"})
            seen.add(url)
    for url, image in by_url.items():
        if isinstance(url, str) and url.startswith("/api/media/") and url not in seen and len(images) < 6:
            images.append(image)
            seen.add(url)
    total = max(int(old.get("total_image_count") or 0),
                int(metadata.get("media_image_count") or 0), len(images))
    if images or total:
        presentation["media"] = {**old, "images": images, "count": len(images),
                                  "total_image_count": total, "truncated": total > len(images)}
        result["media_urls"] = [image["url"] for image in images]
        result["image_url"] = result["media_urls"][0] if images else ""
        result["total_image_count"] = total
    if metadata.get("upstream_content_format"):
        presentation.setdefault("content", {}).update(
            format=metadata["upstream_content_format"], format_origin="upstream")
    return result
