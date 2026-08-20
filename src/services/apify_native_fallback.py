"""Actor-first YouTube acquisition with a bounded public-feed degradation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

import httpx

from ..models import ContentItem, SourceType
from .network_policy import NetworkResolutionError, UnsafeNetworkTarget


class NativeFallbackDecision(str, Enum):
    """Whether a native acquisition result may spend on an Actor fallback."""
    ACCEPT_NATIVE = "accept_native"
    ACTOR_FALLBACK = "actor_fallback"
    FAIL_CLOSED = "fail_closed"


@dataclass(frozen=True, slots=True)
class NativeFetchEvidence:
    """Bounded evidence used by the fallback admission policy."""

    canonical_url: str
    config_valid: bool = True
    security_rejected: bool = False
    confirmed_target_unavailable: bool = False
    target_previously_validated: bool = False
    returned_empty: bool = False
    had_historical_content: bool = False
    schema_drift: bool = False
    status_code: int | None = None
    exception: BaseException | None = None


def is_canonical_youtube_url(value: str) -> bool:
    """Accept only an HTTPS youtube.com identity, never a pinned transport IP."""

    try:
        parsed = urlparse(str(value))
    except ValueError:
        return False
    host = str(parsed.hostname or "").rstrip(".").casefold()
    return (
        parsed.scheme.casefold() == "https"
        and (host == "youtube.com" or host.endswith(".youtube.com"))
        and parsed.port in {None, 443}
        and not parsed.username
        and not parsed.password
    )


def decide_youtube_actor_fallback(
    evidence: NativeFetchEvidence,
) -> NativeFallbackDecision:
    """Apply the paid fallback matrix without inspecting target contents."""

    if (
        not evidence.config_valid
        or evidence.security_rejected
        or evidence.confirmed_target_unavailable
        or not is_canonical_youtube_url(evidence.canonical_url)
    ):
        return NativeFallbackDecision.FAIL_CLOSED

    if evidence.schema_drift:
        return NativeFallbackDecision.ACTOR_FALLBACK
    if evidence.returned_empty:
        return NativeFallbackDecision.ACTOR_FALLBACK if evidence.had_historical_content else NativeFallbackDecision.ACCEPT_NATIVE

    status_code = evidence.status_code
    if isinstance(evidence.exception, httpx.HTTPStatusError):
        status_code = int(evidence.exception.response.status_code)
    if isinstance(evidence.exception, (TimeoutError, httpx.TimeoutException, NetworkResolutionError, httpx.TransportError)):
        return NativeFallbackDecision.ACTOR_FALLBACK
    if status_code == 429 or (status_code is not None and status_code >= 500):
        return NativeFallbackDecision.ACTOR_FALLBACK
    if status_code == 404 and evidence.target_previously_validated:
        return NativeFallbackDecision.ACTOR_FALLBACK
    if evidence.exception is not None or (
        status_code is not None and status_code >= 400
    ):
        return NativeFallbackDecision.FAIL_CLOSED
    return NativeFallbackDecision.ACCEPT_NATIVE


def _youtube_video_id(item: ContentItem) -> str:
    metadata = item.metadata if isinstance(item.metadata, dict) else {}
    for key in ("native_id", "video_id", "videoId"):
        value = str(metadata.get(key) or "").strip()
        if value:
            return value
    parsed = urlparse(str(item.url))
    host = str(parsed.hostname or "").rstrip(".").casefold()
    if host == "youtu.be" or host.endswith(".youtu.be"):
        return parsed.path.strip("/").split("/", 1)[0]
    if host == "youtube.com" or host.endswith(".youtube.com"):
        query_id = str(parse_qs(parsed.query).get("v", [""])[0]).strip()
        if query_id:
            return query_id
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"shorts", "live", "embed"}:
            return parts[1]
    return hashlib.sha256(str(item.url).encode("utf-8")).hexdigest()[:24]


def reattribute_youtube_fallback_items(
    items: Iterable[ContentItem],
    *,
    source_id: str,
    source_key: str,
    canonical_feed_url: str,
) -> list[ContentItem]:
    """Project Actor output back onto the original RSS source identity."""

    if not is_canonical_youtube_url(canonical_feed_url):
        raise ValueError("canonical_feed_url must keep a youtube.com identity")
    feed_id = canonical_feed_url.split("//", 1)[1].replace("/", "_")
    projected: list[ContentItem] = []
    for original in items:
        item = original.model_copy(deep=True)
        native_id = _youtube_video_id(item)
        entry_hash = hashlib.sha256(
            f"yt:video:{native_id}".encode("utf-8")
        ).hexdigest()[:16]
        item.id = f"rss:{feed_id}:{entry_hash}"
        item.source_type = SourceType.RSS
        item.metadata.update(
            {
                "source_id": str(source_id),
                "source_key": str(source_key),
                "catalog_type": "rss",
                "acquisition_origin": "apify_actor",
                "native_id": native_id,
            }
        )
        projected.append(item)
    generation = getattr(items, "_apify_actor_route_generation", None)
    if not isinstance(generation, int):
        return projected
    from .apify_actor_route import ApifyActorRoutedList

    return ApifyActorRoutedList(
        projected,
        route_generation=generation,
        workspace_id=getattr(items, "_apify_actor_workspace_id", None),
        source_id=getattr(items, "_apify_actor_source_id", None),
        candidate_id=getattr(items, "_apify_actor_candidate_id", None),
        latest_published_at=getattr(items, "_apify_actor_latest_published_at", None),
        latest_item_id_hash=getattr(
            items, "_apify_actor_latest_item_id_hash", None
        ),
        semantic_outcome=getattr(items, "_apify_actor_semantic_outcome", None),
    )


class YouTubeNativeActorFallbackScraper:
    """Use a source-certified Actor before the public Atom degradation."""

    def __init__(
        self,
        source: Any,
        http_client: httpx.AsyncClient,
        *,
        actor_ops: Any,
        apify_coordinator: Any,
        job_id: str | None = None,
    ) -> None:
        from ..scrapers.rss import RSSScraper

        self.source = source
        self.actor_ops = actor_ops
        self.apify_coordinator = apify_coordinator
        self.job_id = job_id
        self.native = RSSScraper([source], http_client)
        self.native.strict_errors = True
        self.client = http_client
        self.publication_snapshots: list[Any] = []

    @property
    def upstream_response_schema(self) -> dict[str, Any] | None:
        return self.native.upstream_response_schema

    @property
    def source_avatar_hints(self) -> tuple[Any, ...]:
        return self.native.source_avatar_hints

    @property
    def strict_errors(self) -> bool:
        return True

    @strict_errors.setter
    def strict_errors(self, _value: bool) -> None:
        self.native.strict_errors = True

    async def fetch(self, since: datetime) -> list[ContentItem]:
        canonical_url = str(self.source.url)
        binding = None
        route = None
        frozen_snapshot = None
        snapshot_error: BaseException | None = None
        try:
            binding = self.actor_ops.get_source_binding(str(self.source.source_id))
        except Exception as exc:
            if getattr(exc, "code", "") != "apify_actor_source_binding_not_found":
                raise
        validated = bool(
            binding
            and str(binding["validation_status"])
            in {"ready_1of1", "ready_2of2", "ready_3of3", "revalidation_pending"}
        )
        if validated and binding is not None:
            try:
                route = self.actor_ops.get_route(str(binding["route_id"]))
                if str(route["platform"]) != "youtube":
                    raise ValueError("YouTube binding has the wrong platform")
                frozen_snapshot = self.actor_ops.freeze_execution(str(binding["route_id"]), source_id=str(self.source.source_id))
            except Exception as exc:
                snapshot_error = exc
        actor_error: BaseException | None = None
        if validated and binding is not None and frozen_snapshot and route:
            try:
                return await self._fetch_actor(binding, frozen_snapshot, since)
            except BaseException as exc:
                actor_error = exc
        error: BaseException | None = None
        try:
            native_items = await self.native.fetch(since)
        except BaseException as exc:
            native_items = []
            error = exc
        if native_items:
            return native_items
        if actor_error is not None:
            raise actor_error

        status_code = (
            int(error.response.status_code)
            if isinstance(error, httpx.HTTPStatusError)
            else None
        )
        security_rejected = isinstance(error, UnsafeNetworkTarget) and not isinstance(
            error,
            NetworkResolutionError,
        )
        error_code = str(getattr(error, "code", "") or "").casefold()
        schema_drift = bool(
            error is not None
            and not security_rejected
            and (
                isinstance(error, (AttributeError, KeyError, TypeError, ValueError))
                or any(
                    marker in error_code
                    for marker in ("schema", "parse", "contract")
                )
            )
        )
        evidence = NativeFetchEvidence(
            canonical_url=canonical_url,
            config_valid=is_canonical_youtube_url(canonical_url),
            security_rejected=security_rejected,
            target_previously_validated=validated,
            returned_empty=error is None,
            had_historical_content=self._had_historical_content(),
            schema_drift=schema_drift,
            status_code=status_code,
            exception=error,
        )
        decision = decide_youtube_actor_fallback(evidence)
        if decision == NativeFallbackDecision.ACCEPT_NATIVE:
            return []
        if decision == NativeFallbackDecision.FAIL_CLOSED:
            if error is not None:
                raise error
            from ..scrapers.base import SourceFetchError

            raise SourceFetchError(
                "YouTube native source failed closed before paid fallback",
                retryable=False,
                code="youtube_actor_fallback_denied",
            )
        if not validated or binding is None:
            from ..scrapers.base import SourceFetchError

            raise SourceFetchError(
                "YouTube Actor fallback is not source-validated",
                retryable=True,
                code="apify_actor_source_binding_not_ready",
            )
        if frozen_snapshot is None or route is None:
            from ..scrapers.base import SourceFetchError

            raise SourceFetchError(
                "YouTube Actor fallback snapshot was unavailable at fetch start",
                retryable=bool(getattr(snapshot_error, "retryable", True)),
                code=str(
                    getattr(
                        snapshot_error,
                        "code",
                        "apify_actor_route_snapshot_unavailable",
                    )
                ),
            ) from snapshot_error

        return await self._fetch_actor(binding, frozen_snapshot, since)

    async def _fetch_actor(
        self,
        binding: Any,
        frozen_snapshot: Any,
        since: datetime,
    ) -> list[ContentItem]:
        self.publication_snapshots.append(frozen_snapshot)
        if getattr(frozen_snapshot, "actorops_version", 1) == 2:
            from .actorops.youtube_rss_compat import fetch_v2_youtube_rss
            return await fetch_v2_youtube_rss(source=self.source, actor_ops=self.actor_ops, coordinator=self.apify_coordinator,
                http_client=self.client, binding=binding, snapshot=frozen_snapshot, since=since, job_id=self.job_id)
        from ..scrapers.apify_client import ApifyClient
        from .apify_actor_manifest import ActorRuntime
        from .apify_actor_runtime import ActorContentContext, ApifyActorRuntimeService, actor_target_for_route

        result = await ApifyActorRuntimeService(self.actor_ops, ApifyClient(
            coordinator=self.apify_coordinator, http_client=self.client,
        )).fetch(
            route_id=str(binding["route_id"]), source_id=str(self.source.source_id),
            target=actor_target_for_route("youtube", str(self.source.url)),
            runtime=ActorRuntime(max_items=int(self.source.fetch_limit),
                since_iso=since.astimezone(timezone.utc).isoformat(),
                until_iso=datetime.now(timezone.utc).isoformat()),
            content=ActorContentContext(platform="youtube", source_id=str(self.source.source_id),
                source_key=str(self.source.source_key or canonical_url),
                source_name=str(self.source.source_display_name or self.source.name),
                channel=self.source.channel, topics=tuple(self.source.topics),
                tags=tuple(self.source.tags), personal_tags=tuple(self.source.personal_tags),
                analysis_mode=(self.source.analysis_mode.value if hasattr(self.source.analysis_mode, "value") else str(self.source.analysis_mode))),
            job_id=self.job_id, frozen_snapshot=frozen_snapshot,
            source_target_value=str(self.source.url),
        )
        return reattribute_youtube_fallback_items(result.value or [],
            source_id=str(self.source.source_id),
            source_key=str(self.source.source_key or self.source.url),
            canonical_feed_url=str(self.source.url))

    def _had_historical_content(self) -> bool:
        row = self.actor_ops.store.connect().execute(
            """
            SELECT 1 FROM user_content_items
            WHERE workspace_id = ? AND source_id = ?
            LIMIT 1
            """,
            (
                self.actor_ops.workspace_id,
                str(self.source.source_id),
            ),
        ).fetchone()
        return row is not None
