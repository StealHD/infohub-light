"""User-scoped subscription and Source Health reads for Remote MCP."""

from __future__ import annotations

from typing import Any

from ..services.source_health import SourceHealthService
from ..storage.service_store import ServiceStore


class RemoteMCPSubscriptionReadService:
    def __init__(self, store: ServiceStore) -> None:
        self.store = store
        self.health = SourceHealthService(store)

    def list_subscriptions(
        self,
        *,
        workspace_id: str,
        user_id: str,
        include_disabled: bool = True,
    ) -> dict[str, Any]:
        records = self.store.list_user_subscriptions_with_sources(
            workspace_id=workspace_id,
            user_id=user_id,
            include_disabled_sources=include_disabled,
        )
        schedule_rows = self.store.connect().execute(
            """
            SELECT subscription_id, enabled, interval_minutes, next_run_at,
                   last_enqueued_at, last_skip_reason
            FROM user_source_schedules
            WHERE workspace_id = ? AND user_id = ?
            """,
            (workspace_id, user_id),
        ).fetchall()
        schedules = {str(row["subscription_id"]): row for row in schedule_rows}
        items: list[dict[str, Any]] = []
        for record in records:
            active = bool(
                record["subscription_enabled"] and record["source_enabled"]
            )
            if not include_disabled and not active:
                continue
            schedule = schedules.get(str(record["subscription_id"]))
            items.append(
                {
                    "subscription_id": record["subscription_id"],
                    "source_name": record["display_name"],
                    "source_type": record["type"],
                    "channel": record.get("override_channel")
                    or record.get("default_channel")
                    or "",
                    "topics": record.get("override_topics")
                    or record.get("default_topics")
                    or [],
                    "status": "active" if active else "disabled",
                    "analysis_mode": record["analysis_mode"],
                    "priority": int(record["priority"]),
                    "schedule": {
                        "enabled": bool(schedule["enabled"]) if schedule else False,
                        "interval_minutes": int(schedule["interval_minutes"])
                        if schedule
                        else None,
                        "next_run_at": schedule["next_run_at"] if schedule else None,
                        "last_enqueued_at": schedule["last_enqueued_at"]
                        if schedule
                        else None,
                        "last_skip_reason": schedule["last_skip_reason"]
                        if schedule
                        else None,
                    },
                }
            )
        return {"items": items, "count": len(items)}

    def source_health(self, *, workspace_id: str, user_id: str) -> dict[str, Any]:
        return self.health.user_projection(
            workspace_id=workspace_id,
            user_id=user_id,
        )
