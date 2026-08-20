"""Compatibility-trial detection kept outside the general Canary runner."""

from __future__ import annotations

import json
from typing import Any


class CompatibilityPreflightError(Exception):
    """A safe, structured failure before a paid compatibility start."""

    def __init__(self, code: str, status_code: int = 412) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)


async def run_compatibility_if_needed(
    runner: Any,
    row: Any,
    *,
    validation_id: str,
    job_id: str,
) -> Any | None:
    """Run a compatibility trial, including its Route-generation fence."""

    if not uses_compatibility_runner(row):
        return None
    if int(row["route_generation"]) != int(row["approved_generation"] or -1) and str(
        row["kind"]
    ) == "route_reference":
        from .apify_actor_ops import ActorOpsError

        runner.ops.record_validation(
            validation_id,
            status="cancelled",
            semantic_outcome="approval_stale",
            cost_usd=0.0,
            cost_final=True,
            counts_toward_canary=False,
        )
        raise ActorOpsError(
            "apify_actor_canary_approval_stale",
            "Actor Route changed after compatibility approval",
            status_code=409,
        )
    return await runner._run_compatibility_single(
        row,
        validation_id=validation_id,
        job_id=job_id,
    )


def uses_compatibility_runner(row: Any) -> bool:
    """Return whether a validation needs X's controlled compatibility path."""

    if bool(row["compatibility_validation"]):
        return True
    if str(row["platform"]) != "x" or not bool(row["observed_manifest"]):
        try:
            evidence = json.loads(str(row["security_evidence_json"] or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
        return isinstance(evidence, dict) and bool(
            evidence.get("compatibility_trial_only")
        )
    return True


def store_result_matches_actor(row: Any, actor_id: str) -> bool:
    """Confirm that Store's unrunnable exclusion covered this exact Actor."""

    expected = str(actor_id).strip().replace("~", "/")
    if not expected:
        return False
    values = {
        str(row.get("actorId") or "").strip().replace("~", "/"),
        str(row.get("id") or "").strip().replace("~", "/"),
    }
    username = str(row.get("username") or row.get("userUsername") or "").strip()
    name = str(row.get("name") or row.get("actorName") or "").strip()
    if username and name:
        values.add(f"{username}/{name}")
    return expected in values


async def preflight_compatibility_candidate(runner: Any, row: Any) -> Any:
    """Reconfirm Store-runnable provenance without starting or billing an Actor."""

    from .apify_actor_discovery import (
        ActorDiscoveryError,
        ApifyActorDiscoveryService,
        ApifyStoreRestClient,
    )
    from .apify_actor_ops import VALIDATION_MAX_CHARGE_USD_LIMIT

    actor_id = str(row["actor_id"])
    metadata = ApifyStoreRestClient(
        str(runner.client.token or ""),
        base_url=str(runner.client.base_url),
        client=runner.client.http_client,
    )
    try:
        security = json.loads(str(row["security_evidence_json"] or "{}"))
        stored_provenance = isinstance(security, dict) and bool(
            security.get("store_runnable_provenance")
        )
        store_rows = []
        if not stored_provenance:
            for query in dict.fromkeys((actor_id, str(row["publisher"]))):
                store_rows.extend(await metadata.search_store(query))
        store_proven = stored_provenance or any(
            store_result_matches_actor(item, actor_id) for item in store_rows
        )
        verifier = ApifyActorDiscoveryService(runner.ops, metadata, lambda _prompt: {})
        candidate = await verifier.load_compatibility_candidate(
            actor_id,
            per_run_cap_usd=min(
                float(row["approved_max_cost_usd"] or VALIDATION_MAX_CHARGE_USD_LIMIT),
                VALIDATION_MAX_CHARGE_USD_LIMIT,
            ),
            allow_store_runnable_omission=store_proven,
        )
        if row["build_id"] and (
            str(candidate.build_id or "") != str(row["build_id"])
            or str(candidate.build_number or "") != str(row["build_number"] or "")
        ):
            raise ActorDiscoveryError(
                "compatibility_candidate_changed",
                "Compatibility Actor Build changed after approval",
                status_code=412,
            )
        return candidate
    except (ActorDiscoveryError, ValueError) as exc:
        raise CompatibilityPreflightError(
            str(getattr(exc, "code", "compatibility_preflight_failed")),
            int(getattr(exc, "status_code", 412)),
        ) from None
