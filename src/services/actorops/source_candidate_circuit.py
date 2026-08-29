"""Source-scoped paid execution circuit and half-open singleflight."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any


_HALF_OPEN_LEASE_MINUTES = 15
_BACKOFF_HOURS = (6, 12, 24)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime | None = None) -> str:
    return (value or _now()).astimezone(timezone.utc).isoformat()


class SourceCandidateCircuit:
    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def available(
        self, binding: Any, candidate_id: str, *, logical_job_id: str
    ) -> bool:
        row = self._row(binding, candidate_id)
        if not row or row["state"] != "source_stale" or not row["cooldown_until"]:
            return True
        stamp = _stamp()
        if str(row["cooldown_until"]) > stamp:
            return False
        token = hashlib.sha256(
            "\x1f".join((
                self.repository.workspace_id,
                str(binding.source_id),
                str(candidate_id),
                str(binding.binding_version),
                str(logical_job_id),
            )).encode()
        ).hexdigest()
        lease_until = _stamp(_now() + timedelta(minutes=_HALF_OPEN_LEASE_MINUTES))
        with self.repository.transaction():
            changed = self.repository.connection.execute(
                """UPDATE actor_source_candidate_freshness_v2
                      SET half_open_lease_until=?, half_open_lease_token=?, updated_at=?
                    WHERE workspace_id=? AND source_id=? AND candidate_id=?
                      AND binding_version=? AND cooldown_until<=?
                      AND (half_open_lease_until IS NULL
                           OR half_open_lease_until<=?
                           OR half_open_lease_token=?)""",
                (
                    lease_until, token, stamp, self.repository.workspace_id,
                    binding.source_id, candidate_id, binding.binding_version,
                    stamp, stamp, token,
                ),
            ).rowcount
        return changed == 1

    def has_unsettled_cost(
        self, binding: Any, *, logical_job_id: str
    ) -> bool:
        return self.repository.connection.execute(
            """SELECT 1 FROM actor_attempts_v2
                WHERE workspace_id=? AND route_id=? AND source_id=? AND kind='fetch'
                  AND (status NOT IN ('succeeded','failed','cancelled') OR cost_final=0)
                  AND logical_job_id<>?
                LIMIT 1""",
            (
                self.repository.workspace_id, binding.route_id,
                binding.source_id, logical_job_id,
            ),
        ).fetchone() is not None

    def record_failure(
        self, *, binding: Any, candidate_id: str, outcome: str,
        logical_job_id: str,
    ) -> None:
        with self.repository.transaction():
            self.record_failure_in_transaction(
                binding=binding, candidate_id=candidate_id, outcome=outcome,
                logical_job_id=logical_job_id,
            )

    def record_failure_in_transaction(
        self, *, binding: Any, candidate_id: str, outcome: str,
        logical_job_id: str,
    ) -> None:
        """Advance one circuit inside the caller's settlement transaction."""

        self.repository._require_transaction()
        stamp = _stamp()
        job_id = _safe_job_id(logical_job_id)
        row = self._row(binding, candidate_id)
        if job_id is not None and row and str(row["last_job_id"] or "") == job_id:
            return
        streak = int(row["failure_streak"] or 0) + 1 if row else 1
        delay = _BACKOFF_HOURS[min(streak - 1, len(_BACKOFF_HOURS) - 1)]
        cooldown = _stamp(_now() + timedelta(hours=delay))
        self.repository.connection.execute(
            """INSERT INTO actor_source_candidate_freshness_v2 (
                   workspace_id, source_id, candidate_id, binding_version,
                   consecutive_scheduled_no_advance, state, cooldown_until,
                   last_outcome, last_job_id, last_checked_at, last_confirmed_at,
                   failure_streak, cooldown_reason, half_open_lease_until,
                   half_open_lease_token, created_at, updated_at
               ) VALUES (?,?,?,?,0,'source_stale',?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(workspace_id,source_id,candidate_id,binding_version)
               DO UPDATE SET consecutive_scheduled_no_advance=0,
                   state='source_stale', cooldown_until=excluded.cooldown_until,
                   last_outcome=excluded.last_outcome,
                   last_job_id=excluded.last_job_id,
                   last_checked_at=excluded.last_checked_at,
                   last_confirmed_at=excluded.last_confirmed_at,
                   failure_streak=excluded.failure_streak,
                   cooldown_reason=excluded.cooldown_reason,
                   half_open_lease_until=NULL, half_open_lease_token=NULL,
                   updated_at=excluded.updated_at""",
            (
                self.repository.workspace_id, binding.source_id, candidate_id,
                binding.binding_version, cooldown, outcome,
                job_id, stamp, stamp, streak, outcome,
                None, None, stamp, stamp,
            ),
        )

    def record_success(
        self, *, binding: Any, candidate_id: str, logical_job_id: str
    ) -> None:
        stamp = _stamp()
        with self.repository.transaction():
            self.repository.connection.execute(
                """UPDATE actor_source_candidate_freshness_v2
                      SET state='neutral', cooldown_until=NULL,
                          failure_streak=0, cooldown_reason=NULL,
                          half_open_lease_until=NULL, half_open_lease_token=NULL,
                          last_outcome='execution_success', last_job_id=?,
                          last_checked_at=?, updated_at=?
                    WHERE workspace_id=? AND source_id=? AND candidate_id=?
                      AND binding_version=?""",
                (
                    _safe_job_id(logical_job_id), stamp, stamp,
                    self.repository.workspace_id, binding.source_id,
                    candidate_id, binding.binding_version,
                ),
            )

    def _row(self, binding: Any, candidate_id: str) -> Any | None:
        return self.repository.connection.execute(
            """SELECT * FROM actor_source_candidate_freshness_v2
                WHERE workspace_id=? AND source_id=? AND candidate_id=?
                  AND binding_version=?""",
            (
                self.repository.workspace_id, binding.source_id, candidate_id,
                binding.binding_version,
            ),
        ).fetchone()


def _safe_job_id(value: str) -> str | None:
    text = str(value or "")
    return text if 1 <= len(text) <= 128 and all(
        character.isalnum() or character in "_.:-" for character in text
    ) else None


__all__ = ["SourceCandidateCircuit"]
