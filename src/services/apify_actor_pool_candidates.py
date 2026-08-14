"""Candidate projections for fixed Actor pool operations."""

from __future__ import annotations

from typing import Any

from .apify_actor_pool_management import _ensure_ops_symbols


def _ensure_module_symbols() -> None:
    ops = _ensure_ops_symbols()
    globals().update(vars(ops))


class ApifyActorPoolCandidatesMixin:
    def _list_pool_candidates_standard(
        self,
        route_id: str,
        *,
        goal: str,
        target_slot: str | None = None,
    ) -> dict[str, Any]:
        """Return safe candidates for a manual pool selection."""

        _ensure_module_symbols()
        connection = self.store.connect()
        route = self._require_route(connection, route_id)
        if blocked := self.pool_candidate_operation_blocker(
            connection, route, goal=goal, target_slot=target_slot
        ):
            return blocked
        if goal == "compatibility_single":
            return self._list_compatibility_candidates(connection, route)
        latest = self._candidate_latest_run(connection, route_id)
        required_count = (
            1
            if goal in {"complete_third", "add_slot", "replace_slot"}
            else 3
            if goal == "upgrade_legacy"
            else int(route["min_runtime_healthy"])
        )
        if latest is None:
            return self._candidate_empty_response(
                route_id=route_id, route=route, goal=goal,
                target_slot=target_slot, required_count=required_count,
            )
        active_rows = self._candidate_active_rows(connection, route_id)
        active_actor_lifecycles = {
            str(row["actor_id"]): str(row["lifecycle"])
            for row in active_rows
        }
        active_actor_ids = set(active_actor_lifecycles)
        rows = (
            self._candidate_upgrade_rows(
                connection,
                route=route,
                route_id=route_id,
                run_id=str(latest["run_id"]),
            )
            if goal == "upgrade_legacy"
            else self._candidate_discovery_rows(
                connection, route=route, run_id=str(latest["run_id"])
            )
        )
        if not rows and goal in {"add_slot", "replace_slot"}:
            rows = self._candidate_upgrade_rows(
                connection,
                route=route,
                route_id=route_id,
                run_id=str(latest["run_id"]),
            )
        candidates: list[dict[str, Any]] = []
        seen_candidates: set[str] = set()
        seen_actors: set[str] = set()
        for row in rows:
            candidate_id, actor_id = str(row["candidate_id"]), str(row["actor_id"])
            if goal == "upgrade_legacy" and actor_id not in active_actor_ids:
                continue
            if candidate_id in seen_candidates or actor_id in seen_actors:
                continue
            seen_candidates.add(candidate_id)
            seen_actors.add(actor_id)
            candidates.append(
                self._candidate_item(
                    connection,
                    route=route,
                    route_id=route_id,
                    goal=goal,
                    row=row,
                    active_ids=active_actor_ids,
                    active_lifecycles=active_actor_lifecycles,
                )
            )
        self._candidate_remembered_failures(
            connection,
            route_id=route_id,
            route=route,
            active_ids=active_actor_ids,
            seen_candidates=seen_candidates,
            seen_actors=seen_actors,
            candidates=candidates,
        )
        if goal == "upgrade_legacy":
            self._candidate_legacy_placeholders(
                latest=latest,
                active_rows=active_rows,
                seen_actors=seen_actors,
                candidates=candidates,
                route=route,
            )
            active_order = {
                str(row["candidate_id"]): index
                for index, row in enumerate(active_rows)
                if row["candidate_id"]
            }
            candidates.sort(
                key=lambda item: (
                    0 if bool(item.get("existing_actor_upgrade")) else 1,
                    active_order.get(str(item["candidate_id"]), len(active_order)),
                )
            )
        return self._candidate_response(
            route_id=route_id,
            route=route,
            goal=goal,
            target_slot=target_slot,
            latest=latest,
            required_count=required_count,
            candidates=candidates,
        )
