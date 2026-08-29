"""Expiry and cost-safety rules for explicit Actor replacement plans."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .domain import ReplacementStatus


def has_unsettled_cost(repository: Any, plan_id: str) -> bool:
    return repository.connection.execute(
        """SELECT 1 FROM actor_attempts_v2
           WHERE workspace_id=? AND attempt_group_id=?
             AND (status NOT IN ('succeeded','failed','cancelled') OR cost_final=0)
           LIMIT 1""",
        (repository.workspace_id, plan_id),
    ).fetchone() is not None


def expire_stale_plans(
    operator: Any, *, route_id: str | None = None,
    now: datetime | None = None,
) -> tuple[str, ...]:
    repository = operator.repository
    repository._require_transaction()
    current = _as_utc(now or datetime.now(timezone.utc))
    clauses = [
        "workspace_id=?", "status IN ('previewed','authorized','running','ready')",
    ]
    params: list[object] = [repository.workspace_id]
    if route_id is not None:
        clauses.append("route_id=?")
        params.append(route_id)
    rows = repository.connection.execute(
        f"SELECT * FROM actor_replacement_plans_v2 WHERE {' AND '.join(clauses)} "
        "ORDER BY updated_at, plan_id",
        tuple(params),
    ).fetchall()
    expired: list[str] = []
    for row in rows:
        status = ReplacementStatus(str(row["status"]))
        age = current - _as_utc(datetime.fromisoformat(str(row["updated_at"])))
        plan_id = str(row["plan_id"])
        has_attempt = repository.connection.execute(
            """SELECT 1 FROM actor_attempts_v2
               WHERE workspace_id=? AND attempt_group_id=? LIMIT 1""",
            (repository.workspace_id, plan_id),
        ).fetchone() is not None
        stale = (
            (status is ReplacementStatus.PREVIEWED and age >= timedelta(minutes=30))
            or (
                status is ReplacementStatus.AUTHORIZED and not has_attempt
                and age >= timedelta(minutes=30)
            )
            or (status is ReplacementStatus.READY and age >= timedelta(hours=24))
            or (
                status is ReplacementStatus.RUNNING and age >= timedelta(hours=24)
                and not has_unsettled_cost(repository, plan_id)
            )
        )
        if not stale:
            continue
        operator.transition_plan(
            plan_id, current=status, target=ReplacementStatus.CANCELLED,
            expected_generation=int(row["generation"]),
            error_code="actorops_replacement_expired",
        )
        expired.append(plan_id)
    return tuple(expired)


def _as_utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None else value.astimezone(timezone.utc)
    )


__all__ = ["expire_stale_plans", "has_unsettled_cost"]
