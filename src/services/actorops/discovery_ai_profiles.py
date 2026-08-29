"""Route-specific product goals for Actor schema mapping."""

from __future__ import annotations


_COMMON_GOAL = {
    "purpose": "detect newly published items and create a compact Feed preview",
    "required_core": ["native_id", "url", "published_at"],
    "required_preview_any": ["title", "text"],
    "optional_preview": [
        "thumbnail_url",
        "author",
        "author_handle",
        "source_name",
        "source_url",
    ],
    "detail_policy": (
        "The service opens the canonical URL for full detail. Do not require full "
        "article bodies, transcripts, comments, engagement metrics, or every image."
    ),
}


def route_mapping_profile(route: str) -> dict[str, object]:
    """Return the bounded mapping vocabulary for one registered route."""

    profiles: dict[str, dict[str, object]] = {
        "x/profile/items": {
            "source": "X",
            "accepted_actor_types": [
                "profile timeline posts or tweets",
                "author-bound tweet search",
                "profile posts with nested author data",
            ],
            "wrong_route_actor_types": [
                "profile metadata only",
                "followers or following relationships",
                "likes, users, or unrelated global search results",
            ],
            "target_inputs": {
                "handle": ["handle", "username", "from", "query"],
                "handle_array": ["handles", "twitterHandles"],
                "url": ["profileUrl"],
                "url_array": ["profileUrls", "startUrls", "accountUrls"],
            },
            "content_aliases": {
                "native_id": ["id", "tweetId", "postId", "rest_id"],
                "url": ["url", "tweetUrl", "postUrl", "permalink"],
                "published_at": ["createdAt", "created_at", "timestamp", "date"],
                "title_or_text": ["text", "fullText", "content", "body"],
                "identity": [
                    "author.username",
                    "author.screenName",
                    "authorUsername",
                    "username",
                    "user_name",
                    "screen_name",
                ],
                "image": [
                    "media[].url",
                    "photos[].url",
                    "imageUrl",
                    "thumbnailUrl",
                ],
            },
        },
        "instagram/profile/items": {
            "source": "Instagram",
            "accepted_actor_types": [
                "profile posts",
                "profile reels",
                "profile media items",
            ],
            "wrong_route_actor_types": [
                "profile metadata only",
                "comments only",
                "hashtag or location results not bound to the requested profile",
            ],
            "target_inputs": {
                "handle": ["username", "profile", "handle"],
                "handle_array": ["usernames"],
                "url": ["profileUrl"],
                "url_array": ["startUrls", "profileUrls"],
            },
            "content_aliases": {
                "native_id": ["id", "shortCode", "shortcode", "postId"],
                "url": ["url", "postUrl", "permalink", "displayUrl"],
                "published_at": ["timestamp", "takenAt", "createdAt", "date"],
                "title_or_text": ["caption", "text", "title", "description"],
                "identity": [
                    "ownerUsername",
                    "authorUsername",
                    "username",
                    "owner.username",
                    "user.username",
                ],
                "image": [
                    "displayUrl",
                    "imageUrl",
                    "thumbnailUrl",
                    "images[].url",
                ],
            },
        },
        "youtube/channel/items": {
            "source": "YouTube",
            "accepted_actor_types": [
                "channel uploads, videos, or Shorts as one row per publication",
                "channel record containing a nested recent-videos array",
                "general YouTube scraper with a dedicated videos Dataset",
            ],
            "wrong_route_actor_types": [
                "comments only",
                "subtitles or transcripts for one video only",
                "channel profile metadata without published video items",
            ],
            "target_inputs": {
                "native_id": ["channelId", "channel_id"],
                "native_id_array": ["channelIds"],
                "handle": ["channelHandle"],
                "handle_array": ["youtubeHandles"],
                "url": ["channelUrl", "url"],
                "url_array": ["channelUrls", "startUrls", "targets"],
            },
            "content_aliases": {
                "native_id": ["id", "videoId", "Video ID", "ID"],
                "url": ["url", "videoUrl", "URL"],
                "published_at": [
                    "date",
                    "publishedAt",
                    "publishedDate",
                    "Published Time",
                ],
                "title_or_text": ["title", "Title", "description", "Description"],
                "identity": ["channelId", "channel_id", "sourceId"],
                "image": ["thumbnailUrl", "Thumbnail URL", "thumbnail"],
            },
        },
    }
    return {"product_goal": dict(_COMMON_GOAL), **profiles.get(route, {})}


__all__ = ["route_mapping_profile"]
