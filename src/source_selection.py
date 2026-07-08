"""Source selection helpers shared by CLI, UI, and MCP integrations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class SourceSelectionError(ValueError):
    """Raised when a source reference cannot be resolved safely."""


INDEXED_SOURCE_ALIASES = {
    "rss": "rss",
    "github": "github",
    "github_release": "github",
    "github_user": "github",
    "reddit_subreddit": "reddit_subreddit",
    "telegram_channel": "telegram_channel",
    "apify_social": "apify_social",
}

TOP_LEVEL_SOURCES = {
    "github",
    "hackernews",
    "rss",
    "reddit",
    "telegram",
    "twitter",
    "apify_social",
    "openbb",
    "ossinsight",
}

VALID_SOURCES = TOP_LEVEL_SOURCES


@dataclass(frozen=True)
class SourceRef:
    """A concrete single source selection."""

    source_type: str
    index: int | None = None

    @property
    def ref(self) -> str:
        if self.index is None:
            return self.source_type
        return f"{self.source_type}:{self.index}"


def parse_source_ref(source_type: str, index: int | str | None = None) -> SourceRef:
    """Parse a source type/index pair or compact ``source:index`` reference."""

    raw = str(source_type or "").strip().lower()
    if not raw:
        raise SourceSelectionError("source_type is required")

    if ":" in raw and index is None:
        raw, raw_index = raw.split(":", 1)
        index = raw_index

    if raw == "hackernews":
        if index not in (None, ""):
            raise SourceSelectionError("hackernews does not accept an index")
        return SourceRef("hackernews")

    canonical = INDEXED_SOURCE_ALIASES.get(raw)
    if not canonical:
        raise SourceSelectionError(f"unknown source_type: {source_type}")

    if index in (None, ""):
        raise SourceSelectionError(f"{canonical} requires an index")
    try:
        parsed_index = int(index)
    except (TypeError, ValueError) as exc:
        raise SourceSelectionError("index must be a non-negative integer") from exc
    if parsed_index < 0:
        raise SourceSelectionError("index must be a non-negative integer")

    return SourceRef(canonical, parsed_index)


def filter_config_for_source_ref(config: Any, source_ref: SourceRef) -> Any:
    """Return a deep-copied config containing only one concrete source."""

    clone = config.model_copy(deep=True)
    sources = clone.sources
    idx = source_ref.index

    if source_ref.source_type == "hackernews":
        if not sources.hackernews.enabled:
            raise SourceSelectionError("hackernews source is disabled")
        _disable_all_sources(clone)
        sources.hackernews.enabled = True
        return clone

    if idx is None:
        raise SourceSelectionError(f"{source_ref.source_type} requires an index")

    if source_ref.source_type == "rss":
        item = _enabled_item(sources.rss, idx, "rss")
        _disable_all_sources(clone)
        sources.rss = [item]
        return clone

    if source_ref.source_type == "github":
        item = _enabled_item(sources.github, idx, "github")
        _disable_all_sources(clone)
        sources.github = [item]
        return clone

    if source_ref.source_type == "reddit_subreddit":
        if not sources.reddit.enabled:
            raise SourceSelectionError("reddit source is disabled")
        item = _enabled_item(sources.reddit.subreddits, idx, "reddit_subreddit")
        _disable_all_sources(clone)
        sources.reddit.enabled = True
        sources.reddit.subreddits = [item]
        return clone

    if source_ref.source_type == "telegram_channel":
        if not sources.telegram.enabled:
            raise SourceSelectionError("telegram source is disabled")
        item = _enabled_item(sources.telegram.channels, idx, "telegram_channel")
        _disable_all_sources(clone)
        sources.telegram.enabled = True
        sources.telegram.channels = [item]
        return clone

    if source_ref.source_type == "apify_social":
        if not sources.apify_social.enabled:
            raise SourceSelectionError("apify_social source is disabled")
        item = _enabled_item(sources.apify_social.subscriptions, idx, "apify_social")
        _disable_all_sources(clone)
        sources.apify_social.enabled = True
        sources.apify_social.subscriptions = [item]
        return clone

    raise SourceSelectionError(f"unknown source ref: {source_ref.ref}")


def apply_source_filter(
    config: Any, sources: list[str] | None
) -> tuple[Any, list[str], list[str]]:
    """Return a config filtered to selected top-level source families."""

    if not sources:
        enabled = get_enabled_sources(config)
        return config, enabled, []

    wanted = {s.strip().lower() for s in sources if s.strip()}
    unknown = sorted(wanted - TOP_LEVEL_SOURCES)
    chosen = sorted(wanted & TOP_LEVEL_SOURCES)

    clone = config.model_copy(deep=True)

    if "github" not in wanted:
        clone.sources.github = []
    if "hackernews" not in wanted:
        clone.sources.hackernews.enabled = False
    if "rss" not in wanted:
        clone.sources.rss = []
    if "reddit" not in wanted:
        clone.sources.reddit.enabled = False
        clone.sources.reddit.subreddits = []
        clone.sources.reddit.users = []
    if "telegram" not in wanted:
        clone.sources.telegram.enabled = False
        clone.sources.telegram.channels = []
    if "twitter" not in wanted and getattr(clone.sources, "twitter", None):
        clone.sources.twitter.enabled = False
        clone.sources.twitter.users = []
    if "apify_social" not in wanted:
        clone.sources.apify_social.enabled = False
        clone.sources.apify_social.subscriptions = []
    if "openbb" not in wanted and getattr(clone.sources, "openbb", None):
        clone.sources.openbb.enabled = False
        clone.sources.openbb.watchlists = []
    if "ossinsight" not in wanted:
        clone.sources.ossinsight.enabled = False

    return clone, chosen, unknown


def get_enabled_sources(config: Any) -> list[str]:
    """List enabled top-level source families in an effective config."""

    enabled: list[str] = []
    if getattr(config.sources, "github", None):
        enabled.append("github")
    if getattr(config.sources.hackernews, "enabled", False):
        enabled.append("hackernews")
    if getattr(config.sources, "rss", None):
        enabled.append("rss")
    if getattr(config.sources.reddit, "enabled", False):
        enabled.append("reddit")
    if getattr(config.sources.telegram, "enabled", False):
        enabled.append("telegram")
    if getattr(getattr(config.sources, "twitter", None), "enabled", False):
        enabled.append("twitter")
    if getattr(config.sources.apify_social, "enabled", False):
        enabled.append("apify_social")
    if getattr(getattr(config.sources, "openbb", None), "enabled", False):
        enabled.append("openbb")
    if getattr(config.sources.ossinsight, "enabled", False):
        enabled.append("ossinsight")
    return enabled


def _enabled_item(items: list[Any], idx: int, label: str) -> Any:
    if idx >= len(items):
        raise SourceSelectionError(f"{label} index {idx} is out of range")
    item = items[idx]
    if getattr(item, "enabled", True) is False:
        raise SourceSelectionError(f"{label} index {idx} is disabled")
    return item


def _disable_all_sources(config: Any) -> None:
    sources = config.sources
    sources.github = []
    sources.hackernews.enabled = False
    sources.rss = []
    sources.reddit.enabled = False
    sources.reddit.subreddits = []
    sources.reddit.users = []
    sources.telegram.enabled = False
    sources.telegram.channels = []
    if getattr(sources, "twitter", None):
        sources.twitter.enabled = False
        sources.twitter.users = []
    sources.apify_social.enabled = False
    sources.apify_social.subscriptions = []
    if getattr(sources, "openbb", None):
        sources.openbb.enabled = False
        sources.openbb.watchlists = []
    sources.ossinsight.enabled = False
