"""Bridge Actor-route transitions to safe workspace operational incidents."""

from __future__ import annotations

import logging
from typing import Any

from ..storage.service_store import ServiceStore
from .apify_actor_alerts import ApifyActorAlertService


logger = logging.getLogger(__name__)
_MANUAL_ROUTE_REASONS = frozenset(
    {
        "admin_reorder",
        "admin_enable",
        "admin_disable",
        "initial_policy",
    }
)


class ApifyActorAlertBridge:
    """Translate route events without letting alert failures affect fetching."""

    def __init__(
        self,
        store: ServiceStore,
        alerts: ApifyActorAlertService,
        *,
        workspace_id: str,
    ) -> None:
        self.store = store
        self.alerts = alerts
        self.workspace_id = str(workspace_id)

    def __call__(self, event_type: str, payload: dict[str, Any]) -> None:
        reason = str(payload.get("reason") or "")
        active_actor_name = self._candidate_name(
            payload.get("candidate_id")
        )
        details = {
            "active_actor_name": active_actor_name,
            "reason_code": reason,
        }
        if event_type == "actor_switched":
            if reason in _MANUAL_ROUTE_REASONS:
                return
            self.alerts.open_incident(
                workspace_id=self.workspace_id,
                route_key="x/profile",
                incident_key="route_degraded",
                event_type="actor_switched",
                severity="warning",
                payload=details,
            )
            return
        if event_type == "all_actors_unavailable":
            self.alerts.open_incident(
                workspace_id=self.workspace_id,
                route_key="x/profile",
                incident_key="route_exhausted",
                event_type="route_exhausted",
                severity="critical",
                payload=details,
            )
            return
        if event_type == "budget_blocked":
            incident_key = (
                "quota_exhausted"
                if reason == "quota_exhausted"
                else "budget_blocked"
            )
            self.alerts.open_incident(
                workspace_id=self.workspace_id,
                route_key="x/profile",
                incident_key=incident_key,
                event_type="budget_blocked",
                severity="critical",
                payload=details,
            )
            return
        if event_type == "start_outcome_unknown":
            self.alerts.open_incident(
                workspace_id=self.workspace_id,
                route_key="x/profile",
                incident_key="start_outcome_unknown",
                event_type="start_outcome_unknown",
                severity="critical",
                payload=details,
            )
            return
        if event_type == "route_recovered":
            route_status = str(payload.get("status") or "")
            incident_keys: list[str] = []
            if route_status == "degraded":
                incident_keys.append("route_exhausted")
            elif route_status == "ready":
                incident_keys.extend(("route_exhausted", "route_degraded"))
            if reason == "budget_fuse_released":
                incident_keys.append("budget_blocked")
            if reason == "run_reconciled":
                incident_keys.append("start_outcome_unknown")
            for incident_key in dict.fromkeys(incident_keys):
                self.alerts.resolve_incident(
                    workspace_id=self.workspace_id,
                    route_key="x/profile",
                    incident_key=incident_key,
                    payload={
                        **details,
                        "reason_code": "recovered",
                    },
                )
            return
        if event_type == "actor_recovered":
            if str(payload.get("status") or "") == "ready":
                self.alerts.resolve_incident(
                    workspace_id=self.workspace_id,
                    route_key="x/profile",
                    incident_key="route_degraded",
                    payload={
                        **details,
                        "reason_code": "recovered",
                    },
                )

    def sync_quota_incident(self, route_state: dict[str, Any]) -> None:
        """Open or resolve the low-credit incident from known pool snapshots."""

        row = self.store.connect().execute(
            """
            SELECT
                COUNT(*) AS available,
                COUNT(remaining_included_credits_usd) AS remaining_measured,
                COUNT(monthly_included_credits_usd) AS included_measured,
                SUM(remaining_included_credits_usd) AS remaining,
                SUM(monthly_included_credits_usd) AS included
            FROM apify_key_pool_members
            WHERE workspace_id = ?
              AND status IN ('active', 'standby', 'draining')
            """,
            (self.workspace_id,),
        ).fetchone()
        available = int(row["available"] or 0) if row is not None else 0
        fully_measured = bool(
            available > 0
            and int(row["remaining_measured"] or 0) == available
            and int(row["included_measured"] or 0) == available
        )
        remaining = (
            float(row["remaining"] or 0.0) if fully_measured else None
        )
        included = (
            float(row["included"] or 0.0) if fully_measured else None
        )
        ratio_low = bool(
            remaining is not None
            and included is not None
            and included > 0
            and remaining / included <= 0.20
        )
        quota = (
            route_state.get("quota")
            if isinstance(route_state.get("quota"), dict)
            else {}
        )
        estimated_days = quota.get("estimated_days_remaining")
        days_low = bool(
            isinstance(estimated_days, (int, float))
            and not isinstance(estimated_days, bool)
            and float(estimated_days) < 2
        )
        quota_is_known = bool(
            fully_measured
            or (
                isinstance(estimated_days, (int, float))
                and not isinstance(estimated_days, bool)
            )
        )
        exhausted = bool(
            fully_measured
            and remaining is not None
            and remaining <= 0
        )
        if exhausted:
            self.alerts.open_incident(
                workspace_id=self.workspace_id,
                route_key="x/profile",
                incident_key="quota_exhausted",
                event_type="budget_blocked",
                severity="critical",
                payload={"reason_code": "quota_exhausted"},
            )
        elif fully_measured and remaining is not None and remaining > 0:
            self.alerts.resolve_incident(
                workspace_id=self.workspace_id,
                route_key="x/profile",
                incident_key="quota_exhausted",
                payload={"reason_code": "recovered"},
            )

        if not exhausted and (ratio_low or days_low):
            self.alerts.open_incident(
                workspace_id=self.workspace_id,
                route_key="x/profile",
                incident_key="quota_low",
                event_type="quota_low",
                severity="warning",
                payload={"reason_code": "quota_low"},
            )
        elif quota_is_known and not exhausted:
            self.alerts.resolve_incident(
                workspace_id=self.workspace_id,
                route_key="x/profile",
                incident_key="quota_low",
                payload={"reason_code": "recovered"},
            )

    def _candidate_name(self, candidate_id: Any) -> str:
        if not candidate_id:
            return ""
        row = self.store.connect().execute(
            """
            SELECT display_name
            FROM apify_actor_candidates
            WHERE id = ? AND workspace_id = ? AND route_key = 'x/profile'
            """,
            (str(candidate_id), self.workspace_id),
        ).fetchone()
        return str(row["display_name"]) if row is not None else ""


