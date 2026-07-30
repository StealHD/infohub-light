"""Structured values returned by service-safe feed production runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ..models import ContentItem


RunStatus = Literal["succeeded", "partial", "failed"]
SourceStatus = Literal["succeeded", "failed"]


@dataclass(frozen=True, slots=True)
class SourceAvatarHint:
    """Internal source-level media evidence omitted from public diagnostics."""

    source_id: str
    remote_url: str = field(repr=False)
    origin: str
    kind: Literal["image", "page"] = "image"


@dataclass(frozen=True, slots=True)
class AnalysisUsage:
    """Token-saving execution counts safe to expose in job diagnostics."""

    item_count: int = 0
    cache_hits: int = 0
    ai_calls: int = 0
    provider_attempts: int = 0
    fallbacks: int = 0
    skipped: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "item_count": max(int(self.item_count), 0),
            "cache_hits": max(int(self.cache_hits), 0),
            "ai_calls": max(int(self.ai_calls), 0),
            "provider_attempts": max(int(self.provider_attempts), 0),
            "fallbacks": max(int(self.fallbacks), 0),
            "skipped": max(int(self.skipped), 0),
        }


@dataclass(frozen=True, slots=True)
class AcquisitionUsage:
    """Shared-acquisition counts safe to expose in job diagnostics."""

    cache_hits: int = 0
    cache_misses: int = 0
    upstream_attempts: int = 0
    waits: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "cache_hits": max(int(self.cache_hits), 0),
            "cache_misses": max(int(self.cache_misses), 0),
            "upstream_attempts": max(int(self.upstream_attempts), 0),
            "waits": max(int(self.waits), 0),
        }


@dataclass(frozen=True, slots=True)
class RunIssue:
    """One structured issue encountered during a feed run."""

    stage: str
    code: str
    message: str
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class SourceOutcome:
    """Fetch outcome for one source participating in a feed run."""

    source_id: str
    subscription_id: str | None
    source_key: str
    analysis_mode: str
    status: SourceStatus
    fetched_count: int
    issue: RunIssue | None = None
    catalog_type: str = ""
    capture_status: Literal["captured", "empty", "cached", "unavailable"] = "unavailable"
    upstream_schema: dict[str, Any] | None = None
    normalized_schema: dict[str, Any] | None = None
    avatar_hints: tuple[SourceAvatarHint, ...] = field(
        default=(),
        repr=False,
    )


@dataclass(frozen=True, slots=True)
class FeedRunResult:
    """Immutable structured output from a service-safe feed run."""

    schema_version: int = field(default=2, init=False)
    run_id: str
    status: RunStatus
    started_at: str
    finished_at: str
    items: tuple[ContentItem, ...] = ()
    featured_item_ids: tuple[str, ...] = ()
    daily_push_item_ids: tuple[str, ...] = ()
    source_outcomes: tuple[SourceOutcome, ...] = ()
    issues: tuple[RunIssue, ...] = ()
    analysis_usage: AnalysisUsage = field(default_factory=AnalysisUsage)
    acquisition_usage: AcquisitionUsage = field(default_factory=AcquisitionUsage)


def safe_issue(issue: RunIssue | None) -> dict[str, Any] | None:
    """Return the bounded public representation of one run issue."""
    if issue is None:
        return None
    from .source_health import sanitize_issue_message

    return {
        "stage": issue.stage,
        "code": issue.code,
        "message": sanitize_issue_message(issue.message),
        "retryable": bool(issue.retryable),
    }


def safe_source_outcome(outcome: SourceOutcome) -> dict[str, Any]:
    """Return source provenance and status without configuration or secrets."""
    from .source_health import sanitize_issue_message

    return {
        "source_id": outcome.source_id,
        "subscription_id": outcome.subscription_id,
        "source_key": sanitize_issue_message(outcome.source_key),
        "analysis_mode": outcome.analysis_mode,
        "status": outcome.status,
        "fetched_count": int(outcome.fetched_count),
        "issue": safe_issue(outcome.issue),
    }


def safe_run_diagnostics(
    result: FeedRunResult,
    *,
    item_count: int,
) -> dict[str, Any]:
    """Build the shared safe diagnostic shape for jobs and snapshots."""
    from .response_schema import bound_source_response_schemas

    response_schemas = bound_source_response_schemas(
        {
            "source_id": outcome.source_id,
            "catalog_type": outcome.catalog_type,
            "capture_status": outcome.capture_status,
            "upstream": outcome.upstream_schema
            or {"root_type": "null", "fields": [], "truncated": False},
            "normalized": outcome.normalized_schema
            or {"root_type": "array", "fields": [], "truncated": False},
        }
        for outcome in result.source_outcomes
    )
    return {
        "run_id": result.run_id,
        "run_status": result.status,
        "item_count": max(int(item_count), 0),
        "source_outcomes": [
            safe_source_outcome(outcome) for outcome in result.source_outcomes
        ],
        "issues": [safe_issue(issue) for issue in result.issues],
        "analysis_usage": result.analysis_usage.as_dict(),
        "acquisition_usage": result.acquisition_usage.as_dict(),
        "response_schemas": response_schemas,
    }
