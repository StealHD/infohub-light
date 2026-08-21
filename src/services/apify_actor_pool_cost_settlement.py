"""Local, proof-based settlement for ActorOps validations that never started.

This lives outside the legacy control-plane module so financial reconciliation
can evolve without extending the historical ActorOps monolith.  The narrow
predicate is intentional: a validation can be settled as zero only when no
logical attempt was ever created and its terminal reason is generated before a
remote Actor start is possible.
"""

from __future__ import annotations

import math
from typing import Any

from .apify_actor_canary_cost_guard import OVER_CAP_CHARGE_CODE


_ZERO_START_TERMINAL_OUTCOMES = frozenset(
    {
        "approval_revoked",
        "revision_not_executable",
    }
)


class ApifyActorPoolCostSettlementMixin:
    """Settle terminal validation costs without contacting Apify again."""

    def settle_validation_charge_above_approved_cap(
        self,
        validation_id: str,
        *,
        attempt_id: str,
        actual_cost_usd: float,
        duration_seconds: int,
    ) -> bool:
        """Fail a running validation when Apify reports an over-cap charge.

        The remote amount is durable cost evidence, not a reason to keep the
        local validation running.  The failed state permanently prevents pool
        activation while preserving the actual cost for audit and budget use.
        """

        actual = float(actual_cost_usd)
        if not math.isfinite(actual) or actual < 0 or actual > 0.20:
            raise ValueError("Actor validation actual cost is outside bounds")
        if int(duration_seconds) < 0:
            raise ValueError("Actor validation duration cannot be negative")
        now = self._now_iso()
        with self._write() as connection:
            validation = connection.execute(
                """
                SELECT status, approved_max_cost_usd
                FROM apify_actor_validations
                WHERE workspace_id = ? AND validation_id = ?
                """,
                (self.workspace_id, validation_id),
            ).fetchone()
            if validation is None:
                raise ValueError("Actor validation was not found")
            approved = float(validation["approved_max_cost_usd"] or 0)
            if actual <= approved + 1e-9:
                return False
            if str(validation["status"]) not in {"queued", "running"}:
                return False
            validation_cursor = connection.execute(
                """
                UPDATE apify_actor_validations
                SET status = 'failed', semantic_outcome = ?, attempt_id = ?,
                    cost_usd = ?, cost_final = 1, counts_toward_canary = 1,
                    duration_seconds = ?, mapped_item_count = 0,
                    completed_at = ?
                WHERE workspace_id = ? AND validation_id = ?
                  AND status IN ('queued', 'running')
                """,
                (
                    OVER_CAP_CHARGE_CODE,
                    attempt_id,
                    actual,
                    int(duration_seconds),
                    now,
                    self.workspace_id,
                    validation_id,
                ),
            )
            if validation_cursor.rowcount != 1:
                return False
            connection.execute(
                """
                UPDATE apify_actor_attempts
                SET status = 'actor_failed', semantic_outcome = ?,
                    actual_cost_usd = ?, cost_final = 1,
                    last_error_code = ?, terminal_at = COALESCE(terminal_at, ?),
                    updated_at = ?
                WHERE workspace_id = ? AND id = ?
                """,
                (
                    OVER_CAP_CHARGE_CODE,
                    actual,
                    OVER_CAP_CHARGE_CODE,
                    now,
                    now,
                    self.workspace_id,
                    attempt_id,
                ),
            )
            connection.execute(
                """
                UPDATE apify_actor_canary_batch_items
                SET status = 'failed', semantic_outcome = ?,
                    actual_cost_usd = ?, cost_final = 1,
                    completed_at = ?, updated_at = ?
                WHERE workspace_id = ? AND validation_id = ?
                """,
                (
                    OVER_CAP_CHARGE_CODE,
                    actual,
                    now,
                    now,
                    self.workspace_id,
                    validation_id,
                ),
            )
        return True

    def reconcile_validation_charge_overages(self) -> int:
        """Repair interrupted over-cap writes from older Worker revisions."""

        rows = self.store.connect().execute(
            """
            SELECT validation.validation_id, validation.attempt_id,
                   attempt.actual_cost_usd
            FROM apify_actor_validations AS validation
            JOIN apify_actor_attempts AS attempt
              ON attempt.workspace_id = validation.workspace_id
             AND attempt.id = validation.attempt_id
            WHERE validation.workspace_id = ?
              AND validation.status IN ('queued', 'running')
              AND validation.attempt_id IS NOT NULL
              AND attempt.cost_final = 1
              AND attempt.actual_cost_usd IS NOT NULL
              AND attempt.actual_cost_usd > validation.approved_max_cost_usd
            ORDER BY validation.created_at, validation.validation_id
            LIMIT 500
            """,
            (self.workspace_id,),
        ).fetchall()
        settled = 0
        for row in rows:
            if self.settle_validation_charge_above_approved_cap(
                str(row["validation_id"]),
                attempt_id=str(row["attempt_id"]),
                actual_cost_usd=float(row["actual_cost_usd"]),
                duration_seconds=0,
            ):
                settled += 1
        return settled

    def reconcile_terminal_no_start_validation_costs(self) -> dict[str, int]:
        """Finalize local no-start and durable over-cap validation evidence.

        An Actor execution always creates a durable attempt before it can call
        Apify.  Consequently, ``attempt_id IS NULL`` together with either of
        the two local pre-start outcomes is proof that no billable Run exists.
        Separately, a finalized remote charge above the approved cap is proof
        that the validation must fail closed; it cannot be treated as pending.
        """

        now = self._now_iso()
        validation_count = self.reconcile_validation_charge_overages()
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
