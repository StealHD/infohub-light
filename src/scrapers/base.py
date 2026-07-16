"""Base scraper interface."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, List
import httpx

from ..models import ContentItem
from ..services.response_schema import extract_response_schema, merge_response_schemas


class SourceFetchError(RuntimeError):
    """A source-level failure with an explicit retry policy."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = True,
        code: str | None = None,
    ):
        super().__init__(message)
        self.retryable = retryable
        self.code = code or type(self).__name__


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
        self.strict_errors = False
        self._upstream_response_schemas: list[dict[str, Any]] = []

    def observe_upstream_response(self, value: Any) -> None:
        """Retain only a bounded structural summary of a transient response."""

        self._upstream_response_schemas.append(extract_response_schema(value))

    @property
    def upstream_response_schema(self) -> dict[str, Any] | None:
        if not self._upstream_response_schemas:
            return None
        return merge_response_schemas(self._upstream_response_schemas)

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
        analysis_mode = getattr(source_config, "analysis_mode", "full")
        if hasattr(analysis_mode, "value"):
            analysis_mode = analysis_mode.value
        metadata = {
            "channel": hub_channel,
            "topics": topics,
            "tags": topics,
            "personal_tags": list(getattr(source_config, "personal_tags", []) or []),
            "source_id": getattr(source_config, "source_id", None),
            "subscription_id": getattr(source_config, "subscription_id", None),
            "source_key": getattr(source_config, "source_key", None),
            "source_display_name": getattr(source_config, "source_display_name", None),
            "catalog_source_type": getattr(source_config, "catalog_source_type", None),
            "source_priority": int(getattr(source_config, "source_priority", 0) or 0),
            "analysis_mode": str(analysis_mode or "full"),
        }
        if metadata["analysis_mode"] == "personal_only":
            metadata["show_in_personal_feed"] = True
        return metadata