def build_apify_actor_route(
    store: ServiceStore,
    *,
    data_dir: str,
    workspace_id: str,
    alerts: ApifyActorAlertService | None = None,
):
    """Build one workspace route with its non-blocking incident bridge."""

    from .apify_actor_route import ApifyActorRouteService

    alert_service = alerts or ApifyActorAlertService(
        store,
        data_dir=data_dir,
    )
    bridge = ApifyActorAlertBridge(
        store,
        alert_service,
        workspace_id=workspace_id,
    )
    return ApifyActorRouteService(
        store,
        workspace_id=workspace_id,
        transition_hook=bridge,
        enforce_quota_admission=True,
    )


def sync_apify_actor_quota_alert(
    store: ServiceStore,
    *,
    data_dir: str,
    workspace_id: str,
    route_state: dict[str, Any] | None = None,
    alerts: ApifyActorAlertService | None = None,
) -> None:
    """Synchronize a low-quota incident without making it a fetch dependency."""

    from .apify_actor_route import ApifyActorRouteService

    alert_service = alerts or ApifyActorAlertService(
        store,
        data_dir=data_dir,
    )
    bridge = ApifyActorAlertBridge(
        store,
        alert_service,
        workspace_id=workspace_id,
    )
    state = route_state or ApifyActorRouteService(
        store,
        workspace_id=workspace_id,
    ).public_state()
    bridge.sync_quota_incident(state)
