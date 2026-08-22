"""Global 29 additive Attempt recovery schema for ActorOps v2."""

ALTER_SQL = (
    "ALTER TABLE actor_attempts_v2 ADD COLUMN logical_job_id TEXT",
    """ALTER TABLE actor_attempts_v2 ADD COLUMN request_schema_version INTEGER
       NOT NULL DEFAULT 1 CHECK(request_schema_version IN (1,2))""",
    "ALTER TABLE actor_attempts_v2 ADD COLUMN request_fingerprint TEXT",
    "ALTER TABLE actor_attempts_v2 ADD COLUMN window_since TEXT",
    "ALTER TABLE actor_attempts_v2 ADD COLUMN window_until TEXT",
    "ALTER TABLE actor_attempts_v2 ADD COLUMN max_items INTEGER CHECK(max_items IS NULL OR max_items > 0)",
    """ALTER TABLE actor_attempts_v2 ADD COLUMN result_state TEXT NOT NULL
       DEFAULT 'pending' CHECK(result_state IN ('pending','observed','validated'))""",
    "ALTER TABLE actor_attempts_v2 ADD COLUMN result_observed_at TEXT",
)

REQUIRED_COLUMNS = {
    "logical_job_id",
    "request_schema_version",
    "request_fingerprint",
    "window_since",
    "window_until",
    "max_items",
    "result_state",
    "result_observed_at",
}

INDEX_SQL = """
CREATE UNIQUE INDEX idx_actor_attempts_v2_logical_candidate
ON actor_attempts_v2 (
    workspace_id,
    logical_job_id,
    coalesce(source_id, ''),
    coalesce(binding_version, 0),
    candidate_id,
    kind
)
WHERE request_schema_version = 2;
"""

TRIGGER_SQL = """
CREATE TRIGGER trg_actor_attempts_v2_request_v2_complete
BEFORE INSERT ON actor_attempts_v2
WHEN NEW.request_schema_version = 2 AND (
    NEW.logical_job_id IS NULL OR NEW.logical_job_id = '' OR
    NEW.request_fingerprint IS NULL OR NEW.request_fingerprint = '' OR
    NEW.window_since IS NULL OR NEW.max_items IS NULL
)
BEGIN
    SELECT RAISE(ABORT, 'ActorOps v2 Attempt request is incomplete');
END;

CREATE TRIGGER trg_actor_attempts_v2_request_immutable
BEFORE UPDATE ON actor_attempts_v2
WHEN NEW.logical_job_id IS NOT OLD.logical_job_id
  OR NEW.request_schema_version IS NOT OLD.request_schema_version
  OR NEW.request_fingerprint IS NOT OLD.request_fingerprint
  OR NEW.window_since IS NOT OLD.window_since
  OR NEW.window_until IS NOT OLD.window_until
  OR NEW.max_items IS NOT OLD.max_items
  OR NEW.attempt_group_id IS NOT OLD.attempt_group_id
  OR NEW.source_id IS NOT OLD.source_id
  OR NEW.binding_version IS NOT OLD.binding_version
  OR NEW.candidate_id IS NOT OLD.candidate_id
  OR NEW.kind IS NOT OLD.kind
BEGIN
    SELECT RAISE(ABORT, 'ActorOps Attempt request identity is immutable');
END;

CREATE TRIGGER trg_actor_attempts_v2_observation_monotonic
BEFORE UPDATE ON actor_attempts_v2
WHEN (OLD.actual_cost_usd IS NOT NULL AND (
        NEW.actual_cost_usd IS NULL OR NEW.actual_cost_usd < OLD.actual_cost_usd
     ))
  OR (OLD.cost_final = 1 AND NEW.cost_final = 0)
  OR (OLD.dataset_id IS NOT NULL AND NEW.dataset_id IS NOT OLD.dataset_id)
  OR (
      CASE OLD.result_state WHEN 'pending' THEN 0 WHEN 'observed' THEN 1 ELSE 2 END
      > CASE NEW.result_state WHEN 'pending' THEN 0 WHEN 'observed' THEN 1 ELSE 2 END
  )
BEGIN
    SELECT RAISE(ABORT, 'ActorOps Attempt observation cannot regress');
END;
"""

REQUIRED_INDEXES = {"idx_actor_attempts_v2_logical_candidate"}
REQUIRED_TRIGGERS = {
    "trg_actor_attempts_v2_request_v2_complete",
    "trg_actor_attempts_v2_request_immutable",
    "trg_actor_attempts_v2_observation_monotonic",
}
