"""Paid, bounded Actor freshness comparison using the validation credential."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from ..models import (
    ApifySocialConfig,
    ApifySocialPlatform,
    ApifySocialSubscriptionConfig,
)
from ..scrapers.apify_client import ApifyClient
from ..scrapers.apify_social import ApifySocialScraper
from ..storage.service_store import ServiceStore
from .apify_actor_canary import (
    actor_canary_timeout_seconds,
    reference_target_for_slot,
)
from .apify_actor_manifest import (
    ActorRuntime,
    map_actor_output,
    parse_actor_manifest,
    render_actor_input,
)
from .apify_actor_ops import ApifyActorOpsService
from .apify_actor_resilience import (
    ActorResilienceError,
    ApifyActorResilienceService,
    FRESHNESS_PER_ACTOR_CAP_USD,
)


REFERENCE_WINDOW_DAYS = 30
REFERENCE_SAMPLE_ITEMS = 3


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_error_code(exc: Exception) -> str:
    raw = str(getattr(exc, "code", "") or type(exc).__name__).strip().casefold()
    normalized = "".join(
        character if character.isalnum() else "_" for character in raw
    ).strip("_")
    return normalized[:96] or "freshness_actor_failed"


def _observed_x_handle(row: dict[str, Any]) -> str:
    user_value = row.get("user") or row.get("author") or {}
    user = user_value if isinstance(user_value, dict) else {}
    observed = str(
        user.get("screen_name")
        or user.get("username")
        or user.get("userName")
        or user.get("handle")
        or row.get("user_screen_name")
        or row.get("user_username")
        or row.get("screen_name")
        or row.get("handle")
        or row.get("username")
        or ""
    ).strip().lstrip("@").casefold()
    if observed:
        return observed
    raw_url = str(row.get("url") or row.get("permalink") or "")
    parts = [part for part in urlparse(raw_url).path.split("/") if part]
    return parts[0].lstrip("@").casefold() if parts else ""


class ApifyActorFreshnessRunner:
    """Execute every configured slot once; never retry an Actor POST."""

    def __init__(
        self,
        store: ServiceStore,
        ops: ApifyActorOpsService,
        client: ApifyClient,
    ) -> None:
        self.store = store
        self.ops = ops
        self.client = client
        self.resilience = ApifyActorResilienceService(
            store,
            workspace_id=ops.workspace_id,
        )

    async def run(self, check_id: str, *, job_id: str) -> dict[str, Any]:
        check = self.resilience.begin_freshness_check(check_id)
        if check.get("job_id") and str(check["job_id"]) != str(job_id):
            self.resilience.fail_freshness_check(
                check_id,
                reason_code="freshness_job_mismatch",
            )
            raise ActorResilienceError(
                "freshness_job_mismatch",
                "Freshness check does not belong to this Job",
            )
        slots = self.store.connect().execute(
            """
            SELECT slot.slot_name, slot.candidate_id, slot.revision_id,
                   candidate.display_name, candidate.state,
                   revision.actor_id, revision.build_number,
                   revision.manifest_json, revision.lifecycle,
                   revision.execution_mode, revision.observed_manifest,
                   revision.security_evidence_json
            FROM apify_route_active_slots AS slot
            JOIN apify_actor_candidates AS candidate
              ON candidate.workspace_id = slot.workspace_id
             AND candidate.id = slot.candidate_id
            JOIN apify_actor_adapter_revisions AS revision
              ON revision.workspace_id = slot.workspace_id
             AND revision.revision_id = slot.revision_id
            WHERE slot.workspace_id = ? AND slot.route_id = ?
              AND candidate.state != 'disabled'
            ORDER BY CASE slot.slot_name
                WHEN 'primary' THEN 0 WHEN 'backup_1' THEN 1 ELSE 2 END
            """,
            (self.ops.workspace_id, str(check["route_id"])),
        ).fetchall()
        if not slots or len(slots) > 3:
            self.resilience.fail_freshness_check(
                check_id,
                reason_code="freshness_route_empty",
            )
            raise ActorResilienceError(
                "freshness_route_empty",
                "Freshness check requires one to three configured Actors",
            )
        if len(slots) != int(check["planned_count"]):
            self.resilience.fail_freshness_check(
                check_id,
                reason_code="freshness_plan_changed",
            )
            raise ActorResilienceError(
                "freshness_plan_changed",
                "Actor Route changed after the freshness plan was created",
            )
        target = reference_target_for_slot(
            str(check["platform"]),
            int(check["reference_slot"]),
        )
        now = _utc_now()
        since = now - timedelta(days=REFERENCE_WINDOW_DAYS)
        key_state = self.store.connect().execute(
            "SELECT generation FROM apify_key_pool_state WHERE workspace_id = ?",
            (self.ops.workspace_id,),
        ).fetchone()
        key_generation = int(key_state["generation"]) if key_state else None
        samples: list[dict[str, Any]] = []
        for row in slots:
            base = {
                "candidate_id": str(row["candidate_id"]),
                "revision_id": str(row["revision_id"]),
                "actor_public_name": str(row["display_name"] or ""),
                "actual_cost_usd": 0.0,
                "cost_final": False,
                "successful": False,
                "timely": False,
                "semantic_outcome": "freshness_actor_failed",
                "reason_code": "freshness_actor_failed",
                "latest_published_at": None,
                "latest_item_id": None,
            }
            try:
                if (
                    str(check["platform"]).casefold() == "x"
                    and (
                        str(row["lifecycle"]) == "legacy_builtin"
                        or str(row["execution_mode"] or "pinned") == "current"
                        or bool(row["observed_manifest"])
                    )
                ):
                    sample = await self._run_controlled_x(
                        row,
                        target=target,
                        since=since,
                        until=now,
                        key_generation=key_generation,
                        logical_run_id=(
                            f"freshness:{check_id}:{row['candidate_id']}"
                        ),
                    )
                else:
                    sample = await self._run_manifest(
                        row,
                        target=target,
                        since=since,
                        until=now,
                        key_generation=key_generation,
                        logical_run_id=(
                            f"freshness:{check_id}:{row['candidate_id']}"
                        ),
                    )
                base.update(sample)
            except Exception as exc:
                code = _safe_error_code(exc)
                base.update(
                    {
                        "semantic_outcome": code,
                        "reason_code": code,
                        "actual_cost_usd": getattr(
                            exc, "actual_charge_usd", 0.0
                        ),
                        "cost_final": bool(getattr(exc, "cost_final", False)),
                    }
                )
            samples.append(base)
        return self.resilience.complete_freshness_check(
            check_id,
            samples=samples,
        )

    async def _run_manifest(
        self,
        row: Any,
        *,
        target: Any,
        since: datetime,
        until: datetime,
        key_generation: int | None,
        logical_run_id: str,
    ) -> dict[str, Any]:
        manifest = parse_actor_manifest(str(row["manifest_json"]))
        runtime = ActorRuntime(
            max_items=REFERENCE_SAMPLE_ITEMS,
            since_iso=since.isoformat(),
            until_iso=until.isoformat(),
        )
        actor_input = render_actor_input(manifest, target, runtime)
        run = await self.client.run_actor_detailed(
            str(row["actor_id"]),
            actor_input,
            max_total_charge_usd=FRESHNESS_PER_ACTOR_CAP_USD,
            logical_run_id=logical_run_id,
            build_number=str(row["build_number"]),
            max_paid_dataset_items=REFERENCE_SAMPLE_ITEMS,
            dataset_item_limit=REFERENCE_SAMPLE_ITEMS + 1,
            expected_pool_generation=key_generation,
            max_remote_starts=1,
            timeout_seconds=actor_canary_timeout_seconds(),
        )
        try:
            mapped = map_actor_output(manifest, run.items, target, runtime)
        except Exception as exc:
            setattr(exc, "actual_charge_usd", run.actual_charge_usd)
            setattr(exc, "cost_final", run.cost_final)
            raise
        return {
            "successful": bool(mapped.latest_published_at and mapped.latest_native_id),
            "timely": mapped.semantic_outcome == "valid_nonempty",
            "semantic_outcome": mapped.semantic_outcome,
            "reason_code": (
                "freshness_sample_valid"
                if mapped.latest_published_at
                else "freshness_nonempty_required"
            ),
            "latest_published_at": mapped.latest_published_at,
            "latest_item_id": mapped.latest_native_id,
            "actual_cost_usd": run.actual_charge_usd,
            "cost_final": run.cost_final,
        }

    async def _run_controlled_x(
        self,
        row: Any,
        *,
        target: Any,
        since: datetime,
        until: datetime,
        key_generation: int | None,
        logical_run_id: str,
    ) -> dict[str, Any]:
        expected_handle = str(target.handle or "").strip().lstrip("@").casefold()
        if not expected_handle:
            raise ActorResilienceError(
                "freshness_reference_invalid",
                "X freshness reference is unavailable",
            )
        sub = ApifySocialSubscriptionConfig(
            platform=ApifySocialPlatform.X,
            kind="profile",
            target=expected_handle,
            fetch_limit=REFERENCE_SAMPLE_ITEMS,
            enabled=True,
        )
        scraper = ApifySocialScraper(
            ApifySocialConfig(
                enabled=True,
                timeout_seconds=actor_canary_timeout_seconds(),
                subscriptions=[sub],
            ),
            self.client.http_client,
            apify_coordinator=self.client.coordinator,
            paid_canary=False,
        )
        security_evidence: dict[str, Any] = {}
        try:
            parsed_evidence = json.loads(
                str(row["security_evidence_json"] or "{}")
            )
            if isinstance(parsed_evidence, dict):
                security_evidence = parsed_evidence
        except (TypeError, ValueError, json.JSONDecodeError):
            security_evidence = {}
        actor_input = scraper._actor_input(
            sub,
            actor_id=str(row["actor_id"]),
            input_dialect=str(
                security_evidence.get("input_dialect")
                or "controlled_default"
            ),
            input_count_field=(
                str(security_evidence["input_count_field"])
                if security_evidence.get("input_count_field")
                else None
            ),
        )
        run = await self.client.run_actor_detailed(
            str(row["actor_id"]),
            actor_input,
            max_total_charge_usd=FRESHNESS_PER_ACTOR_CAP_USD,
            logical_run_id=logical_run_id,
            build_number=(
                str(row["build_number"]) if row["build_number"] else None
            ),
            max_paid_dataset_items=REFERENCE_SAMPLE_ITEMS,
            dataset_item_limit=REFERENCE_SAMPLE_ITEMS + 1,
            expected_pool_generation=key_generation,
            max_remote_starts=1,
            timeout_seconds=actor_canary_timeout_seconds(),
        )
        try:
            candidate_rows, semantic = scraper._validated_x_rows(run.items)
            identity_rows = [
                item
                for item in candidate_rows
                if _observed_x_handle(item) == expected_handle
            ]
            if candidate_rows and not identity_rows:
                raise ActorResilienceError(
                    "apify_actor_identity_mismatch",
                    "Actor freshness output did not prove target identity",
                )
            parsed = scraper._parse_candidate_rows(
                identity_rows,
                sub,
                datetime.min.replace(tzinfo=timezone.utc),
            )
        except Exception as exc:
            setattr(exc, "actual_charge_usd", run.actual_charge_usd)
            setattr(exc, "cost_final", run.cost_final)
            raise
        latest = (
            max(parsed, key=lambda item: (item.published_at, item.id))
            if parsed
            else None
        )
        timely = bool(
            latest is not None
            and since <= latest.published_at <= until
        )
        return {
            "successful": latest is not None,
            "timely": timely,
            "semantic_outcome": (
                "valid_nonempty" if latest is not None else semantic
            ),
            "reason_code": (
                "freshness_sample_valid"
                if latest is not None
                else "freshness_nonempty_required"
            ),
            "latest_published_at": (
                latest.published_at.astimezone(timezone.utc).isoformat()
                if latest is not None
                else None
            ),
            "latest_item_id": latest.id if latest is not None else None,
            "actual_cost_usd": run.actual_charge_usd,
            "cost_final": run.cost_final,
        }


__all__ = [
    "ApifyActorFreshnessRunner",
    "REFERENCE_SAMPLE_ITEMS",
    "REFERENCE_WINDOW_DAYS",
]
