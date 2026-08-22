"""Apify Store metadata adapter for v2 Discovery; never executes an Actor."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from .discovery import DiscoveryCatalogError
from .ports import DiscoveryRevision, ProbePreflightResult
from .store_metadata import StoreMetadata, estimated_run_price, normalize_store_metadata


class ApifyStoreMetadata(Protocol):
    async def search_store(self, query: str) -> Sequence[Mapping[str, Any]]: ...

    async def get_actor(self, actor_id: str) -> Mapping[str, Any]: ...

    async def get_build(self, build_id: str) -> Mapping[str, Any]: ...


class ApifyStoreRestClient:
    """Bounded public Store client used only by the v2 catalog.

    This transport deliberately exposes metadata reads only: it cannot start
    an Actor and never puts its bearer token in a URL.
    """

    def __init__(
        self,
        token: str,
        *,
        base_url: str = "https://api.apify.com/v2",
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        if not str(token).strip():
            raise ValueError("Apify token is required")
        self._token = str(token).strip()
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._timeout = timeout_seconds

    async def search_store(self, query: str) -> Sequence[Mapping[str, Any]]:
        payload = await self._get(
            "/store",
            params={
                "search": query,
                "limit": 20,
                "offset": 0,
                "responseFormat": "agent",
                "includeUnrunnableActors": False,
            },
        )
        data = _unwrap(payload)
        rows = data.get("items") if isinstance(data, Mapping) else None
        if rows is None and isinstance(data, Sequence) and not isinstance(data, str):
            rows = data
        return tuple(row for row in (rows or ()) if isinstance(row, Mapping))

    async def get_actor(self, actor_id: str) -> Mapping[str, Any]:
        return _unwrap(
            await self._get(
                f"/actors/{quote(actor_id.replace('/', '~'), safe='~')}"
            )
        )

    async def get_build(self, build_id: str) -> Mapping[str, Any]:
        return _unwrap(await self._get(f"/actor-builds/{quote(build_id, safe='')}"))

    async def _get(
        self, path: str, *, params: Mapping[str, Any] | None = None
    ) -> Mapping[str, Any]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self._timeout, trust_env=False
        )
        try:
            for attempt in range(3):
                try:
                    response = await client.get(
                        f"{self._base_url}{path}",
                        params=dict(params or {}),
                        headers={
                            "Authorization": f"Bearer {self._token}",
                            "Accept": "application/json",
                            "Accept-Encoding": "identity",
                        },
                    )
                    response.raise_for_status()
                    if len(response.content) > 2 * 1024 * 1024:
                        raise DiscoveryCatalogError(
                            "actorops_discovery_catalog_response_too_large",
                            retryable=False,
                        )
                    payload = response.json()
                    if not isinstance(payload, Mapping):
                        raise DiscoveryCatalogError(
                            "actorops_discovery_catalog_invalid", retryable=True
                        )
                    return payload
                except DiscoveryCatalogError:
                    raise
                except httpx.HTTPStatusError as error:
                    status = int(error.response.status_code)
                    if (status == 429 or status >= 500) and attempt < 2:
                        await _retry_catalog_request(attempt, error.response)
                        continue
                    code = (
                        "actorops_discovery_catalog_not_found"
                        if status in {404, 410}
                        else "actorops_discovery_catalog_unavailable"
                    )
                    raise DiscoveryCatalogError(
                        code, retryable=status == 429 or status >= 500
                    ) from None
                except (httpx.HTTPError, ValueError):
                    if attempt < 2:
                        await _retry_catalog_request(attempt)
                        continue
                    raise DiscoveryCatalogError(
                        "actorops_discovery_catalog_unavailable", retryable=True
                    ) from None
            raise AssertionError("unreachable")
        finally:
            if owns_client:
                await client.aclose()


async def _retry_catalog_request(
    attempt: int, response: httpx.Response | None = None
) -> None:
    retry_after = response.headers.get("Retry-After") if response else None
    try:
        delay = float(retry_after) if retry_after else float(2**attempt)
    except (TypeError, ValueError):
        delay = float(2**attempt)
    import asyncio

    await asyncio.sleep(min(max(delay, 0.0), 30.0))


def _unwrap(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    data = payload.get("data")
    return data if isinstance(data, Mapping) else payload


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

    async def store_metadata(self, candidate: object) -> StoreMetadata:
        """Read and normalize a public Store card; never expose raw provider JSON."""

        actor_id = str(getattr(candidate, "actor_id", "")).strip()
        if not actor_id:
            raise DiscoveryCatalogError("actorops_store_metadata_actor_invalid", retryable=False)
        try:
            actor = await self.metadata.get_actor(actor_id)
        except Exception as error:
            raise _catalog_error(error) from error
        return normalize_store_metadata(
            actor, fallback_slug=actor_id, fallback_name=str(getattr(candidate, "publisher", "")),
        )


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
    input_schema = _schema(build.get("inputSchema"))
    output_schema = _schema(build.get("datasetSchema") or build.get("outputSchema"))
    if not input_schema:
        input_schema = _schema(definition.get("input"))
    if not output_schema:
        storages = definition.get("storages")
        dataset = storages.get("dataset") if isinstance(storages, Mapping) else None
        fields = dataset.get("fields") if isinstance(dataset, Mapping) else None
        output_schema = _schema(fields)
    if not output_schema:
        output_schema = _schema(definition.get("output"))
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


def _schema(value: object) -> Mapping[str, object]:
    schema = _mapping(value)
    return schema if isinstance(schema.get("properties"), Mapping) else {}


def _price(actor: Mapping[str, Any]) -> float | None:
    return estimated_run_price(actor.get("pricingInfos"))


def _schema_hash(value: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = ["ApifyDiscoveryCatalog", "ApifyStoreRestClient"]
