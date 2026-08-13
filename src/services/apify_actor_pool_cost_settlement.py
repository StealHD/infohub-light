"""Local, proof-based settlement for ActorOps validations that never started.

This lives outside the legacy control-plane module so financial reconciliation
can evolve without extending the historical ActorOps monolith.  The narrow
predicate is intentional: a validation can be settled as zero only when no
logical attempt was ever created and its terminal reason is generated before a
remote Actor start is possible.
"""

from __future__ import annotations

from typing import Any


_ZERO_START_TERMINAL_OUTCOMES = frozenset(
    {
        "approval_revoked",
        "revision_not_executable",
    }
)


class ApifyActorPoolCostSettlementMixin:
    """Settle pre-start terminal validations without contacting Apify."""

    def reconcile_terminal_no_start_validation_costs(self) -> dict[str, int]:
        """Finalize only locally-proven, never-started validations at zero.

        An Actor execution always creates a durable attempt before it can call
        Apify.  Consequently, ``attempt_id IS NULL`` together with either of
        the two local pre-start outcomes is proof that no billable Run exists.
        All unknown starts, remote errors, and records with an attempt remain
        unresolved and continue to reserve their approved maximum cost.
        """

        now = self._now_iso()
        validation_count = 0
        batch_item_count = 0
        batch_ids: set[str] = set()
        with self._write() as connection:
            rows = connection.execute(
                """
                SELECT validation.validation_id
                FROM apify_actor_validations AS validation
                WHERE validation.workspace_id = ?
                  AND validation.attempt_id IS NULL
                  AND validation.status IN ('failed', 'cancelled')
                  AND validation.semantic_outcome IN (?, ?)
                  AND validation.cost_final = 0
                ORDER BY validation.completed_at, validation.validation_id
                LIMIT 500
                """,
                (
                    self.workspace_id,
                    *_ZERO_START_TERMINAL_OUTCOMES,
                ),
            ).fetchall()
            for row in rows:
                validation_id = str(row["validation_id"])
                cursor = connection.execute(
                    """
                    UPDATE apify_actor_validations
                    SET cost_usd = 0, cost_final = 1,
                        counts_toward_canary = 0,
                        completed_at = COALESCE(completed_at, ?)
                    WHERE workspace_id = ? AND validation_id = ?
                      AND attempt_id IS NULL AND cost_final = 0
                    """,
                    (now, self.workspace_id, validation_id),
                )
                if cursor.rowcount != 1:
                    continue
                validation_count += 1
                item_rows = connection.execute(
                    """
                    SELECT batch_id
                    FROM apify_actor_canary_batch_items
                    WHERE workspace_id = ? AND validation_id = ?
                    """,
                    (self.workspace_id, validation_id),
                ).fetchall()
                item_cursor = connection.execute(
                    """
                    UPDATE apify_actor_canary_batch_items
                    SET actual_cost_usd = 0, cost_final = 1, updated_at = ?
                    WHERE workspace_id = ? AND validation_id = ?
                    """,
                    (now, self.workspace_id, validation_id),
                )
                batch_item_count += int(item_cursor.rowcount)
                batch_ids.update(str(item["batch_id"]) for item in item_rows)
            for batch_id in batch_ids:
                aggregate = connection.execute(
                    """
                    SELECT COALESCE(SUM(CASE WHEN cost_final = 1
                               THEN COALESCE(actual_cost_usd, 0)
                               ELSE 0 END), 0) AS actual_cost,
                           COUNT(*) AS item_count,
                           COALESCE(SUM(cost_final), 0) AS final_count
                    FROM apify_actor_canary_batch_items
                    WHERE workspace_id = ? AND batch_id = ?
                    """,
                    (self.workspace_id, batch_id),
                ).fetchone()
                connection.execute(
                    """
                    UPDATE apify_actor_canary_batches
                    SET actual_cost_usd = ?, cost_final = ?, updated_at = ?
                    WHERE workspace_id = ? AND batch_id = ?
                    """,
                    (
                        float(aggregate["actual_cost"] or 0),
                        int(
                            int(aggregate["final_count"] or 0)
                            == int(aggregate["item_count"] or 0)
                        ),
                        now,
                        self.workspace_id,
                        batch_id,
                    ),
                )
        return {
            "validations": validation_count,
            "batch_items": batch_item_count,
            "batches": len(batch_ids),
        }
