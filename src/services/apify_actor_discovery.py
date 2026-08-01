"""Safe Actor discovery and declarative adapter proposal workflow.

Discovery is intentionally proposal-only: it searches public Store metadata,
applies deterministic filters, asks AI for bounded JSON manifests, validates
those manifests against fetched identities and exact Builds, and stops at
``awaiting_canary_approval``.  It never starts a paid Actor Run.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Mapping, Protocol, Sequence, TypeVar
from urllib.parse import quote

import httpx

from .apify_actor_manifest import (
    ActorManifestError,
    ActorRuntime,
    ActorTarget,
    parse_actor_manifest,
    render_actor_input,
)
from .apify_actor_ops import ActorOpsError, ApifyActorOpsService


logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

MAX_DISCOVERY_QUERIES = 3
MAX_STORE_RESULTS_PER_QUERY = 20
MIN_AI_PROPOSALS = 3
MAX_AI_PROPOSALS = 6
MAX_METADATA_RESPONSE_BYTES = 2 * 1024 * 1024
_PLATFORM_HOSTS = {
    "x": frozenset({"x.com", "twitter.com"}),
    "youtube": frozenset({"youtube.com", "youtu.be"}),
    "instagram": frozenset({"instagram.com"}),
}
_FATAL_INPUT_VALIDATION_ERRORS = frozenset(
    {
        "apify_actor_metadata_authentication_failed",
        "actor_input_validation_contract_error",
    }
)
T = TypeVar("T")


class ActorDiscoveryError(ActorOpsError):
    pass


class ActorMetadataClient(Protocol):
    async def search_store(self, query: str) -> Sequence[Mapping[str, Any]]: ...

    async def get_actor(self, actor_id: str) -> Mapping[str, Any]: ...

    async def get_build(self, build_id: str) -> Mapping[str, Any]: ...

    async def validate_input(
        self,
        actor_id: str,
        build_number: str,
        actor_input: Mapping[str, Any],
    ) -> bool: ...


class ApifyStoreRestClient:
    """Minimal official REST client; bearer tokens never enter request URLs."""

    def __init__(
        self,
        token: str,
        *,
        base_url: str = "https://api.apify.com/v2",
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 20.0,
        retry_base_delay: float = 1.0,
    ) -> None:
        if not str(token).strip():
            raise ValueError("Apify token is required")
        self._token = str(token).strip()
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._timeout = timeout_seconds
        self._retry_base_delay = retry_base_delay

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        }

    @staticmethod
    def _operation(path: str) -> str:
        return "input_validation" if path.endswith("/validate-input") else "metadata"

    @staticmethod
    def _http_error(path: str, status_code: int) -> ActorDiscoveryError:
        input_validation = path.endswith("/validate-input")
        if status_code == 401:
            return ActorDiscoveryError(
                "apify_actor_metadata_authentication_failed",
                "Apify metadata authentication failed",
                retryable=False,
                status_code=401,
            )
        if input_validation:
            if status_code == 400:
                code = "actor_input_validation_rejected"
                message = "Actor input validation rejected the rendered input"
            elif status_code == 403:
                code = "actor_input_validation_forbidden"
                message = "Actor input validation is not permitted"
            elif status_code in {404, 410}:
                code = "actor_input_validation_target_unavailable"
                message = "Actor or Build input validation target is unavailable"
            elif status_code == 429 or status_code >= 500:
                code = "actor_input_validation_unavailable"
                message = "Actor input validation is temporarily unavailable"
            else:
                code = "actor_input_validation_contract_error"
                message = "Actor input validation request contract was rejected"
            return ActorDiscoveryError(
                code,
                message,
                retryable=(status_code == 429 or status_code >= 500),
                status_code=status_code,
            )
        if status_code in {404, 410}:
            return ActorDiscoveryError(
                "apify_actor_metadata_not_found",
                "Apify Actor or Build metadata was not found",
                retryable=False,
                status_code=404,
            )
        return ActorDiscoveryError(
            "apify_actor_metadata_unavailable",
            "Apify metadata is unavailable",
            retryable=(status_code == 429 or status_code >= 500),
            status_code=502,
        )

    async def _retry_delay(
        self,
        attempt: int,
        *,
        response: httpx.Response | None = None,
    ) -> None:
        retry_after = response.headers.get("Retry-After") if response else None
        try:
            delay = (
                float(retry_after)
                if retry_after
                else self._retry_base_delay * (2**attempt)
            )
        except ValueError:
            delay = self._retry_base_delay * (2**attempt)
        await asyncio.sleep(min(max(delay, 0.0), 30.0))

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self._timeout,
            trust_env=False,
        )
        request_method = str(method).upper()
        operation = self._operation(path)
        retryable_operation = request_method == "GET" or operation == "input_validation"
        try:
            for attempt in range(3):
                try:
                    async with client.stream(
                        request_method,
                        f"{self._base_url}{path}",
                        params=dict(params or {}),
                        json=dict(json_body) if json_body is not None else None,
                        headers=self._headers(),
                    ) as response:
                        response.raise_for_status()
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > MAX_METADATA_RESPONSE_BYTES:
                                raise ActorDiscoveryError(
                                    "apify_actor_metadata_too_large",
                                    "Apify metadata response exceeds the safety limit",
                                    retryable=False,
                                    status_code=502,
                                )
                    payload = json.loads(bytes(body))
                    if not isinstance(payload, Mapping):
                        raise ActorDiscoveryError(
                            "apify_actor_metadata_invalid",
                            "Apify metadata response is invalid",
                            retryable=True,
                            status_code=502,
                        )
                    return payload
                except httpx.HTTPStatusError as error:
                    status_code = int(error.response.status_code)
                    if (
                        retryable_operation
                        and (status_code == 429 or status_code >= 500)
                        and attempt < 2
                    ):
                        logger.warning(
                            "Apify discovery request retrying operation=%s status=%d attempt=%d",
                            operation,
                            status_code,
                            attempt + 1,
                        )
                        await self._retry_delay(
                            attempt,
                            response=error.response,
                        )
                        continue
                    raise self._http_error(path, status_code) from None
                except ActorDiscoveryError as error:
                    if retryable_operation and error.retryable and attempt < 2:
                        logger.warning(
                            "Apify discovery request retrying operation=%s category=payload attempt=%d",
                            operation,
                            attempt + 1,
                        )
                        await self._retry_delay(attempt)
                        continue
                    raise
                except (httpx.HTTPError, ValueError) as error:
                    if retryable_operation and attempt < 2:
                        logger.warning(
                            "Apify discovery request retrying operation=%s category=%s attempt=%d",
                            operation,
                            (
                                "decoding"
                                if isinstance(error, httpx.DecodingError)
                                else "transport_or_payload"
                            ),
                            attempt + 1,
                        )
                        await self._retry_delay(attempt)
                        continue
                    code = (
                        "actor_input_validation_unavailable"
                        if operation == "input_validation"
                        else "apify_actor_metadata_unavailable"
                    )
                    raise ActorDiscoveryError(
                        code,
                        (
                            "Actor input validation is temporarily unavailable"
                            if operation == "input_validation"
                            else "Apify metadata is unavailable"
                        ),
                        retryable=True,
                        status_code=502,
                    ) from None
            raise RuntimeError("Apify discovery request produced no response")
        finally:
            if owns_client:
                await client.aclose()

    async def search_store(self, query: str) -> Sequence[Mapping[str, Any]]:
        payload = await self._request(
            "GET",
            "/store",
            params={
                "search": query,
                "limit": MAX_STORE_RESULTS_PER_QUERY,
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
        payload = await self._request(
            "GET",
            f"/actors/{quote(actor_id.replace('/', '~'), safe='~')}",
        )
        return _unwrap(payload)

    async def get_build(self, build_id: str) -> Mapping[str, Any]:
        payload = await self._request(
            "GET",
            f"/actor-builds/{quote(build_id, safe='')}",
        )
        return _unwrap(payload)

    async def validate_input(
        self,
        actor_id: str,
        build_number: str,
        actor_input: Mapping[str, Any],
    ) -> bool:
        payload = await self._request(
            "POST",
            f"/actors/{quote(actor_id.replace('/', '~'), safe='~')}/validate-input",
            params={"build": build_number},
            json_body=actor_input,
        )
        data = _unwrap(payload)
        return bool(data.get("valid")) if isinstance(data, Mapping) else False


@dataclass(frozen=True, slots=True)
class DiscoveryCandidate:
    actor_id: str
    publisher: str
    build_id: str
    build_number: str
    actor: Mapping[str, Any]
    build: Mapping[str, Any]
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    pricing: Mapping[str, Any]
    input_template: Mapping[str, Any]

    def ai_summary(self) -> dict[str, Any]:
        """Safe metadata only: no README, credentials, or example row values."""

        return {
            "actor_id": self.actor_id,
            "publisher": self.publisher,
            "build_id": self.build_id,
            "build_number": self.build_number,
            "input_schema": _schema_shape(self.input_schema),
            "output_schema": _schema_shape(self.output_schema),
            "pricing": _safe_pricing_summary(self.pricing),
            "input_template": dict(self.input_template),
        }


@dataclass(frozen=True, slots=True)
class DiscoveryOutcome:
    run_id: str
    route_id: str
    stage: str
    revision_ids: tuple[str, ...]
    rejected: tuple[dict[str, str], ...]


class ApifyActorDiscoveryService:
    def __init__(
        self,
        ops: ApifyActorOpsService,
        metadata_client: ActorMetadataClient,
        ai_generate: Callable[
            [Mapping[str, Any]],
            Mapping[str, Any] | Awaitable[Mapping[str, Any]],
        ],
        *,
        ai_provider: str | None = None,
        ai_model: str | None = None,
    ) -> None:
        self.ops = ops
        self.metadata_client = metadata_client
        self.ai_generate = ai_generate
        self.ai_provider = ai_provider
        self.ai_model = ai_model

    async def run_discovery(
        self,
        run_id: str,
        *,
        queries: Sequence[str],
    ) -> DiscoveryOutcome:
        run = self.ops.get_discovery_run(run_id)
        if run["stage"] != "queued":
            raise ActorDiscoveryError(
                "apify_actor_discovery_not_queued",
                "Actor discovery run is not queued",
            )
        settings = self.ops.get_discovery_settings()
        if not settings["enabled"]:
            self.ops.update_discovery_run(
                run_id,
                expected_stage="queued",
                stage="blocked_ai_unavailable",
                error_code="discovery_ai_disabled",
            )
            return DiscoveryOutcome(
                run_id,
                str(run["route_id"]),
                "blocked_ai_unavailable",
                (),
                (),
            )
        clean_queries: list[str] = []
        for raw in queries:
            query = " ".join(str(raw).split())
            if query and len(query) <= 160 and query not in clean_queries:
                clean_queries.append(query)
            if len(clean_queries) >= min(
                MAX_DISCOVERY_QUERIES,
                int(settings["call_limit"]),
            ):
                break
        if not clean_queries:
            raise ActorDiscoveryError(
                "apify_actor_discovery_query_invalid",
                "Actor discovery requires at least one bounded query",
                status_code=422,
            )
        self.ops.update_discovery_run(
            run_id,
            expected_stage="queued",
            stage="searching",
            query_count=len(clean_queries),
        )
        route = self.ops.get_route(str(run["route_id"]))
        store_hits: dict[str, Mapping[str, Any]] = {}
        for query in clean_queries:
            for row in await _maybe_await(self.metadata_client.search_store(query)):
                actor_id = _actor_id(row)
                if actor_id and actor_id not in store_hits:
                    store_hits[actor_id] = row
        self.ops.update_discovery_run(
            run_id,
            expected_stage="searching",
            stage="metadata",
            query_count=len(clean_queries),
        )
        accepted: list[DiscoveryCandidate] = []
        rejected: list[dict[str, str]] = []
        for actor_id in sorted(store_hits):
            try:
                candidate = await self._load_candidate(
                    actor_id,
                    per_run_cap_usd=float(route["per_run_cap_usd"]),
                )
            except ActorDiscoveryError as error:
                if error.code == "apify_actor_metadata_authentication_failed":
                    raise
                rejected.append({"actor_id": actor_id, "reason": error.code})
                continue
            accepted.append(candidate)
        accepted = accepted[: int(settings["max_candidates"])]
        if len(accepted) < 3 or len({row.publisher for row in accepted}) < 2:
            self.ops.update_discovery_run(
                run_id,
                expected_stage="metadata",
                stage="candidate_shortfall",
                error_code="candidate_shortfall",
                candidate_count=len(accepted),
                rejections=tuple(rejected),
            )
            return DiscoveryOutcome(
                run_id,
                str(run["route_id"]),
                "candidate_shortfall",
                (),
                tuple(rejected),
            )
        self.ops.update_discovery_run(
            run_id,
            expected_stage="metadata",
            stage="ranking",
        )
        proposal_target = min(MAX_AI_PROPOSALS, len(accepted))
        identity_example = {
            "output_field": "author_handle",
            "target_ref": "target.handle",
            "match": "handle",
        }
        prompt = {
            "task": "rank_candidates_and_generate_manifest_v1",
            "route": {
                "platform": route["platform"],
                "target_type": route["target_type"],
                "capability": route["capability"],
                "allowed_output_hosts": sorted(
                    _PLATFORM_HOSTS.get(str(route["platform"]), frozenset())
                ),
            },
            "constraints": {
                "min_proposals": MIN_AI_PROPOSALS,
                "target_proposals": proposal_target,
                "max_proposals": proposal_target,
                "required_proposals": proposal_target,
                "min_distinct_publishers": 2,
                "one_proposal_per_actor": True,
                "proposals_ranked_best_first": True,
                "actor_and_build_must_match_candidates": True,
                "code_or_templates_forbidden": True,
                "response_must_be_exact_json_object": True,
            },
            "response_contract": {
                "type": "object",
                "required": ["proposals"],
                "additional_properties": False,
                "properties": {
                    "proposals": {
                        "type": "array",
                        "min_items": proposal_target,
                        "max_items": proposal_target,
                        "items": {
                        "actor_id": "must_equal_candidate.actor_id",
                        "build_id": "must_equal_candidate.build_id",
                        "build_number": "must_equal_candidate.build_number",
                        "manifest": {
                            "version": 1,
                            "actor_id": "must_equal_candidate.actor_id",
                            "build_number": "must_equal_candidate.build_number",
                            "input": "must_equal_candidate.input_template",
                            "output": {
                                "native_id": {
                                    "pointers": ["/candidate/id"],
                                    "transforms": ["to_string"],
                                },
                                "url": {
                                    "pointers": ["/candidate/url"],
                                    "transforms": ["normalize_url"],
                                },
                                "published_at": {
                                    "pointers": ["/candidate/date"],
                                    "transforms": ["parse_datetime"],
                                },
                                "text": {
                                    "pointers": ["/candidate/text"],
                                    "transforms": ["strip_html"],
                                },
                                "author_handle": {
                                    "pointers": ["/candidate/ownerUsername"],
                                    "transforms": ["to_string"],
                                },
                            },
                            "semantics": {
                                "identity": identity_example,
                                "url_host_allowlist": [
                                    "must_use_route_allowed_output_host"
                                ],
                                "empty_result_markers": [],
                            },
                        },
                        },
                    },
                },
                "notes": [
                    "Return exactly target_proposals distinct Actors.",
                    "Use at least two distinct candidate publishers across the proposals.",
                    "Rank proposals best-first so later entries can replace an invalid earlier entry.",
                    "Replace candidate placeholders with fetched schema paths only.",
                    "Copy candidate.input_template exactly into manifest.input.",
                    "input values are JSON literals or one exact $ref object.",
                    "output paths are RFC 6901 JSON Pointers.",
                    "allowed transforms: pick_first,to_string,to_integer,to_number,to_boolean,parse_datetime,normalize_url,strip_html.",
                    "native_id,url,published_at and title or text are required.",
                    "For profile/channel items, prove identity with an author/owner handle or source id from each content row.",
                    "The content item url is not the source profile/channel url and must never be reused as source_url identity.",
                    "Reject profile metadata-only Dataset schemas for the items capability.",
                ],
            },
            "candidates": [candidate.ai_summary() for candidate in accepted],
        }
        try:
            ai_result = await _maybe_await(self.ai_generate(prompt))
        except Exception as error:
            error_code = str(
                getattr(error, "code", "discovery_ai_unavailable")
            )[:128]
            self.ops.update_discovery_run(
                run_id,
                expected_stage="ranking",
                stage="blocked_ai_unavailable",
                error_code=error_code,
                candidate_count=len(accepted),
                rejections=tuple(rejected),
                failure_phase="ai_generation",
            )
            return DiscoveryOutcome(
                run_id,
                str(run["route_id"]),
                "blocked_ai_unavailable",
                (),
                tuple(rejected),
            )
        self.ops.update_discovery_run(
            run_id,
            expected_stage="ranking",
            stage="static_validation",
        )
        by_identity = {
            (candidate.actor_id, candidate.build_id, candidate.build_number): candidate
            for candidate in accepted
        }
        proposals = ai_result.get("proposals") if isinstance(ai_result, Mapping) else None
        if (
            not isinstance(proposals, Sequence)
            or isinstance(proposals, (str, bytes, bytearray))
        ):
            proposals = ()
        bounded_proposals = proposals[:proposal_target]
        if len(bounded_proposals) < proposal_target:
            rejected.extend(
                {
                    "actor_id": "ai-response",
                    "reason": "ai_proposal_shortfall",
                }
                for _ in range(proposal_target - len(bounded_proposals))
            )
        validated: list[tuple[DiscoveryCandidate, Any]] = []
        seen_actors: set[str] = set()
        for raw in bounded_proposals:
            if not isinstance(raw, Mapping):
                rejected.append(
                    {
                        "actor_id": "ai-response",
                        "reason": "ai_proposal_contract_invalid",
                    }
                )
                continue
            identity = (
                str(raw.get("actor_id") or "").replace("~", "/"),
                str(raw.get("build_id") or ""),
                str(raw.get("build_number") or ""),
            )
            candidate = by_identity.get(identity)
            if candidate is None or candidate.actor_id in seen_actors:
                rejected.append(
                    {
                        "actor_id": identity[0] or "unknown",
                        "reason": "ai_identity_not_fetched",
                    }
                )
                continue
            try:
                ai_manifest = parse_actor_manifest(raw.get("manifest"))
                if (
                    ai_manifest.actor_id != candidate.actor_id
                    or ai_manifest.build_number != candidate.build_number
                ):
                    raise ActorManifestError(
                        "apify_manifest_identity_mismatch",
                        "Manifest identity mismatch",
                    )
                normalized_manifest = ai_manifest.model_dump(
                    mode="json",
                    by_alias=True,
                    exclude_none=True,
                )
                normalized_manifest["input"] = dict(candidate.input_template)
                manifest = parse_actor_manifest(normalized_manifest)
                _validate_manifest_hosts(manifest, str(route["platform"]))
                _validate_manifest_output_schema(
                    manifest,
                    candidate.output_schema,
                )
                _validate_manifest_route_identity(
                    manifest,
                    target_type=str(route["target_type"]),
                    capability=str(route["capability"]),
                )
            except ActorManifestError as error:
                rejected.append(
                    {"actor_id": candidate.actor_id, "reason": error.code}
                )
                continue
            validated.append((candidate, manifest))
            seen_actors.add(candidate.actor_id)
        static_publishers = {row.publisher for row, _ in validated}
        static_pool_complete = (
            len(validated) >= MIN_AI_PROPOSALS
            and len(static_publishers) >= 2
        )
        self.ops.update_discovery_run(
            run_id,
            expected_stage="static_validation",
            stage="input_validation",
        )
        self.ops.record_discovery_ai_metrics(
            run_id,
            manifest_status="valid" if static_pool_complete else "invalid",
        )
        revisions: list[str] = []
        revision_publishers: set[str] = set()
        for candidate, manifest in validated:
            rendered = render_actor_input(
                manifest,
                _reference_target(str(route["platform"])),
                ActorRuntime(max_items=1),
            )
            try:
                is_valid = await _maybe_await(
                    self.metadata_client.validate_input(
                        candidate.actor_id,
                        candidate.build_number,
                        rendered,
                    )
                )
            except ActorDiscoveryError as error:
                if error.code in _FATAL_INPUT_VALIDATION_ERRORS:
                    raise
                rejected.append(
                    {
                        "actor_id": candidate.actor_id,
                        "reason": error.code,
                    }
                )
                continue
            if not is_valid:
                rejected.append(
                    {
                        "actor_id": candidate.actor_id,
                        "reason": "build_input_validation_failed",
                    }
                )
                continue
            candidate_id = self.ops.ensure_candidate(
                str(run["route_id"]),
                actor_id=candidate.actor_id,
                display_name=candidate.actor_id,
            )
            revision_id = self.ops.create_adapter_revision(
                candidate_id=candidate_id,
                actor_id=candidate.actor_id,
                publisher=candidate.publisher,
                build_id=candidate.build_id,
                build_number=candidate.build_number,
                manifest=manifest,
                input_schema_hash=_json_hash(candidate.input_schema),
                output_schema_hash=_json_hash(candidate.output_schema),
                pricing=_safe_pricing_summary(candidate.pricing),
                permission_level=str(candidate.actor["actorPermissionLevel"]),
                security_evidence={
                    "public": candidate.actor.get("isPublic") is True,
                    "store_unrunnable_actors_excluded": True,
                    "not_deprecated": (
                        candidate.actor.get("isDeprecated") is False
                    ),
                    "limited_permissions": True,
                    "exact_successful_build": True,
                    "input_validation": True,
                },
                lifecycle="static_valid",
                ai_provider=self.ai_provider,
                ai_model=self.ai_model,
                prompt_version="actor_manifest_v1",
                discovery_run_id=run_id,
            )
            revisions.append(revision_id)
            revision_publishers.add(candidate.publisher)
        if len(revision_publishers) < 2 and revisions:
            rejected.append(
                {
                    "actor_id": "candidate-pool",
                    "reason": "actor_publisher_diversity_shortfall",
                }
            )
        final_stage = (
            "awaiting_canary_approval"
            if len(revisions) >= MIN_AI_PROPOSALS
            and len(revision_publishers) >= 2
            else "candidate_shortfall"
        )
        shortfall_error = (
            "input_validation_candidate_shortfall"
            if len(revisions) < MIN_AI_PROPOSALS
            else "publisher_diversity_candidate_shortfall"
        )
        self.ops.update_discovery_run(
            run_id,
            expected_stage="input_validation",
            stage=final_stage,
            error_code=(
                None if final_stage == "awaiting_canary_approval"
                else shortfall_error
            ),
            candidate_count=len(revisions),
            rejections=tuple(rejected),
        )
        return DiscoveryOutcome(
            run_id,
            str(run["route_id"]),
            final_stage,
            tuple(revisions),
            tuple(rejected),
        )

    async def _load_candidate(
        self,
        actor_id: str,
        *,
        per_run_cap_usd: float,
    ) -> DiscoveryCandidate:
        actor = dict(await _maybe_await(self.metadata_client.get_actor(actor_id)))
        metadata_identities = {
            str(actor.get("id") or "").strip().replace("~", "/"),
            str(actor.get("actorId") or "").strip().replace("~", "/"),
        }
        username = str(
            actor.get("username") or actor.get("userUsername") or ""
        ).strip()
        name = str(actor.get("name") or actor.get("actorName") or "").strip()
        if username and name:
            metadata_identities.add(f"{username}/{name}")
        metadata_identities.discard("")
        if metadata_identities and actor_id not in metadata_identities:
            raise _reject("actor_metadata_identity_mismatch")
        if actor.get("isPublic") is not True:
            raise _reject("actor_not_public")
        if actor.get("isDeprecated") is not False:
            raise _reject(
                "actor_deprecated"
                if actor.get("isDeprecated") is True
                else "actor_deprecation_unverifiable"
            )
        if actor.get("isRunnable") is False or actor.get("canRun") is False:
            raise _reject("actor_not_runnable")
        permission = str(actor.get("actorPermissionLevel") or "").casefold()
        if permission != "limited_permissions":
            raise _reject(
                "actor_full_permission"
                if permission == "full_permissions"
                else "actor_permission_unverifiable"
            )
        build_id, build_number = _tagged_build(actor)
        if not build_id or not build_number:
            raise _reject("actor_exact_build_missing")
        build = dict(await _maybe_await(self.metadata_client.get_build(build_id)))
        if str(build.get("status") or "").upper() != "SUCCEEDED":
            raise _reject("actor_build_not_successful")
        actual_number = str(build.get("buildNumber") or "")
        if actual_number and actual_number != build_number:
            raise _reject("actor_build_identity_mismatch")
        input_schema, output_schema = _schemas(build)
        if not input_schema or not output_schema:
            raise _reject("actor_schema_unverifiable")
        input_template = _input_template_from_schema(input_schema)
        if not input_template:
            raise _reject("actor_input_schema_unmappable")
        pricing = _pricing(actor)
        _validate_pricing(pricing, per_run_cap_usd)
        publisher = _publisher(actor_id, actor)
        return DiscoveryCandidate(
            actor_id=actor_id,
            publisher=publisher,
            build_id=build_id,
            build_number=build_number,
            actor=actor,
            build=build,
            input_schema=input_schema,
            output_schema=output_schema,
            pricing=pricing,
            input_template=input_template,
        )


async def _maybe_await(value: T | Awaitable[T]) -> T:
    if inspect.isawaitable(value):
        return await value
    return value


def _unwrap(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    data = payload.get("data")
    return data if isinstance(data, Mapping) else payload


def _actor_id(row: Mapping[str, Any]) -> str | None:
    username = str(row.get("username") or row.get("userUsername") or "").strip()
    name = str(row.get("name") or row.get("actorName") or "").strip()
    value = str(row.get("actorId") or row.get("id") or "").strip().replace("~", "/")
    if not value and username and name:
        value = f"{username}/{name}"
    if not (
        (8 <= len(value) <= 64 and value.isalnum())
        or (
            value.count("/") == 1
            and 3 <= len(value) <= 127
            and all(part for part in value.split("/", 1))
        )
    ):
        return None
    return value


def _publisher(actor_id: str, actor: Mapping[str, Any]) -> str:
    actor_prefix = actor_id.split("/", 1)[0] if "/" in actor_id else ""
    publisher = str(
        actor.get("username")
        or actor.get("userUsername")
        or actor_prefix
    ).strip()
    if not publisher or len(publisher) > 128:
        raise _reject("actor_publisher_invalid")
    return publisher.casefold()


def _tagged_build(actor: Mapping[str, Any]) -> tuple[str, str]:
    tagged = actor.get("taggedBuilds")
    if not isinstance(tagged, Mapping):
        return "", ""
    preferred = tagged.get("latest")
    if not isinstance(preferred, Mapping):
        for value in tagged.values():
            if isinstance(value, Mapping):
                preferred = value
                break
    if not isinstance(preferred, Mapping):
        return "", ""
    return (
        str(preferred.get("buildId") or preferred.get("id") or "").strip(),
        str(preferred.get("buildNumber") or preferred.get("number") or "").strip(),
    )


def _schemas(
    build: Mapping[str, Any],
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    definition = build.get("actorDefinition")
    definition = definition if isinstance(definition, Mapping) else {}
    input_schema = _schema_mapping(build.get("inputSchema"))
    if not input_schema:
        input_block = definition.get("input")
        nested_input = (
            input_block.get("schema")
            if isinstance(input_block, Mapping)
            else input_block
        )
        input_schema = _schema_mapping(nested_input)
        if not input_schema:
            input_schema = _schema_mapping(input_block)
    output_schema = _dataset_schema_mapping(
        build.get("datasetSchema") or build.get("outputSchema")
    )
    if not output_schema:
        storages = definition.get("storages")
        dataset = (
            storages.get("dataset")
            if isinstance(storages, Mapping)
            else None
        )
        nested_dataset = (
            dataset.get("schema")
            if isinstance(dataset, Mapping)
            else dataset
        )
        output_schema = _dataset_schema_mapping(nested_dataset)
        if not output_schema:
            output_schema = _dataset_schema_mapping(dataset)
    return (
        input_schema if isinstance(input_schema, Mapping) else {},
        output_schema if isinstance(output_schema, Mapping) else {},
    )


def _schema_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if not isinstance(value, str) or len(value.encode("utf-8")) > 64 * 1024:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, Mapping) else {}


def _dataset_schema_mapping(value: Any) -> Mapping[str, Any]:
    """Return only the Dataset row contract, excluding presentation views."""

    schema = _schema_mapping(value)
    fields = schema.get("fields")
    if isinstance(fields, Mapping):
        return dict(fields)
    return schema


def _pricing(actor: Mapping[str, Any]) -> Mapping[str, Any]:
    """Select the currently effective official Actor Detail price record.

    Actor Detail exposes pricing through ``pricingInfos``.  Do not accept a
    caller-supplied/normalized top-level ``pricing`` object here: allowing it
    to take precedence would let cheaper synthetic metadata hide the current
    official price record.
    """

    infos = actor.get("pricingInfos")
    if isinstance(infos, Sequence) and not isinstance(infos, (str, bytes)):
        rows = [info for info in infos if isinstance(info, Mapping)]
        if not rows:
            return {}
        now = datetime.now(timezone.utc)
        effective: list[tuple[datetime, Mapping[str, Any]]] = []
        for info in rows:
            started_at = _pricing_started_at(info.get("startedAt"))
            if started_at is not None and started_at <= now:
                effective.append((started_at, info))
        if effective:
            return max(effective, key=lambda pair: pair[0])[1]
        return {}
    return {}


def _validate_pricing(pricing: Mapping[str, Any], cap: float) -> None:
    if not isinstance(pricing, Mapping) or not pricing:
        raise _reject("actor_pricing_unverifiable")
    model = str(
        pricing.get("pricingModel")
        or pricing.get("model")
        or pricing.get("type")
        or ""
    ).casefold()
    if "month" in model or "rental" in model or "subscription" in model:
        raise _reject("actor_monthly_pricing")
    if model not in {"free", "price_per_dataset_item", "pay_per_event"}:
        raise _reject("actor_pricing_unverifiable")
    for key in (
        "minimumChargeUsd",
        "minChargeUsd",
        "minimumPriceUsd",
        "pricePerRunUsd",
        "minimalMaxTotalChargeUsd",
        "pricePerUnitUsd",
    ):
        value = pricing.get(key)
        if value is None:
            continue
        _validate_price_value(value, cap)

    pricing_per_event = pricing.get("pricingPerEvent")
    tiered_dataset = pricing.get("tieredPricing")
    if model == "free":
        if any(
            pricing.get(key) is not None
            for key in (
                "pricePerUnitUsd",
                "tieredPricing",
                "pricingPerEvent",
            )
        ):
            raise _reject("actor_pricing_invalid")
        return

    if model == "price_per_dataset_item":
        if pricing_per_event is not None:
            raise _reject("actor_pricing_invalid")
        direct_price = pricing.get("pricePerUnitUsd")
        has_direct = direct_price is not None
        has_tiered = tiered_dataset is not None
        if has_direct == has_tiered:
            raise _reject("actor_pricing_invalid")
        if has_direct:
            _validate_price_value(direct_price, cap)
            return
        if (
            not isinstance(tiered_dataset, Mapping)
            or not tiered_dataset
            or len(tiered_dataset) > 32
        ):
            raise _reject("actor_pricing_invalid")
        for tier in tiered_dataset.values():
            if (
                not isinstance(tier, Mapping)
                or tier.get("tieredPricePerUnitUsd") is None
            ):
                raise _reject("actor_pricing_invalid")
            _validate_price_value(tier["tieredPricePerUnitUsd"], cap)
        return

    if pricing.get("pricePerUnitUsd") is not None or tiered_dataset is not None:
        raise _reject("actor_pricing_invalid")
    if not isinstance(pricing_per_event, Mapping):
        raise _reject("actor_pricing_invalid")
    events = pricing_per_event.get("actorChargeEvents")
    if not isinstance(events, Mapping) or not events or len(events) > 64:
        raise _reject("actor_pricing_invalid")
    for event in events.values():
        if not isinstance(event, Mapping):
            raise _reject("actor_pricing_invalid")
        event_price = event.get("eventPriceUsd")
        tiered = event.get("eventTieredPricingUsd")
        if (event_price is None) == (tiered is None):
            raise _reject("actor_pricing_invalid")
        if event_price is not None:
            _validate_price_value(event_price, cap)
            continue
        if not isinstance(tiered, Mapping) or not tiered or len(tiered) > 32:
            raise _reject("actor_pricing_invalid")
        for tier in tiered.values():
            if (
                not isinstance(tier, Mapping)
                or tier.get("tieredEventPriceUsd") is None
            ):
                raise _reject("actor_pricing_invalid")
            _validate_price_value(tier["tieredEventPriceUsd"], cap)


def _safe_pricing_summary(pricing: Mapping[str, Any]) -> dict[str, Any]:
    allowed = (
        "pricingModel",
        "model",
        "minimumChargeUsd",
        "minChargeUsd",
        "minimumPriceUsd",
        "pricePerRunUsd",
        "minimalMaxTotalChargeUsd",
        "pricePerUnitUsd",
    )
    summary: dict[str, Any] = {}
    for key in allowed:
        value = pricing.get(key)
        if isinstance(value, str):
            summary[key] = value
        elif _finite_price_number(value) is not None:
            summary[key] = value
    pricing_per_event = pricing.get("pricingPerEvent")
    events = (
        pricing_per_event.get("actorChargeEvents")
        if isinstance(pricing_per_event, Mapping)
        else None
    )
    if not isinstance(events, Mapping):
        # Accept the first implementation's flattened safe snapshot so that
        # the canonicalizer remains idempotent across an in-place v15 upgrade.
        events = pricing.get("actorChargeEvents")
    if isinstance(events, Mapping):
        safe_events: dict[str, Any] = {}
        for event_name, event in sorted(events.items())[:64]:
            if not isinstance(event_name, str) or not isinstance(
                event,
                Mapping,
            ):
                continue
            safe_event: dict[str, Any] = {}
            value = event.get("eventPriceUsd")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                safe_event["eventPriceUsd"] = value
            tiered = event.get("eventTieredPricingUsd")
            if isinstance(tiered, Mapping):
                safe_tiers: dict[str, float] = {}
                for tier_name, tier in sorted(tiered.items())[:32]:
                    tier_value = (
                        tier.get("tieredEventPriceUsd")
                        if isinstance(tier, Mapping)
                        else tier
                    )
                    safe_value = _finite_price_number(tier_value)
                    if isinstance(tier_name, str) and safe_value is not None:
                        safe_tiers[tier_name] = safe_value
                if safe_tiers:
                    safe_event["eventTieredPricingUsd"] = safe_tiers
            if safe_event:
                safe_events[event_name[:128]] = safe_event
        if safe_events:
            summary["pricingPerEvent"] = {
                "actorChargeEvents": safe_events,
            }
    tiered_dataset = pricing.get("tieredPricing")
    if isinstance(tiered_dataset, Mapping):
        safe_dataset_tiers: dict[str, dict[str, float]] = {}
        for tier_name, tier in sorted(tiered_dataset.items())[:32]:
            value = (
                tier.get("tieredPricePerUnitUsd")
                if isinstance(tier, Mapping)
                else None
            )
            safe_value = _finite_price_number(value)
            if isinstance(tier_name, str) and safe_value is not None:
                safe_dataset_tiers[tier_name[:64]] = {
                    "tieredPricePerUnitUsd": safe_value
                }
        if safe_dataset_tiers:
            summary["tieredPricing"] = safe_dataset_tiers
    return summary


def _finite_price_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        numeric = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) and numeric >= 0 else None


def _validate_price_value(value: Any, cap: float) -> None:
    if value is None:
        return
    numeric = _finite_price_number(value)
    if numeric is None:
        raise _reject("actor_pricing_invalid")
    if numeric > cap:
        raise _reject("actor_price_above_route_cap")


def _pricing_started_at(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


_MISSING_INPUT_LITERAL = object()


def _input_template_from_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Derive one code-free target input from public Actor Schema metadata.

    AI ranks candidates and maps their output, but it must not guess whether a
    target belongs in a string, string array, or Apify ``startUrls`` request
    list.  The official Build input validator remains the final authority.
    """

    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return {}
    raw_required = schema.get("required", ())
    if (
        isinstance(raw_required, Sequence)
        and not isinstance(raw_required, (str, bytes, bytearray))
        and any(not _safe_input_key(item) for item in raw_required)
    ):
        return {}
    required = (
        {
            str(item)
            for item in raw_required
            if isinstance(item, str) and item
        }
        if isinstance(raw_required, Sequence)
        and not isinstance(raw_required, (str, bytes, bytearray))
        else set()
    )

    target_options: list[tuple[int, str, Mapping[str, Any]]] = []
    for raw_name, raw_property in properties.items():
        if not _safe_input_key(raw_name) or not isinstance(raw_property, Mapping):
            continue
        score = _target_input_score(raw_name, raw_property)
        if score > 0:
            target_options.append((score, raw_name, raw_property))
    if not target_options:
        return {}
    _, target_name, target_schema = max(
        target_options,
        key=lambda item: (item[0], item[1]),
    )
    target_value = _target_input_value(target_name, target_schema)
    if target_value is None:
        return {}

    template: dict[str, Any] = {target_name: target_value}
    for name in sorted(required):
        if name in template:
            continue
        property_schema = properties.get(name)
        if not isinstance(property_schema, Mapping):
            return {}
        literal = _required_input_literal(property_schema)
        if literal is _MISSING_INPUT_LITERAL:
            return {}
        template[name] = literal

    max_options: list[tuple[int, str]] = []
    for raw_name, raw_property in properties.items():
        if (
            not isinstance(raw_name, str)
            or not _safe_input_key(raw_name)
            or raw_name in template
            or not isinstance(raw_property, Mapping)
            or str(raw_property.get("type") or "") not in {"integer", "number"}
        ):
            continue
        score = _max_items_input_score(raw_name)
        if score > 0:
            max_options.append((score, raw_name))
    if max_options:
        _, max_name = max(max_options, key=lambda item: (item[0], item[1]))
        template[max_name] = {"$ref": "runtime.max_items"}
    return template


