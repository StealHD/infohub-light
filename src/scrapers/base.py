"""Base scraper interface."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List
import httpx

from ..models import ContentItem


class BaseScraper(ABC):
    """Abstract base class for all scrapers."""

    def __init__(self, config: dict, http_client: httpx.AsyncClient):
        """Initialize scraper.

        Args:
            config: Scraper-specific configuration
            http_client: Shared async HTTP client
        """
        self.config = config
        self.client = http_client

    @abstractmethod
    async def fetch(self, since: datetime) -> List[ContentItem]:
        """Fetch content items published since the given time.

        Args:
            since: Only fetch items published after this time

        Returns:
            List[ContentItem]: Fetched content items
        """
        pass

    def _generate_id(self, source_type: str, subtype: str, native_id: str) -> str:
        """Generate unique content item ID.

        Args:
            source_type: Source type (github, hackernews, etc.)
            subtype: Content subtype (event, release, story, etc.)
            native_id: Native ID from the source platform

        Returns:
            str: Unique ID in format {source}:{subtype}:{native_id}
        """
        return f"{source_type}:{subtype}:{native_id}"

    def _tag_metadata(self, source_config) -> dict:
        """Return separated reading topics and personal tags for a source."""
        topics = list(getattr(source_config, "topics", []) or [])
        legacy_tags = list(getattr(source_config, "tags", []) or [])
        for tag in legacy_tags:
            if tag not in topics:
                topics.append(tag)
        if hasattr(source_config, "hub_channel"):
            hub_channel = getattr(source_config, "hub_channel", None) or getattr(
                source_config, "category", None
            )
        else:
            hub_channel = getattr(source_config, "channel", None) or getattr(
                source_config, "category", None
            )
        return {
            "channel": hub_channel,
            "topics": topics,
            "tags": topics,
            "personal_tags": list(getattr(source_config, "personal_tags", []) or []),
        }
