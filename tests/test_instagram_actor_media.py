from datetime import datetime, timezone
from dataclasses import replace
import json

import pytest

from src.services.actorops.adapters.instagram.media_inventory import extract_media
from src.services.actorops.adapters.instagram.profile_items import InstagramProfileItemsAdapter
from src.services.actorops.ports import ActorManifest, FetchWindow
from src.services.media_cache import MediaCacheService
from src.services.content_presentation import _presentation_media, resolve_content_format
from src.services.instagram_media_order import ordered_instagram_assets
from src.services.apify_actor_manifest import actor_manifest_hash
from src.services.actorops.adapter_rows import prepare_adapter_rows
from test_actorops_v2_presentation_mapping import _repository


def row(**values):
    return {"id": "one", "url": "https://www.instagram.com/p/one/", "author": "openai",
            "createdAt": "2026-08-20T00:00:00Z", "text": "caption", **values}


def validated(candidate, rows):
    adapter = InstagramProfileItemsAdapter()
    return adapter.validate_output(rows, adapter.normalize_target({"target": "openai"}),
        ActorManifest(candidate.actor_id, candidate.build_id, candidate.build_number,
                      candidate.manifest_json, candidate.manifest_hash),
        FetchWindow(100, datetime(2026, 8, 19, tzinfo=timezone.utc), None))


@pytest.mark.parametrize("alias", ["displayUrl", "displayURL", "display_url", "imageUrl",
                                  "image_url", "thumbnailUrl", "thumbnail_url"])
def test_known_photo_alias(alias):
    result = extract_media({alias: "https://cdn.example/a.jpg"})
    assert result.total_count == result.photo_count == 1
    assert result.metadata()["upstream_content_format"] == "image"


def test_carousel_order_variants_duplicate_parent_and_limit():
    children = [{"displayUrl": f"https://cdninstagram.com/{i}.jpg"} for i in range(8)]
    children[0] = {"image_versions2": {"candidates": [
        {"url": "https://cdn.example/low.jpg", "width": 10, "height": 10},
        {"url": "https://cdninstagram.com/0.jpg", "width": 100, "height": 100}]}}
    children.insert(1, {"displayUrl": "https://cdninstagram.com/0.jpg?signature=2"})
    media = extract_media({"displayUrl": "https://cdn.example/parent.jpg", "childPosts": children})
    assert media.total_count == 8
    assert media.images[0].width == 100
    assert media.metadata()["media_urls"] == [f"https://cdninstagram.com/{i}.jpg" for i in range(6)]


def test_video_cover_mixed_gallery_and_no_recursive_avatar_collection():
    media = extract_media({"type": "Video", "displayUrl": "https://cdn.example/cover.jpg",
                           "profilePicUrl": "https://cdn.example/avatar.jpg"})
    assert media.video_count == 1 and media.photo_count == 0
    assert media.metadata()["upstream_content_format"] == "video"
    mixed = extract_media({"children": [{"type": "Video", "displayUrl": media.images[0].url},
                                       {"imageUrl": "https://cdn.example/photo.jpg"}]})
    assert mixed.video_count == mixed.photo_count == 1
    assert mixed.metadata()["upstream_content_format"] == "gallery"
    assert not extract_media({"comments": [{"imageUrl": "https://cdn.example/x.jpg"}],
                              "imageUrl": "https://cdn.example/movie.mp4"}).images


def test_unvisited_tail_is_not_counted_as_verified_photos():
    media = extract_media({"images": ["https://cdn.example/a.jpg"] * 101})
    assert media.bounded and media.total_count == 1


def test_legacy_manifest_without_media_mapping_caches_partial_and_preserves_total(tmp_path):
    store, _, candidate = _repository(tmp_path)
    batch = validated(candidate, [row(images=[f"https://cdn.example/{i}.png" for i in range(8)])])
    assert len(batch.items) == 1
    item = batch.items[0]
    user = store.create_user(workspace_id=store.get_default_workspace()["id"],
                             username="media-test", password="test-only-password")
    def fetch(url):
        if url.endswith("1.png"):
            raise ValueError("download failed")
        return b"\x89PNG\r\n\x1a\n" + url.encode(), "image/png"
    MediaCacheService(store, data_dir=store.data_dir, fetch_image=fetch).cache_items(
        workspace_id=store.get_default_workspace()["id"], user_id=user["id"], items=[item])
    media = _presentation_media(title=item.title, media_urls=item.metadata["media_urls"],
                                total_image_count=item.metadata["media_image_count"])
    assert media["count"] == 5 and media["total_image_count"] == 8 and media["truncated"]
    assert all(image["url"].startswith("/api/media/") for image in media["images"])
    assert resolve_content_format(source_type="instagram", metadata=item.metadata)[0] == "gallery"
    store.close()