def _target_input_score(name: str, schema: Mapping[str, Any]) -> int:
    normalized = re.sub(r"[^a-z0-9]", "", name.casefold())
    field_type = str(schema.get("type") or "").casefold()
    if field_type not in {"string", "array", "object"}:
        return 0
    if any(
        marker in normalized
        for marker in ("keyword", "searchterm", "location", "videourl", "posturl")
    ):
        return 0
    if normalized in {"starturls", "directurls", "profileurls", "channelurls"}:
        return 300
    if "profileurl" in normalized or "channelurl" in normalized:
        return 280
    if any(
        marker in normalized
        for marker in ("youtubehandle", "handle", "username", "channel", "profile")
    ):
        return 240
    if "url" in normalized or "uri" in normalized:
        return 160
    return 0


def _safe_input_key(value: Any) -> bool:
    return isinstance(value, str) and bool(
        re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", value)
    )


def _target_input_value(name: str, schema: Mapping[str, Any]) -> Any:
    normalized = re.sub(r"[^a-z0-9]", "", name.casefold())
    reference = (
        "target.handle"
        if any(marker in normalized for marker in ("handle", "username"))
        and "url" not in normalized
        else "target.native_id"
        if normalized.endswith("id") and "url" not in normalized
        else "target.canonical_url"
    )
    value: dict[str, str] = {"$ref": reference}
    field_type = str(schema.get("type") or "").casefold()
    if field_type == "string":
        return value
    if field_type == "object":
        nested = schema.get("properties")
        if isinstance(nested, Mapping):
            url_name = next(
                (
                    str(key)
                    for key in nested
                    if _safe_input_key(key)
                    and ("url" in key.casefold() or "uri" in key.casefold())
                ),
                None,
            )
            if url_name:
                return {url_name: {"$ref": "target.canonical_url"}}
        return None
    if field_type != "array":
        return None
    items = schema.get("items")
    if isinstance(items, Mapping) and str(items.get("type") or "").casefold() == "object":
        nested = items.get("properties")
        if isinstance(nested, Mapping):
            url_name = next(
                (
                    str(key)
                    for key in nested
                    if _safe_input_key(key)
                    and ("url" in key.casefold() or "uri" in key.casefold())
                ),
                None,
            )
            if url_name:
                return [{url_name: {"$ref": "target.canonical_url"}}]
    if normalized == "starturls":
        return [{"url": {"$ref": "target.canonical_url"}}]
    return [value]


