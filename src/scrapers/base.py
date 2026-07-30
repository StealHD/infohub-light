"""Base scraper interface."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, List
import httpx

from ..models import ContentItem
from ..services.feed_run import SourceAvatarHint
from ..services.response_schema import extract_response_schema, merge_response_schemas
from ..services.source_acquisition import target_subscription_projection


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
        self._source_avatar_hints: list[SourceAvatarHint] = []

    def observe_upstream_response(self, value: Any) -> None:
        """Retain only a bounded structural summary of a transient response."""

        self._upstream_response_schemas.append(extract_response_schema(value))

    @property
    def upstream_response_schema(self) -> dict[str, Any] | None:
        if not self._upstream_response_schemas:
            return None
        return merge_response_schemas(self._upstream_response_schemas)

    def observe_source_avatar(
        self,
        *,
        source_id: Any,
        remote_url: Any,
        origin: str,
        kind: str = "image",
    ) -> None:
        """Record bounded source media independently of selected content items."""

        normalized_source_id = str(source_id or "").strip()
        normalized_url = str(remote_url or "").strip()
        normalized_origin = str(origin or "").strip()
        if (
            not normalized_source_id
            or not normalized_origin
            or kind not in {"image", "page"}
            or not normalized_url.startswith(("https://", "http://"))
        ):
            return
        hint = SourceAvatarHint(
            source_id=normalized_source_id,
            remote_url=normalized_url,
            origin=normalized_origin[:64],
            kind=kind,
        )
        if hint not in self._source_avatar_hints:
            self._source_avatar_hints.append(hint)

    @property
    def source_avatar_hints(self) -> tuple[SourceAvatarHint, ...]:
        return tuple(self._source_avatar_hints)

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
        return target_subscription_projection(source_config).metadata()
