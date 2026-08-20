"""Monotonic-state and relationship triggers for ActorOps v2."""

TRIGGER_SQL = """
CREATE TRIGGER trg_actor_candidates_v2_immutable
BEFORE UPDATE ON actor_candidates_v2
WHEN NEW.candidate_id != OLD.candidate_id
  OR NEW.workspace_id != OLD.workspace_id OR NEW.route_id != OLD.route_id
  OR NEW.actor_id != OLD.actor_id OR NEW.publisher != OLD.publisher
  OR COALESCE(NEW.build_id,'') != COALESCE(OLD.build_id,'')
  OR COALESCE(NEW.build_number,'') != COALESCE(OLD.build_number,'')
  OR COALESCE(NEW.manifest_json,'') != COALESCE(OLD.manifest_json,'')
  OR COALESCE(NEW.manifest_hash,'') != COALESCE(OLD.manifest_hash,'')
  OR COALESCE(NEW.input_schema_hash,'') != COALESCE(OLD.input_schema_hash,'')
  OR COALESCE(NEW.output_schema_hash,'') != COALESCE(OLD.output_schema_hash,'')
BEGIN SELECT RAISE(ABORT, 'actorops_v2_candidate_immutable'); END;

CREATE TRIGGER trg_actor_candidates_v2_assignment_insert
BEFORE INSERT ON actor_candidates_v2
WHEN NEW.assignment_role IN ('active','standby') AND (
    NEW.lifecycle NOT IN ('probationary','certified')
    OR NEW.build_id IS NULL OR NEW.manifest_hash IS NULL
)
BEGIN SELECT RAISE(ABORT, 'actorops_v2_candidate_not_runnable'); END;

CREATE TRIGGER trg_actor_candidates_v2_assignment_update
BEFORE UPDATE ON actor_candidates_v2
WHEN NEW.assignment_role IN ('active','standby') AND (
    NEW.lifecycle NOT IN ('probationary','certified')
    OR NEW.build_id IS NULL OR NEW.manifest_hash IS NULL
)
BEGIN SELECT RAISE(ABORT, 'actorops_v2_candidate_not_runnable'); END;

CREATE TRIGGER trg_actor_candidates_v2_transition
BEFORE UPDATE OF lifecycle ON actor_candidates_v2
WHEN NEW.lifecycle != OLD.lifecycle AND NOT (
    (OLD.lifecycle = 'discovered' AND NEW.lifecycle IN ('mapping_pending','static_valid','rejected')) OR
    (OLD.lifecycle = 'mapping_pending' AND NEW.lifecycle IN ('static_valid','rejected')) OR
    (OLD.lifecycle = 'static_valid' AND NEW.lifecycle IN ('probationary','rejected','disabled')) OR
    (OLD.lifecycle = 'probationary' AND NEW.lifecycle IN ('certified','quarantined','disabled','superseded')) OR
    (OLD.lifecycle = 'certified' AND NEW.lifecycle IN ('quarantined','disabled','superseded'))
)
BEGIN SELECT RAISE(ABORT, 'actorops_v2_candidate_transition'); END;

CREATE TRIGGER trg_actor_attempts_v2_transition
BEFORE UPDATE OF status ON actor_attempts_v2
WHEN NEW.status != OLD.status AND NOT (
    (OLD.status = 'created' AND NEW.status IN ('starting','cancelled')) OR
    (OLD.status = 'starting' AND NEW.status IN ('registered','start_unknown','failed','cancelled')) OR
    (OLD.status = 'start_unknown' AND NEW.status IN ('registered','failed','cancelled')) OR
    (OLD.status = 'registered' AND NEW.status IN ('running','succeeded','failed','cancelled')) OR
    (OLD.status = 'running' AND NEW.status IN ('succeeded','failed','cancelled'))
)
BEGIN SELECT RAISE(ABORT, 'actorops_v2_attempt_transition'); END;

CREATE TRIGGER trg_actor_discovery_v2_status_transition
BEFORE UPDATE OF status ON actor_discovery_jobs_v2
WHEN NEW.status != OLD.status AND NOT (
    (OLD.status = 'queued' AND NEW.status IN ('running','cancelled')) OR
    (OLD.status = 'running' AND NEW.status IN ('retry_wait','completed','failed','cancelled')) OR
    (OLD.status = 'retry_wait' AND NEW.status IN ('running','failed','cancelled'))
)
BEGIN SELECT RAISE(ABORT, 'actorops_v2_discovery_status_transition'); END;

CREATE TRIGGER trg_actor_discovery_v2_stage_monotonic
BEFORE UPDATE OF stage ON actor_discovery_jobs_v2
WHEN (CASE NEW.stage
    WHEN 'store_search' THEN 0 WHEN 'metadata' THEN 1 WHEN 'validation' THEN 2
    WHEN 'mapping' THEN 3 WHEN 'ranking' THEN 4 WHEN 'persist' THEN 5 END)
   < (CASE OLD.stage
    WHEN 'store_search' THEN 0 WHEN 'metadata' THEN 1 WHEN 'validation' THEN 2
    WHEN 'mapping' THEN 3 WHEN 'ranking' THEN 4 WHEN 'persist' THEN 5 END)
BEGIN SELECT RAISE(ABORT, 'actorops_v2_discovery_stage_regression'); END;

CREATE TRIGGER trg_actor_bindings_v2_candidate_route
BEFORE INSERT ON actor_source_bindings_v2
WHEN (NEW.preferred_candidate_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM actor_candidates_v2 WHERE workspace_id = NEW.workspace_id
          AND route_id = NEW.route_id AND candidate_id = NEW.preferred_candidate_id))
  OR (NEW.last_known_good_candidate_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM actor_candidates_v2 WHERE workspace_id = NEW.workspace_id
          AND route_id = NEW.route_id AND candidate_id = NEW.last_known_good_candidate_id))
BEGIN SELECT RAISE(ABORT, 'actorops_v2_binding_candidate_route'); END;

CREATE TRIGGER trg_actor_bindings_v2_candidate_route_update
BEFORE UPDATE ON actor_source_bindings_v2
WHEN (NEW.preferred_candidate_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM actor_candidates_v2 WHERE workspace_id = NEW.workspace_id
          AND route_id = NEW.route_id AND candidate_id = NEW.preferred_candidate_id))
  OR (NEW.last_known_good_candidate_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM actor_candidates_v2 WHERE workspace_id = NEW.workspace_id
          AND route_id = NEW.route_id AND candidate_id = NEW.last_known_good_candidate_id))
BEGIN SELECT RAISE(ABORT, 'actorops_v2_binding_candidate_route'); END;

CREATE TRIGGER trg_actor_attempts_v2_candidate_route
BEFORE INSERT ON actor_attempts_v2
WHEN NOT EXISTS (SELECT 1 FROM actor_candidates_v2
    WHERE workspace_id = NEW.workspace_id AND route_id = NEW.route_id
      AND candidate_id = NEW.candidate_id)
BEGIN SELECT RAISE(ABORT, 'actorops_v2_attempt_candidate_route'); END;

CREATE TRIGGER trg_actor_discovery_candidates_v2_route
BEFORE INSERT ON actor_discovery_job_candidates_v2
WHEN NOT EXISTS (
    SELECT 1 FROM actor_discovery_jobs_v2 AS job
    JOIN actor_candidates_v2 AS candidate
      ON candidate.workspace_id = job.workspace_id
     AND candidate.route_id = job.route_id
    WHERE job.workspace_id = NEW.workspace_id
      AND job.discovery_id = NEW.discovery_id
      AND candidate.candidate_id = NEW.candidate_id
)
BEGIN SELECT RAISE(ABORT, 'actorops_v2_discovery_candidate_route'); END;

CREATE TRIGGER trg_actor_routes_v2_generation
BEFORE UPDATE ON actor_routes_v2 WHEN NEW.generation < OLD.generation
BEGIN SELECT RAISE(ABORT, 'actorops_v2_generation_regression'); END;
CREATE TRIGGER trg_actor_candidates_v2_generation
BEFORE UPDATE ON actor_candidates_v2 WHEN NEW.generation < OLD.generation
BEGIN SELECT RAISE(ABORT, 'actorops_v2_generation_regression'); END;
CREATE TRIGGER trg_actor_bindings_v2_generation
BEFORE UPDATE ON actor_source_bindings_v2 WHEN NEW.binding_version < OLD.binding_version
BEGIN SELECT RAISE(ABORT, 'actorops_v2_generation_regression'); END;
CREATE TRIGGER trg_actor_attempts_v2_generation
BEFORE UPDATE ON actor_attempts_v2 WHEN NEW.generation < OLD.generation
BEGIN SELECT RAISE(ABORT, 'actorops_v2_generation_regression'); END;
CREATE TRIGGER trg_actor_discovery_v2_generation
BEFORE UPDATE ON actor_discovery_jobs_v2 WHEN NEW.generation < OLD.generation
BEGIN SELECT RAISE(ABORT, 'actorops_v2_generation_regression'); END;
CREATE TRIGGER trg_actor_policies_v2_generation
BEFORE UPDATE ON actor_maintenance_policies_v2 WHEN NEW.generation < OLD.generation
BEGIN SELECT RAISE(ABORT, 'actorops_v2_generation_regression'); END;
"""


REQUIRED_TRIGGERS = frozenset(
    {
        "trg_actor_candidates_v2_immutable",
        "trg_actor_candidates_v2_assignment_update",
        "trg_actor_candidates_v2_transition",
        "trg_actor_attempts_v2_transition",
        "trg_actor_discovery_v2_status_transition",
        "trg_actor_discovery_v2_stage_monotonic",
        "trg_actor_bindings_v2_candidate_route",
        "trg_actor_attempts_v2_candidate_route",
        "trg_actor_discovery_candidates_v2_route",
        "trg_actor_routes_v2_generation",
    }
)
