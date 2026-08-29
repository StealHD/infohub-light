"""Free replacement checks performed before an operator authorizes a Probe."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from ...apify_actor_identity import source_config_target, source_target_fingerprint
from ..apify_actor_manifest import (
    ActorManifestError,
    actor_manifest_hash,
    parse_actor_manifest,
)
from .apify_catalog import ApifyDiscoveryCatalog, ApifyStoreRestClient
from .apify_catalog_credentials import resolve_apify_catalog_credential
from .maintenance_preflight import settle_preflight_rejection
from .input_plan import render_input_plan
from .policy import candidate_has_exact_execution_contract
from .ports import ActorManifest, FetchWindow, ProbePreflightResult
from .registry import AdapterNotRegistered, AdapterRegistry
from .replacement_contract_reason import (
    manifest_contract_error_code,
    target_context_error_code,
)
from .runtime_candidate_health import candidate_operational_states


class ReplacementCatalog(Protocol):
    async def verify_candidate(
        self, candidate: object, *, max_charge_usd: float
    ) -> ProbePreflightResult: ...


@dataclass(frozen=True, slots=True)
class ReplacementPreviewCheck:
    allowed: bool
    error_code: str | None = None
    source_id: str | None = None
    settlement_code: str | None = None


def validation_catalog(
    store: Any,
    *,
    workspace_id: str,
    data_dir: str,
) -> ReplacementCatalog | None:
    credential = resolve_apify_catalog_credential(
        store,
        workspace_id=workspace_id,
        data_dir=data_dir,
        purpose="validation",
    )
    if credential is None:
        return None
    return ApifyDiscoveryCatalog(ApifyStoreRestClient(credential.token))


async def check_replacement_preview(
    store: Any,
    repository: Any,
    registry: AdapterRegistry,
    catalog: ReplacementCatalog | None,
    *,
    route_id: str,
    candidate_id: str,
    max_charge_usd: float,
) -> ReplacementPreviewCheck:
    """Validate known health, local input compatibility, and exact Build metadata."""

    route = repository.get_route(route_id)
    candidate = repository.get_candidate(candidate_id)
    state = candidate_operational_states(repository, (candidate,))[
        candidate.candidate_id
    ]
    if state.confirmed_failure:
        return ReplacementPreviewCheck(
            False, _known_failure_code(state.issue_code)
        )
    bindings = repository.operator.binding_set(route_id)
    if not bindings:
        return ReplacementPreviewCheck(False, "actorops_replacement_route_not_ready")
    source_id = bindings[0][0]
    sampling = repository.sampling.get_valid(candidate)
    if not candidate_has_exact_execution_contract(candidate) and sampling is None:
        return ReplacementPreviewCheck(
            False,
            "actorops_replacement_contract_invalid",
            source_id,
            "actorops_v2_candidate_contract_invalid",
        )
    try:
        adapter = registry.require(route.route_key)
        manifest = _manifest(candidate) if sampling is None else None
        now = datetime.now(timezone.utc)
        window = FetchWindow(
            max_items=1,
            since=now - timedelta(days=90),
            until=now,
        )
        for binding_source_id, _version, fingerprint in bindings:
            source = store.get_source(binding_source_id)
            config = source.get("config") if source else None
            if not isinstance(config, dict):
                return ReplacementPreviewCheck(
                    False, "actorops_replacement_source_missing"
                )
            target = adapter.normalize_target(config)
            actual_fingerprint = source_target_fingerprint(
                repository.workspace_id,
                route_id,
                source_config_target(config, platform=route.route_key.platform),
                platform=route.route_key.platform,
            )
            if actual_fingerprint != fingerprint:
                return ReplacementPreviewCheck(
                    False, "actorops_replacement_target_changed"
                )
            if manifest is not None:
                context_error = target_context_error_code(
                    manifest.manifest_json, target
                )
                if context_error:
                    return ReplacementPreviewCheck(
                        False,
                        context_error,
                        binding_source_id,
                        "actorops_v2_candidate_contract_invalid",
                    )
                adapter.build_actor_input(target, manifest, window)
            else:
                render_input_plan(str(sampling["input_plan_json"]), target, window)
    except ActorManifestError as error:
        return ReplacementPreviewCheck(
            False,
            manifest_contract_error_code(error.code),
            source_id,
            "actorops_v2_candidate_contract_invalid",
        )
    except (AdapterNotRegistered, TypeError, ValueError):
        return ReplacementPreviewCheck(
            False,
            "actorops_replacement_input_contract_invalid",
            source_id,
            "actorops_v2_candidate_contract_invalid",
        )
    if catalog is None:
        return ReplacementPreviewCheck(
            False, "actorops_replacement_credential_unavailable"
        )
    result = await catalog.verify_candidate(
        candidate, max_charge_usd=max_charge_usd
    )
    if result.allowed:
        return ReplacementPreviewCheck(True)
    raw_code = str(
        result.error_code or "actorops_replacement_preflight_rejected"
    )
    settlement_code = raw_code if raw_code in _HARD_PREFLIGHT_CODES else None
    return ReplacementPreviewCheck(
        False,
        _public_preflight_code(raw_code),
        source_id,
        settlement_code,
    )


def settle_replacement_preview_failure(
    repository: Any,
    check: ReplacementPreviewCheck,
    *,
    route_id: str,
    candidate_id: str,
    expected_candidate_generation: int,
) -> None:
    if not check.source_id or not check.settlement_code:
        return
    settle_preflight_rejection(
        repository,
        route_id=route_id,
        source_id=check.source_id,
        candidate_id=candidate_id,
        expected_candidate_generation=expected_candidate_generation,
        maintenance_slot=f"replacement-preview:{candidate_id}",
        error_code=check.settlement_code,
    )


def _manifest(candidate: Any) -> ActorManifest:
    parsed = parse_actor_manifest(str(candidate.manifest_json))
    if actor_manifest_hash(parsed) != str(candidate.manifest_hash):
        raise ValueError("candidate manifest hash mismatch")
    return ActorManifest(
        actor_id=str(candidate.actor_id),
        build_id=str(candidate.build_id),
        build_number=str(candidate.build_number),
        manifest_json=str(candidate.manifest_json),
        manifest_hash=str(candidate.manifest_hash),
    )


def _known_failure_code(issue_code: str | None) -> str:
    return {
        "actor_deleted": "actorops_maintenance_actor_unavailable",
        "build_unavailable": "actorops_maintenance_revision_changed",
        "contract_invalid": "actorops_replacement_contract_invalid",
        "repeated_start_rejection": "actorops_replacement_candidate_unavailable",
    }.get(str(issue_code or ""), "actorops_replacement_candidate_unavailable")


def _public_preflight_code(code: str) -> str:
    return {
        "actorops_discovery_actor_unavailable": "actorops_maintenance_actor_unavailable",
        "actorops_discovery_catalog_not_found": "actorops_maintenance_actor_unavailable",
        "actorops_discovery_exact_build_missing": "actorops_maintenance_revision_changed",
        "actorops_discovery_revision_changed": "actorops_maintenance_revision_changed",
        "actorops_discovery_catalog_unavailable": "actorops_maintenance_preflight_unavailable",
    }.get(code, code)


_HARD_PREFLIGHT_CODES = {
    "actorops_v2_candidate_contract_invalid",
    "actorops_discovery_actor_unavailable",
    "actorops_discovery_catalog_not_found",
    "actorops_maintenance_actor_unavailable",
    "actorops_discovery_exact_build_missing",
    "actorops_discovery_revision_changed",
    "actorops_maintenance_revision_changed",
}


__all__ = [
    "ReplacementPreviewCheck",
    "check_replacement_preview",
    "settle_replacement_preview_failure",
    "validation_catalog",
]
