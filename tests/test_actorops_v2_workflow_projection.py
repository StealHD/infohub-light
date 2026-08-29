from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

from src.services.actorops.workflow_projection import (
    replacement_workflow_additions,
    route_workflow_summary,
)


def test_replacement_progress_aggregates_sources_and_cost_without_identity() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE actor_replacement_plans_v2 (
          workspace_id TEXT, plan_id TEXT, status TEXT, error_code TEXT
        );
        CREATE TABLE actor_attempts_v2 (
          workspace_id TEXT, attempt_group_id TEXT, kind TEXT, source_id TEXT,
          status TEXT, semantic_outcome TEXT, cost_final INTEGER,
          actual_cost_usd REAL, created_at TEXT, attempt_id TEXT
        );
        INSERT INTO actor_replacement_plans_v2 VALUES
          ('workspace','plan','running','actorops_replacement_cost_pending');
        INSERT INTO actor_attempts_v2 VALUES
          ('workspace','plan','probe','private-source-1','succeeded','valid_nonempty',1,0.012,'1','a'),
          ('workspace','plan','probe','private-source-2','running',NULL,0,NULL,'2','b');
        """
    )
    repository = SimpleNamespace(connection=connection, workspace_id="workspace")

    result = replacement_workflow_additions(
        repository, "plan", binding_count=2, status="running"
    )

    assert result == {
        "phase": "cost_reconciliation",
        "progress": {
            "verified_bindings": 1,
            "required_bindings": 2,
            "completed_attempts": 1,
            "attempt_count": 2,
            "pending_attempts": 1,
        },
        "cost_summary": {"finalized_usd": 0.012, "pending": True},
    }
    assert "private-source" not in json.dumps(result, sort_keys=True)
    connection.close()


def test_route_workflow_prefers_nonterminal_work_over_latest_terminal_result() -> None:
    completed = {"discovery_id": "completed", "status": "completed"}
    running = {"discovery_id": "running", "status": "running"}
    failed = {"plan_id": "failed", "status": "failed"}
    ready = {"plan_id": "ready", "status": "ready"}

    result = route_workflow_summary(
        [completed, running],
        [failed, ready],
    )

    assert result == {"discovery": running, "replacement": ready}
