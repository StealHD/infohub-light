"""Table rebuild SQL for global 30 ActorOps v2 single-track state."""

ROUTE_COLUMNS = frozenset(
    {
        "route_id",
        "workspace_id",
        "platform",
        "target_type",
        "capability",
        "runtime_mode",
        "per_run_cap_usd",
        "generation",
        "created_at",
        "updated_at",
    }
)

BINDING_COLUMNS = frozenset(
    {
        "binding_id",
        "workspace_id",
        "source_id",
        "route_id",
        "target_fingerprint",
        "status",
        "binding_version",
        "preferred_candidate_id",
        "last_known_good_candidate_id",
        "last_success_at",
        "watermark_latest_published_at",
        "watermark_item_id_hash",
        "watermark_last_advanced_at",
        "created_at",
        "updated_at",
    }
)

RETIRED_COLUMNS = frozenset({"source_v1_generation"})

ROUTE_TABLE_SQL = """
CREATE TABLE actor_routes_v2_single_track_new (
    route_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    platform TEXT NOT NULL,
    target_type TEXT NOT NULL,
    capability TEXT NOT NULL,
    runtime_mode TEXT NOT NULL DEFAULT 'disabled'
        CHECK(runtime_mode IN ('active','disabled')),
    per_run_cap_usd REAL NOT NULL CHECK(per_run_cap_usd > 0),
    generation INTEGER NOT NULL DEFAULT 1 CHECK(generation >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(workspace_id, route_id),
    UNIQUE(workspace_id, platform, target_type, capability)
)
"""

BINDING_TABLE_SQL = """
CREATE TABLE actor_source_bindings_v2_single_track_new (
    binding_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES source_catalog(id) ON DELETE RESTRICT,
    route_id TEXT NOT NULL,
    target_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','ready','disabled')),
    binding_version INTEGER NOT NULL DEFAULT 1 CHECK(binding_version >= 1),
    preferred_candidate_id TEXT,
    last_known_good_candidate_id TEXT,
    last_success_at TEXT,
    watermark_latest_published_at TEXT,
    watermark_item_id_hash TEXT,
    watermark_last_advanced_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(workspace_id, source_id),
    UNIQUE(workspace_id, binding_id),
    FOREIGN KEY(workspace_id, route_id)
        REFERENCES actor_routes_v2(workspace_id, route_id) ON DELETE RESTRICT,
    FOREIGN KEY(workspace_id, preferred_candidate_id)
        REFERENCES actor_candidates_v2(workspace_id, candidate_id) ON DELETE RESTRICT,
    FOREIGN KEY(workspace_id, last_known_good_candidate_id)
        REFERENCES actor_candidates_v2(workspace_id, candidate_id) ON DELETE RESTRICT
)
"""

TRIGGER_SQL = """
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

CREATE TRIGGER trg_actor_routes_v2_generation
BEFORE UPDATE ON actor_routes_v2 WHEN NEW.generation < OLD.generation
BEGIN SELECT RAISE(ABORT, 'actorops_v2_generation_regression'); END;

CREATE TRIGGER trg_actor_bindings_v2_generation
BEFORE UPDATE ON actor_source_bindings_v2 WHEN NEW.binding_version < OLD.binding_version
BEGIN SELECT RAISE(ABORT, 'actorops_v2_generation_regression'); END;
"""

REQUIRED_TRIGGERS = frozenset(
    {
        "trg_actor_bindings_v2_candidate_route",
        "trg_actor_bindings_v2_candidate_route_update",
        "trg_actor_bindings_v2_generation",
        "trg_actor_routes_v2_generation",
    }
)


__all__ = [
    "BINDING_COLUMNS",
    "BINDING_TABLE_SQL",
    "RETIRED_COLUMNS",
    "ROUTE_COLUMNS",
    "ROUTE_TABLE_SQL",
    "REQUIRED_TRIGGERS",
    "TRIGGER_SQL",
]
