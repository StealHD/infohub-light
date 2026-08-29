"""Conservative Store-card gate for obviously wrong Actor route types."""

from __future__ import annotations

import re

from .ports import DiscoveryActorMatch


_TOKEN_BREAK = re.compile(r"[^a-z0-9]+")
_NEGATIVE_PHRASES = {
    "x": (
        "followers scraper", "follower scraper", "following scraper",
        "quote tweets", "quote tweet", "retweets scraper", "retweet scraper",
        "reposts scraper", "repost scraper", "profile scraper",
        "list scraper", "trends scraper", "user scraper",
    ),
    "instagram": (
        "followers scraper", "follower scraper", "following scraper",
        "hashtag scraper", "location scraper", "comments scraper",
        "comment scraper", "profile scraper", "email scraper",
        "story details", "story downloader", "contact scraper",
        "profile extractor", "post details", "hashtag posts",
        "engagement scraper",
    ),
    "youtube": (
        "comments scraper", "comment scraper", "subtitles", "subtitle",
        "transcripts", "transcript", "thumbnail downloader",
        "email scraper", "hashtag scraper", "playlist extractor",
        "playlist videos scraper", "description extractor",
        "music podcast scraper", "thumbnail generator",
        "channel id extractor", "hashtag video",
    ),
}
_PLATFORM_TOKENS = {
    "x": frozenset({"twitter", "tweet", "tweets", "x"}),
    "instagram": frozenset({"ig", "instagram"}),
    "youtube": frozenset({"youtube", "yt"}),
}
_FOREIGN_PLATFORM_TOKENS = frozenset({
    "avito", "facebook", "linkedin", "pinterest", "pubmed", "reddit",
    "rednote", "scribd", "skool", "spotify", "threads", "tiktok", "twitch",
})
_PUBLICATION_TOKENS = {
    "x": frozenset({"post", "posts", "timeline", "tweet", "tweets"}),
    "instagram": frozenset({"media", "post", "posts", "reel", "reels"}),
    "youtube": frozenset({"channel", "short", "shorts", "upload", "uploads", "video", "videos"}),
}


def store_match_is_wrong_type(
    platform: str, match: DiscoveryActorMatch
) -> bool:
    """Reject only explicit non-publication products before exact Build reads."""

    normalized = " ".join(
        _TOKEN_BREAK.sub(" ", value.casefold()).strip()
        for value in (
            match.actor_id, match.display_name, match.short_description,
        )
        if value
    )
    tokens = frozenset(normalized.split())
    platform_tokens = _PLATFORM_TOKENS.get(platform, frozenset())
    if platform_tokens and not tokens & platform_tokens:
        other_known = _FOREIGN_PLATFORM_TOKENS.union(*(
            known for key, known in _PLATFORM_TOKENS.items() if key != platform
        ))
        if tokens & other_known:
            return True
    positives = _PUBLICATION_TOKENS.get(platform, frozenset())
    negative = next(
        (
            phrase for phrase in _NEGATIVE_PHRASES.get(platform, ())
            if phrase in normalized
        ),
        None,
    )
    if negative is None:
        return False
    # Mixed products such as "posts and comments" remain valid because they
    # can still satisfy the Route's minimal publication contract.
    if platform == "x" and negative == "profile scraper":
        return not bool(tokens & positives)
    if platform == "instagram" and negative in {
        "profile scraper", "comments scraper", "comment scraper",
    }:
        return not bool(tokens & positives)
    return True


__all__ = ["store_match_is_wrong_type"]