def test_duplicate_identity_with_conflicting_media_never_attaches_by_position(tmp_path):
    store, _, candidate = _repository(tmp_path)
    batch = validated(candidate, [row(displayUrl="https://cdn.example/a.jpg"),
                                  row(displayUrl="https://cdn.example/b.jpg")])
    assert batch.items
    assert all(not item.metadata.get("media_urls") for item in batch.items)
    store.close()


def test_expired_post_media_does_not_shift_onto_next_post(tmp_path):
    store, _, candidate = _repository(tmp_path)
    batch = validated(candidate, [row(id="old", createdAt="2020-01-01T00:00:00Z",
                                     displayUrl="https://cdn.example/old.jpg"),
                                  row(displayUrl="https://cdn.example/new.jpg")])
    assert len(batch.items) == 1
    assert batch.items[0].metadata["media_urls"] == ["https://cdn.example/new.jpg"]
    store.close()


def test_other_platform_detail_order_unchanged():
    rows = [{"id": "b"}, {"id": "a"}]
    assert ordered_instagram_assets(rows, {"source_type": "x", "media_urls": ["/api/media/a"]}) is rows


def test_nested_envelope_does_not_collect_parent_or_recommended_photos(tmp_path):
    store, _, candidate = _repository(tmp_path)
    data = json.loads(candidate.manifest_json)
    data["row_extraction"] = {"mode": "nested_array", "pointers": ["/posts"]}
    for field in data["output"].values():
        field["pointers"] = ["/item" + pointer for pointer in field["pointers"]]
    raw = json.dumps(data)
    candidate = replace(candidate, manifest_json=raw, manifest_hash=actor_manifest_hash(raw))
    adapter = InstagramProfileItemsAdapter()
    manifest = ActorManifest(candidate.actor_id, candidate.build_id, candidate.build_number, raw, candidate.manifest_hash)
    prepared = prepare_adapter_rows(adapter, [{"imageUrl": "https://cdn.example/profile.png", "posts": [
        row(displayUrl="https://cdn.example/post.png", recommended=[{"displayUrl": "https://cdn.example/foreign.png"}])]}],
        adapter.normalize_target({"target": "openai"}), manifest)
    batch = validated(candidate, prepared)
    assert batch.items[0].metadata["media_urls"] == ["https://cdn.example/post.png"]
    store.close()


def test_signed_duplicate_upgrades_resolution_but_arbitrary_query_ids_stay_distinct():
    media = extract_media({"images": [
        {"imageUrl": "https://cdninstagram.com/photo.jpg?sig=1", "width": 10, "height": 10},
        {"imageUrl": "https://cdninstagram.com/photo.jpg?sig=2", "width": 100, "height": 100}]})
    assert media.total_count == 1 and media.images[0].width == 100
    assert extract_media({"images": ["https://cdn.example/image?id=1", "https://cdn.example/image?id=2"]}).total_count == 2


def test_legacy_thumbnail_mapping_cannot_reintroduce_video_file_url(tmp_path):
    store, _, candidate = _repository(tmp_path)
    data = json.loads(candidate.manifest_json)
    data["output"]["thumbnail_url"] = {"pointers": ["/displayUrl"], "transforms": ["normalize_url"]}
    raw = json.dumps(data)
    candidate = replace(candidate, manifest_json=raw, manifest_hash=actor_manifest_hash(raw))
    batch = validated(candidate, [row(displayUrl="https://cdn.example/movie.mp4")])
    assert batch.items and not batch.items[0].metadata.get("image_url")
    assert batch.items[0].content == "caption"
    store.close()
