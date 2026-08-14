"""Read-model projection for durable Actor pool stages."""

from __future__ import annotations

from typing import Any


def load_pool_stage(service: Any, stage_id: str) -> dict[str, Any]:
    """Return one stage with safe source and cost summaries."""

    connection = service.store.connect()
    row = connection.execute(
        """
        SELECT stage_id, route_id, discovery_run_id, initial_batch_id,
               goal, operation_slot, target_slot_count, selection_mode,
               base_generation, base_pool_hash, plan_hash,
               max_total_charge_usd, route_validation_cap_usd,
               target_primary_revision_id,
               target_backup_1_revision_id,
               target_backup_2_revision_id, target_pool_hash,
               status, applied_route_generation, last_error_code,
               created_at, updated_at, applied_at
        FROM apify_actor_pool_stages
        WHERE workspace_id = ? AND stage_id = ?
        """,
        (service.workspace_id, stage_id),
    ).fetchone()
    if row is None:
        from .apify_actor_pool_management import _ops_module

        raise _ops_module().ActorOpsError(
            "apify_actor_pool_stage_not_found",
            "Actor pool stage was not found",
            status_code=404,
        )
    counts = connection.execute(
        """
        SELECT COUNT(*) AS source_count,
               COALESCE(SUM(required_count), 0) AS required_count,
               COALESCE(SUM(passed_count), 0) AS passed_count,
               SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END)
                   AS succeeded_sources,
               SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END)
                   AS failed_sources,
               SUM(CASE WHEN status IN ('queued', 'running') THEN 1 ELSE 0 END)
                   AS active_sources
        FROM apify_actor_pool_stage_sources
        WHERE workspace_id = ? AND stage_id = ?
        """,
        (service.workspace_id, stage_id),
    ).fetchone()
    cost = connection.execute(
        """
        SELECT COALESCE(SUM(CASE
                   WHEN validation.cost_final = 1
                   THEN COALESCE(validation.cost_usd, 0)
                   ELSE 0 END), 0) AS actual_cost_usd,
               COALESCE(SUM(CASE
                   WHEN validation.cost_final = 0
                        AND validation.status IN ('queued', 'running')
                   THEN COALESCE(validation.approved_max_cost_usd, 0)
                   ELSE 0 END), 0) AS reserved_cost_usd,
               COUNT(*) AS validation_count,
               COALESCE(SUM(validation.cost_final), 0) AS final_count
        FROM apify_actor_pool_stage_sources AS source
        JOIN apify_actor_validations AS validation
          ON validation.workspace_id = source.workspace_id
         AND validation.validation_id IN (
             source.primary_validation_id,
             source.backup_1_validation_id,
             source.backup_2_validation_id
         )
        WHERE source.workspace_id = ? AND source.stage_id = ?
        """,
        (service.workspace_id, stage_id),
    ).fetchone()
    result = dict(row)
    result["target_slots"] = {
        "primary": row["target_primary_revision_id"],
        "backup_1": row["target_backup_1_revision_id"],
        "backup_2": row["target_backup_2_revision_id"],
    }
    result["source_summary"] = {
        key: int(counts[key] or 0)
        for key in (
            "source_count", "required_count", "passed_count",
            "succeeded_sources", "failed_sources", "active_sources",
        )
    }
    result["cost_summary"] = {
        "actual_cost_usd": round(float(cost["actual_cost_usd"] or 0), 6),
        "reserved_cost_usd": round(float(cost["reserved_cost_usd"] or 0), 6),
        "validation_count": int(cost["validation_count"] or 0),
        "cost_final": int(cost["validation_count"] or 0) == int(
            cost["final_count"] or 0
        ),
    }
    return result
