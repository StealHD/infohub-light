"""Key-pool mutations for authoritative unknown-start recovery evidence."""

from __future__ import annotations

import re
from typing import Any


_REMOTE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_UNKNOWN_START_BLOCK_REASONS = frozenset(
    {
        "start_outcome_unknown",
        "apify_start_outcome_unknown",
        "apify_start_http_outcome_unknown",
        "apify_restart_start_outcome_unknown",
    }
)


class ApifyKeyPoolUnknownStartMixin:
    """Retain a terminal audit row instead of guessing an unregistered start."""

    def confirm_start_not_created(self, lease: Any) -> dict[str, Any]:
        """Release a blocked start only after an empty authenticated window."""

        return self._confirm_unknown_start(lease)

    def confirm_zero_cost_aborted_start(
        self,
        lease: Any,
        remote_run_id: str,
        dataset_id: str | None = None,
    ) -> dict[str, Any]:
        """Record a directly known remote ABORTED/$0 Run and unblock safely.

        The caller must have obtained ``remote_run_id`` from the original POST
        response and verified the exact remote Run is terminal ``ABORTED`` with
        ``usageTotalUsd == 0``.  This method never searches or guesses IDs.
        """

        remote_id = str(remote_run_id or "").strip()
        safe_dataset_id = str(dataset_id or "").strip() or None
        if not _REMOTE_IDENTIFIER.fullmatch(remote_id):
            raise ValueError("remote_run_id is invalid")
        if safe_dataset_id is not None and not _REMOTE_IDENTIFIER.fullmatch(
            safe_dataset_id
        ):
            raise ValueError("dataset_id is invalid")
        return self._confirm_unknown_start(
            lease,
            remote_run_id=remote_id,
            dataset_id=safe_dataset_id,
        )

    def _confirm_unknown_start(
        self,
        lease: Any,
        *,
        remote_run_id: str | None = None,
        dataset_id: str | None = None,
    ) -> dict[str, Any]:
        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now_iso = self._current_time().isoformat()
        known_aborted = remote_run_id is not None
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            run = self._run_for_lease(connection, lease)
            if (
                str(run["status"]) != "start_outcome_unknown"
                or run["remote_run_id"] is not None
                or run["dataset_id"] is not None
            ):
                raise self._unknown_start_lease_error()
            connection.execute(
                """
                UPDATE apify_actor_runs
                SET status = ?, remote_run_id = ?, dataset_id = ?,
                    last_error_code = ?, charge_reserved_usd = 0,
                    charge_actual_usd = 0, charge_final = 1,
                    terminal_at = ?, updated_at = ?
                WHERE id = ? AND status = 'start_outcome_unknown'
                  AND remote_run_id IS NULL AND dataset_id IS NULL
                """,
                (
                    "aborted" if known_aborted else "start_rejected",
                    remote_run_id,
                    dataset_id,
                    (
                        "apify_run_registration_aborted"
                        if known_aborted
                        else "apify_start_not_created"
                    ),
                    now_iso,
                    now_iso,
                    run["id"],
                ),
            )
            self._release_unknown_start_block(connection, run, now_iso)
            if owns_transaction:
                connection.commit()
        except Exception:
            if owns_transaction and connection.in_transaction:
                connection.rollback()
            raise
        result = self.get_run(str(run["id"]))
        if result is None:
            raise LookupError("reconciled Apify reservation not found")
        return result

    @staticmethod
    def _unknown_start_lease_error() -> Exception:
        from .apify_key_pool import ApifyRunLeaseError

        return ApifyRunLeaseError()

    def _release_unknown_start_block(
        self, connection: Any, run: Any, now_iso: str
    ) -> None:
        unresolved = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM apify_actor_runs AS run
                JOIN apify_key_pool_members AS member
                  ON member.workspace_id = run.workspace_id
                 AND member.secret_id = run.secret_id
                WHERE run.workspace_id = ?
                  AND member.role = 'acquisition'
                  AND run.status = 'start_outcome_unknown'
                """,
                (run["workspace_id"],),
            ).fetchone()[0]
        )
        state = self._state_row(connection, str(run["workspace_id"]))
        if (
            unresolved == 0
            and str(state["status"]) == "blocked"
            and str(state["blocked_reason"] or "") in _UNKNOWN_START_BLOCK_REASONS
        ):
            connection.execute(
                """
                UPDATE apify_key_pool_state
                SET generation = generation + 1,
                    status = CASE WHEN active_secret_id IS NULL
                                  THEN 'exhausted' ELSE 'ready' END,
                    blocked_reason = NULL, updated_at = ?
                WHERE workspace_id = ?
                """,
                (now_iso, run["workspace_id"]),
            )


__all__ = ["ApifyKeyPoolUnknownStartMixin"]
