"""Registry-driven public source resolution for Agent subscription workflows."""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

from ..storage.service_store import (
    AgentSourceResolutionAuthorizationError,
    AgentSourceResolutionLimitError,
    ServiceStore,
)
from .agent_change_proposal import DelegatedActor
from .source_type_registry import (
    SourceConfigError,
    catalog_source_matches_agent_type,
    normalize_source_setup_input,
    source_key,
    validate_agent_source_type,
)
from .youtube_channel import (
    ResolvedYouTubeChannel,
    YouTubeChannelError,
    YouTubeChannelResolver,
)


SOURCE_RESOLUTION_MAX_CANDIDATES = 5
SOURCE_RESOLUTION_DATA_TRUST = "untrusted_public_metadata"
_RESOLUTION_REF_RE = re.compile(r"asr_[0-9a-f]{32}\Z")


class SourceResolutionError(ValueError):
    """Stable, non-sensitive error for source-resolution callers."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ResolvedSource:
    """Adapter-neutral verified source metadata."""

    identity: str
    display_name: str
    public_url: str
    config: dict[str, Any]


class SourceResolutionAdapter(Protocol):
    source_type: str

    def normalize_direct_input(self, value: str) -> str | None:
        """Return a direct locator, or None when agent discovery is required."""

    def normalize_candidate_url(self, value: str) -> str:
        """Validate an official candidate URL without network access."""

    async def resolve(self, locator: str) -> ResolvedSource:
        """Resolve and verify one prevalidated locator."""


class YouTubeSourceResolutionAdapter:
    """Resolve only fixed official YouTube channel locators."""

    source_type = "youtube"

    def __init__(
        self, resolver: YouTubeChannelResolver | None = None
    ) -> None:
        self.resolver = resolver or YouTubeChannelResolver()

    @staticmethod
    def _invalid() -> SourceResolutionError:
        return SourceResolutionError(
            "invalid_request",
            "YouTube source locator is invalid",
        )

    def normalize_direct_input(self, value: str) -> str | None:
        text = str(value or "").strip()
        if not text:
            raise self._invalid()
        direct_shape = (
            text.startswith("@")
            or re.fullmatch(r"UC[A-Za-z0-9_-]{22}", text) is not None
            or "://" in text
        )
        if not direct_shape:
            return None
        try:
            return self.resolver.normalize_locator(text)
        except YouTubeChannelError:
            raise self._invalid() from None

    def normalize_candidate_url(self, value: str) -> str:
        text = str(value or "").strip()
        try:
            parsed = urlparse(text)
            host = parsed.hostname
            if (
                parsed.scheme != "https"
                or not host
                or host.lower() != "www.youtube.com"
            ):
                raise self._invalid()
            return self.resolver.normalize_locator(text)
        except (SourceResolutionError, ValueError):
            raise self._invalid() from None
        except YouTubeChannelError:
            raise self._invalid() from None

    async def resolve(self, locator: str) -> ResolvedSource:
        channel: ResolvedYouTubeChannel = await self.resolver.resolve_verified(
            locator
        )
        try:
            setup = normalize_source_setup_input(
                "youtube",
                {
                    "url": channel.feed_url,
                    "keep_latest_item": True,
                },
            )
        except SourceConfigError as exc:  # verified adapter output must round-trip
            raise SourceResolutionError(
                "source_resolution_unavailable",
                "source resolution is unavailable",
                status_code=503,
            ) from exc
        return ResolvedSource(
            identity=channel.channel_id,
            display_name=channel.display_name[:120],
            public_url=channel.public_url,
            config={
                "url": channel.feed_url,
                "keep_latest_item": bool(
                    setup["config"].get("keep_latest_item")
                ),
            },
        )


class SourceResolutionService:
    """Resolve public identities and mint actor-bound preparation references."""

    def __init__(
        self,
        store: ServiceStore,
        *,
        adapters: tuple[SourceResolutionAdapter, ...] | None = None,
    ) -> None:
        self.store = store
        selected = adapters or (YouTubeSourceResolutionAdapter(),)
        self.adapters = {adapter.source_type: adapter for adapter in selected}

    @staticmethod
    def _fingerprint(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _visible(source: dict[str, Any], actor: DelegatedActor) -> bool:
        return bool(
            source.get("enabled")
            and source.get("workspace_id") == actor.workspace_id
            and (
                source.get("scope") in {"public", "workspace"}
                or (
                    source.get("scope") == "private"
                    and source.get("owner_user_id") == actor.user_id
                )
            )
        )

    def _reference(
        self,
        *,
        actor: DelegatedActor,
        source_type: str,
        fingerprint: str,
        source: dict[str, Any],
    ) -> tuple[str, str]:
        try:
            row = self.store.create_or_reuse_agent_source_resolution(
                workspace_id=actor.workspace_id,
                user_id=actor.user_id,
                delegation_id=actor.delegation_id,
                source_type=source_type,
                source_fingerprint=fingerprint,
                envelope={"source": source},
            )
        except AgentSourceResolutionAuthorizationError as exc:
            raise SourceResolutionError(
                "unauthorized",
                "delegation is not authorized",
                status_code=401,
            ) from exc
        except AgentSourceResolutionLimitError as exc:
            raise SourceResolutionError(
                "source_resolution_limit",
                "active source resolution limit reached",
                status_code=429,
            ) from exc
        return str(row["id"]), str(row["expires_at"])

    def _candidate(
        self,
        *,
        actor: DelegatedActor,
        source_type: str,
        resolved: ResolvedSource,
    ) -> dict[str, Any]:
        setup = normalize_source_setup_input(source_type, resolved.config)
        catalog_source_type = str(setup["catalog_source_type"])
        catalog_config = dict(setup["config"])
        key = source_key(catalog_source_type, catalog_config)
        fingerprint = self._fingerprint(f"{source_type}\0{key}")
        existing = self.store.get_source_by_key(
            workspace_id=actor.workspace_id,
            source_key=key,
        )
        visible_existing = (
            existing
            if existing is not None
            and self._visible(existing, actor)
            and catalog_source_matches_agent_type(source_type, existing)
            else None
        )
        subscription = (
            self.store.get_user_subscription_for_source(
                actor.user_id, str(visible_existing["id"])
            )
            if visible_existing is not None
            else None
        )
        if subscription is not None:
            state = "subscribed"
            reference = None
        elif visible_existing is not None:
            state = "available"
            reference = self._reference(
                actor=actor,
                source_type=source_type,
                fingerprint=fingerprint,
                source={
                    "mode": "existing",
                    "source_id": str(visible_existing["id"]),
                },
            )
        else:
            state = "new"
            reference = self._reference(
                actor=actor,
                source_type=source_type,
                fingerprint=fingerprint,
                source={
                    "mode": "private",
                    "type": source_type,
                    "display_name": resolved.display_name,
                    "config": dict(resolved.config),
                },
            )
        candidate: dict[str, Any] = {
            "display_name": resolved.display_name,
            "public_url": resolved.public_url,
            "source_type": source_type,
            "subscription_state": state,
            "data_trust": SOURCE_RESOLUTION_DATA_TRUST,
        }
        if reference is not None:
            candidate["resolution_ref"], candidate["expires_at"] = reference
        return candidate

    async def resolve(
        self,
        *,
        actor: DelegatedActor,
        source_type: str,
        input_value: str,
        candidate_urls: list[str] | None = None,
        limit: int = SOURCE_RESOLUTION_MAX_CANDIDATES,
    ) -> dict[str, Any]:
        public_type = validate_agent_source_type(source_type)
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= SOURCE_RESOLUTION_MAX_CANDIDATES
        ):
            raise SourceResolutionError(
                "invalid_request", "source resolution limit is invalid"
            )
        adapter = self.adapters.get(public_type)
        if adapter is None:
            return self._result("web_setup_required", public_type)

        direct = adapter.normalize_direct_input(input_value)
        raw_candidates = list(candidate_urls or [])
        if len(raw_candidates) > SOURCE_RESOLUTION_MAX_CANDIDATES:
            raise SourceResolutionError(
                "invalid_request", "too many source candidates"
            )
        if direct is not None:
            locators = [direct]
        else:
            locators = [
                adapter.normalize_candidate_url(value)
                for value in raw_candidates[:limit]
            ]
        locators = list(dict.fromkeys(locators))
        if not locators:
            return self._result("discovery_required", public_type)

        outcomes = await asyncio.gather(
            *(adapter.resolve(locator) for locator in locators),
            return_exceptions=True,
        )
        verified: list[ResolvedSource] = []
        seen: set[str] = set()
        retryable_failure = False
        for outcome in outcomes:
            if isinstance(outcome, ResolvedSource):
                if outcome.identity not in seen:
                    seen.add(outcome.identity)
                    verified.append(outcome)
                continue
            if isinstance(outcome, YouTubeChannelError):
                retryable_failure = retryable_failure or outcome.retryable
                continue
            if isinstance(outcome, SourceResolutionError):
                retryable_failure = retryable_failure or (
                    outcome.status_code >= 500
                )
                continue
            retryable_failure = True

        if not verified:
            return self._result(
                "unavailable" if retryable_failure else "not_found",
                public_type,
            )
        candidates = [
            self._candidate(
                actor=actor,
                source_type=public_type,
                resolved=item,
            )
            for item in verified
        ]
        return self._result(
            "resolved" if len(candidates) == 1 else "ambiguous",
            public_type,
            candidates,
        )

    @staticmethod
    def _result(
        status: str,
        source_type: str,
        candidates: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        values = list(candidates or [])
        return {
            "status": status,
            "source_type": source_type,
            "candidates": values,
            "returned": len(values),
            "data_trust": SOURCE_RESOLUTION_DATA_TRUST,
        }

    def resolve_reference(
        self,
        *,
        actor: DelegatedActor,
        resolution_ref: str,
    ) -> dict[str, Any]:
        """Project one valid same-actor reference to an existing planner input."""

        if _RESOLUTION_REF_RE.fullmatch(str(resolution_ref or "")) is None:
            raise SourceResolutionError(
                "not_found", "source resolution not found", status_code=404
            )
        row = self.store.get_agent_source_resolution_for_actor(
            resolution_ref,
            workspace_id=actor.workspace_id,
            user_id=actor.user_id,
            delegation_id=actor.delegation_id,
        )
        if row is None:
            raise SourceResolutionError(
                "not_found", "source resolution not found", status_code=404
            )
        if str(row.get("expires_at") or "") <= (
            self.store.authoritative_agent_proposal_time().isoformat()
        ):
            raise SourceResolutionError(
                "source_resolution_expired",
                "source resolution expired",
                status_code=410,
            )
        envelope = row.get("envelope")
        source = envelope.get("source") if isinstance(envelope, dict) else None
        source_type = str(row.get("source_type") or "")
        try:
            if not isinstance(source, dict):
                raise ValueError("missing source envelope")
            if source.get("mode") == "existing":
                if set(source) != {"mode", "source_id"}:
                    raise ValueError("invalid existing source envelope")
                existing = self.store.get_source(str(source["source_id"]))
                if (
                    existing is None
                    or not self._visible(existing, actor)
                    or not catalog_source_matches_agent_type(
                        source_type, existing
                    )
                ):
                    raise SourceResolutionError(
                        "not_found",
                        "source resolution not found",
                        status_code=404,
                    )
                key = source_key(
                    str(existing["type"]),
                    dict(existing.get("config") or {}),
                )
            elif source.get("mode") == "private":
                if set(source) != {
                    "mode",
                    "type",
                    "display_name",
                    "config",
                } or source.get("type") != source_type:
                    raise ValueError("invalid private source envelope")
                setup = normalize_source_setup_input(
                    source_type, dict(source.get("config") or {})
                )
                key = source_key(
                    str(setup["catalog_source_type"]),
                    dict(setup["config"]),
                )
            else:
                raise ValueError("invalid source envelope mode")
            if (
                self._fingerprint(f"{source_type}\0{key}")
                != row.get("source_fingerprint")
            ):
                raise ValueError("source resolution identity mismatch")
        except SourceResolutionError:
            raise
        except (KeyError, TypeError, ValueError, SourceConfigError) as exc:
            raise SourceResolutionError(
                "invalid_source_resolution",
                "source resolution is invalid",
                status_code=409,
            ) from exc
        return dict(source)
