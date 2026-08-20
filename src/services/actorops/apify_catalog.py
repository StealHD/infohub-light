"""Apify Store metadata adapter for v2 Discovery; never executes an Actor."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from .discovery import DiscoveryCatalogError
from .ports import DiscoveryRevision, ProbePreflightResult


class ApifyStoreMetadata(Protocol):
    async def search_store(self, query: str) -> Sequence[Mapping[str, Any]]: ...

    async def get_actor(self, actor_id: str) -> Mapping[str, Any]: ...

    async def get_build(self, build_id: str) -> Mapping[str, Any]: ...


class ApifyDiscoveryCatalog:
    """Translate only public Actor/Build facts into the generic Catalog port."""

    def __init__(self, metadata: ApifyStoreMetadata) -> None:
        self.metadata = metadata

    async def search(self, query: str) -> tuple[str, ...]:
        try:
            rows = await self.metadata.search_store(query)
        except Exception as error:
            raise _catalog_error(error) from error
        values = []
        for row in rows:
            actor_id = _actor_id(row)
            if actor_id and actor_id not in values:
                values.append(actor_id)
        return tuple(values)

    async def get_revision(self, actor_id: str) -> DiscoveryRevision:
        try:
            actor = await self.metadata.get_actor(actor_id)
            build_id, build_number = _tagged_build(actor)
            if not build_id or not build_number:
                raise DiscoveryCatalogError("actorops_discovery_exact_build_missing", retryable=False)
            build = await self.metadata.get_build(build_id)
        except DiscoveryCatalogError:
            raise
        except Exception as error:
            raise _catalog_error(error) from error
        input_schema, output_schema = _schemas(build)
        publisher = str(
            actor.get("username") or actor.get("userUsername") or actor_id.split("/", 1)[0]
        ).strip().casefold()
        if not publisher:
            raise DiscoveryCatalogError("actorops_discovery_publisher_invalid", retryable=False)
        return DiscoveryRevision(
            actor_id=actor_id,
            publisher=publisher,
            build_id=build_id,
            build_number=build_number,
            price_per_run_usd=_price(actor),
            input_schema=input_schema,
            output_schema=output_schema,
        )

    async def verify_candidate(
        self, candidate: object, *, max_charge_usd: float
    ) -> ProbePreflightResult:
        """Free, exact revision proof for a maintenance Probe."""

        actor_id = str(getattr(candidate, "actor_id", ""))
        try:
            actor = await self.metadata.get_actor(actor_id)
            revision = await self.get_revision(actor_id)
        except DiscoveryCatalogError as error:
            return ProbePreflightResult(False, error.code)
        except Exception:
            return ProbePreflightResult(False, "actorops_maintenance_preflight_unavailable")
        if any(actor.get(key) is True for key in ("isDeprecated", "isDisabled")) or actor.get("isPublic") is False:
            return ProbePreflightResult(False, "actorops_maintenance_actor_unavailable")
        if (
            revision.publisher != str(getattr(candidate, "publisher", ""))
            or revision.build_id != str(getattr(candidate, "build_id", ""))
            or revision.build_number != str(getattr(candidate, "build_number", ""))
            or _schema_hash(revision.input_schema) != str(getattr(candidate, "input_schema_hash", ""))
            or _schema_hash(revision.output_schema) != str(getattr(candidate, "output_schema_hash", ""))
            or revision.price_per_run_usd is None
            or revision.price_per_run_usd > float(max_charge_usd)
        ):
            return ProbePreflightResult(False, "actorops_maintenance_revision_changed")
        return ProbePreflightResult(True)


def _catalog_error(error: Exception) -> DiscoveryCatalogError:
    code = str(getattr(error, "code", "actorops_discovery_catalog_unavailable"))
    return DiscoveryCatalogError(code[:96], retryable=bool(getattr(error, "retryable", True)))


def _actor_id(value: Mapping[str, Any]) -> str | None:
    raw = str(value.get("actorId") or value.get("id") or "").strip().replace("~", "/")
    if not raw:
        username = str(value.get("username") or value.get("userUsername") or "").strip()
        name = str(value.get("name") or value.get("actorName") or "").strip()
        raw = f"{username}/{name}" if username and name else ""
    return raw if raw and len(raw) <= 127 and all(part for part in raw.split("/")) else None


def _tagged_build(actor: Mapping[str, Any]) -> tuple[str, str]:
    tagged = actor.get("taggedBuilds")
    preferred = tagged.get("latest") if isinstance(tagged, Mapping) else None
    if not isinstance(preferred, Mapping):
        return "", ""
    return (
        str(preferred.get("buildId") or preferred.get("id") or "").strip(),
        str(preferred.get("buildNumber") or preferred.get("number") or "").strip(),
    )


def _schemas(build: Mapping[str, Any]) -> tuple[Mapping[str, object], Mapping[str, object]]:
    definition = build.get("actorDefinition")
    definition = definition if isinstance(definition, Mapping) else {}
    input_schema = _mapping(build.get("inputSchema"))
    output_schema = _mapping(build.get("datasetSchema") or build.get("outputSchema"))
    if not input_schema:
        input_schema = _mapping(definition.get("input"))
    if not output_schema:
        storages = definition.get("storages")
        output_schema = _mapping(storages.get("dataset") if isinstance(storages, Mapping) else None)
    return input_schema, output_schema


def _mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        nested = value.get("schema")
        return _mapping(nested) if isinstance(nested, (Mapping, str)) else value
    if not isinstance(value, str) or len(value.encode("utf-8")) > 64 * 1024:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, Mapping) else {}


def _price(actor: Mapping[str, Any]) -> float | None:
    infos = actor.get("pricingInfos")
    rows = infos if isinstance(infos, Sequence) and not isinstance(infos, str) else ()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        for key in ("minimumChargeUsd", "minChargeUsd", "pricePerRunUsd", "pricePerUnitUsd"):
            value = row.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
                return float(value)
    return None


def _schema_hash(value: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = ["ApifyDiscoveryCatalog"]