def _required_input_literal(schema: Mapping[str, Any]) -> Any:
    for key in ("default", "const"):
        if key in schema and _safe_input_literal(schema[key]):
            return schema[key]
    enum = schema.get("enum")
    if isinstance(enum, Sequence) and not isinstance(enum, (str, bytes, bytearray)):
        for value in enum:
            if _safe_input_literal(value):
                return value
    field_type = str(schema.get("type") or "").casefold()
    if field_type == "boolean":
        return False
    if field_type in {"integer", "number"}:
        return {"$ref": "runtime.max_items"}
    return _MISSING_INPUT_LITERAL


def _safe_input_literal(value: Any) -> bool:
    if value is None or isinstance(value, (bool, int, float)):
        return not isinstance(value, float) or math.isfinite(value)
    if isinstance(value, str):
        return bool(re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", value))
    return False


def _max_items_input_score(name: str) -> int:
    normalized = re.sub(r"[^a-z0-9]", "", name.casefold())
    exact = {
        "maxitems": 300,
        "resultslimit": 290,
        "maxresults": 280,
        "maxvideosperchannel": 270,
        "maxposts": 260,
        "maxvideos": 250,
        "limit": 200,
    }
    if normalized in exact:
        return exact[normalized]
    if normalized.startswith("max") and any(
        marker in normalized for marker in ("item", "result", "post", "video", "tweet")
    ):
        return 180
    return 0


def _schema_shape(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Keep schema structure but drop examples/defaults/descriptions and values."""

    def visit(
        value: Any,
        depth: int = 0,
        *,
        property_map: bool = False,
    ) -> Any:
        if depth > 10:
            return {"truncated": True}
        if isinstance(value, Mapping):
            if property_map:
                return {
                    str(key)[:128]: visit(child, depth + 1)
                    for key, child in sorted(
                        value.items(),
                        key=lambda item: str(item[0]),
                    )[:128]
                    if isinstance(key, str) and key
                }
            result: dict[str, Any] = {}
            for key, child in value.items():
                if key in {
                    "example",
                    "examples",
                    "default",
                    "description",
                    "title",
                    "$comment",
                }:
                    continue
                if key in {
                    "type",
                    "format",
                    "required",
                    "properties",
                    "items",
                    "oneOf",
                    "anyOf",
                    "allOf",
                    "enum",
                }:
                    result[str(key)] = visit(
                        child,
                        depth + 1,
                        property_map=key == "properties",
                    )
            return result
        if isinstance(value, Sequence) and not isinstance(
            value,
            (str, bytes, bytearray),
        ):
            return [visit(child, depth + 1) for child in value[:64]]
        if isinstance(value, str):
            return value[:128]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return None

    shaped = visit(schema)
    return shaped if isinstance(shaped, dict) else {}


def _validate_manifest_hosts(manifest: Any, platform: str) -> None:
    permitted = _PLATFORM_HOSTS.get(platform)
    if not permitted:
        raise ActorManifestError(
            "apify_manifest_platform_unsupported",
            "Manifest platform is not supported",
        )
    for host in manifest.semantics.url_host_allowlist:
        if not any(host == root or host.endswith(f".{root}") for root in permitted):
            raise ActorManifestError(
                "apify_manifest_output_host_invalid",
                "Manifest output host is outside the route allowlist",
            )


def _json_pointer_tokens(pointer: str) -> tuple[str, ...]:
    if pointer == "":
        return ()
    return tuple(
        token.replace("~1", "/").replace("~0", "~")
        for token in pointer[1:].split("/")
    )


def _schema_alternatives(schema: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    alternatives: list[Mapping[str, Any]] = [schema]
    for keyword in ("oneOf", "anyOf", "allOf"):
        branches = schema.get(keyword)
        if isinstance(branches, Sequence) and not isinstance(
            branches,
            (str, bytes, bytearray),
        ):
            alternatives.extend(
                branch for branch in branches if isinstance(branch, Mapping)
            )
    return tuple(alternatives)


def _schema_pointer_exists(schema: Mapping[str, Any], pointer: str) -> bool:
    frontier: tuple[Mapping[str, Any], ...] = (schema,)
    for token in _json_pointer_tokens(pointer):
        next_frontier: list[Mapping[str, Any]] = []
        for raw_node in frontier:
            for node in _schema_alternatives(raw_node):
                properties = node.get("properties")
                if isinstance(properties, Mapping):
                    child = properties.get(token)
                    if isinstance(child, Mapping):
                        next_frontier.append(child)
                # Apify Dataset schemas frequently expose ``fields`` as a
                # direct name -> JSON Schema mapping rather than wrapping it
                # in a root ``properties`` object.
                direct = node.get(token)
                if isinstance(direct, Mapping):
                    next_frontier.append(direct)
                if token.isdigit():
                    items = node.get("items")
                    if isinstance(items, Mapping):
                        next_frontier.append(items)
        if not next_frontier:
            return False
        frontier = tuple(next_frontier)
    return bool(frontier)


def _validate_manifest_output_schema(
    manifest: Any,
    output_schema: Mapping[str, Any],
) -> None:
    """Require every output pointer to exist in the fetched Build schema."""

    if not output_schema:
        raise ActorManifestError(
            "apify_manifest_output_schema_unverifiable",
            "Manifest output schema is unavailable",
        )
    for field_name in type(manifest.output).model_fields:
        mapping = getattr(manifest.output, field_name)
        if mapping is None:
            continue
        if any(
            not _schema_pointer_exists(output_schema, pointer)
            for pointer in mapping.pointers
        ):
            raise ActorManifestError(
                "apify_manifest_output_pointer_unverifiable",
                "Manifest output pointer is absent from the exact Build schema",
            )


def _validate_manifest_route_identity(
    manifest: Any,
    *,
    target_type: str,
    capability: str,
) -> None:
    """Keep item identity separate from the content item's own URL."""

    identity = manifest.semantics.identity
    if (
        target_type in {"profile", "channel"}
        and capability == "items"
        and identity.output_field == "source_url"
    ):
        source_url = manifest.output.source_url
        item_url = manifest.output.url
        if source_url is None or set(source_url.pointers) & set(item_url.pointers):
            raise ActorManifestError(
                "apify_manifest_source_identity_invalid",
                "Profile or channel identity cannot reuse the content item URL",
            )


def _reference_target(platform: str) -> ActorTarget:
    if platform == "x":
        return ActorTarget(
            canonical_url="https://x.com/apify",
            native_id="apify",
            handle="apify",
        )
    if platform == "youtube":
        return ActorTarget(
            canonical_url="https://www.youtube.com/@apify",
            native_id="apify",
            handle="apify",
        )
    if platform == "instagram":
        return ActorTarget(
            canonical_url="https://www.instagram.com/apify/",
            native_id="apify",
            handle="apify",
        )
    raise ActorDiscoveryError(
        "apify_actor_platform_unsupported",
        "Actor discovery platform is not supported",
        status_code=422,
    )


def _json_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _reject(code: str) -> ActorDiscoveryError:
    return ActorDiscoveryError(
        code,
        "Actor candidate failed deterministic discovery checks",
        status_code=422,
    )


__all__ = [
    "ActorDiscoveryError",
    "ActorMetadataClient",
    "ApifyActorDiscoveryService",
    "ApifyStoreRestClient",
    "DiscoveryCandidate",
    "DiscoveryOutcome",
]
