"""DDL constants for the seven-table ActorOps v2 schema."""

V2_TABLES = (
    "actor_routes_v2",
    "actor_candidates_v2",
    "actor_source_bindings_v2",
    "actor_attempts_v2",
    "actor_discovery_jobs_v2",
    "actor_discovery_job_candidates_v2",
    "actor_maintenance_policies_v2",
)


SCHEMA_SQL = """
CREATE TABLE actor_routes_v2 (
    route_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    platform TEXT NOT NULL,
    target_type TEXT NOT NULL,
    capability TEXT NOT NULL,
    runtime_mode TEXT NOT NULL DEFAULT 'disabled'
        CHECK(runtime_mode IN ('disabled','shadow','active')),
    per_run_cap_usd REAL NOT NULL CHECK(per_run_cap_usd > 0),
    generation INTEGER NOT NULL DEFAULT 1 CHECK(generation >= 1),
    source_v1_generation INTEGER NOT NULL CHECK(source_v1_generation >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(workspace_id, route_id),
    UNIQUE(workspace_id, platform, target_type, capability)
);

CREATE TABLE actor_candidates_v2 (
    candidate_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    route_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    publisher TEXT NOT NULL,
    build_id TEXT,
    build_number TEXT,
    manifest_json TEXT,
    manifest_hash TEXT,
    input_schema_hash TEXT,
    output_schema_hash TEXT,
    lifecycle TEXT NOT NULL CHECK(lifecycle IN (
        'discovered','mapping_pending','static_valid','probationary','certified',
        'rejected','quarantined','disabled','superseded'
    )),
    assignment_role TEXT NOT NULL DEFAULT 'inactive'
        CHECK(assignment_role IN ('active','standby','inactive')),
    priority INTEGER,
    generation INTEGER NOT NULL DEFAULT 1 CHECK(generation >= 1),
    last_success_at TEXT,
    last_failure_at TEXT,
    last_error_class TEXT CHECK(last_error_class IS NULL OR last_error_class IN (
        'configuration','target','credential','candidate','remote_unknown','internal'
    )),
    last_error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(workspace_id, candidate_id),
    UNIQUE(workspace_id, route_id, actor_id, build_id, manifest_hash),
    FOREIGN KEY(workspace_id, route_id)
        REFERENCES actor_routes_v2(workspace_id, route_id) ON DELETE RESTRICT,
    CHECK(
        (assignment_role = 'active' AND priority = 0) OR
        (assignment_role = 'standby' AND priority >= 1) OR
        (assignment_role = 'inactive' AND priority IS NULL)
    )
);
CREATE UNIQUE INDEX idx_actor_candidates_v2_active
    ON actor_candidates_v2(workspace_id, route_id)
    WHERE assignment_role = 'active';
CREATE UNIQUE INDEX idx_actor_candidates_v2_standby_priority
    ON actor_candidates_v2(workspace_id, route_id, priority)
    WHERE assignment_role = 'standby';
CREATE INDEX idx_actor_candidates_v2_route
    ON actor_candidates_v2(workspace_id, route_id, assignment_role, priority);

CREATE TABLE actor_source_bindings_v2 (
    binding_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES source_catalog(id) ON DELETE RESTRICT,
    route_id TEXT NOT NULL,
    target_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','ready','disabled')),
    binding_version INTEGER NOT NULL DEFAULT 1 CHECK(binding_version >= 1),
    source_v1_generation INTEGER NOT NULL CHECK(source_v1_generation >= 1),
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
);

CREATE TABLE actor_attempts_v2 (
    attempt_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    route_id TEXT NOT NULL,
    source_id TEXT REFERENCES source_catalog(id) ON DELETE RESTRICT,
    candidate_id TEXT NOT NULL,
    discovery_id TEXT,
    kind TEXT NOT NULL CHECK(kind IN ('fetch','probe')),
    attempt_group_id TEXT NOT NULL,
    attempt_index INTEGER NOT NULL CHECK(attempt_index >= 0),
    route_generation INTEGER NOT NULL CHECK(route_generation >= 1),
    binding_version INTEGER CHECK(binding_version IS NULL OR binding_version >= 1),
    target_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'created','starting','registered','running','start_unknown',
        'succeeded','failed','cancelled'
    )),
    semantic_outcome TEXT,
    failure_class TEXT CHECK(failure_class IS NULL OR failure_class IN (
        'configuration','target','credential','candidate','remote_unknown','internal'
    )),
    error_code TEXT,
    secret_ref_id TEXT,
    secret_version INTEGER CHECK(secret_version IS NULL OR secret_version >= 1),
    pool_generation INTEGER CHECK(pool_generation IS NULL OR pool_generation >= 1),
    remote_run_id TEXT,
    dataset_id TEXT,
    reserved_usd REAL NOT NULL DEFAULT 0 CHECK(reserved_usd >= 0),
    actual_cost_usd REAL CHECK(actual_cost_usd IS NULL OR actual_cost_usd >= 0),
    cost_final INTEGER NOT NULL DEFAULT 0 CHECK(cost_final IN (0,1)),
    generation INTEGER NOT NULL DEFAULT 1 CHECK(generation >= 1),
    created_at TEXT NOT NULL,
    started_at TEXT,
    terminal_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(workspace_id, idempotency_key),
    UNIQUE(workspace_id, remote_run_id),
    FOREIGN KEY(workspace_id, route_id)
        REFERENCES actor_routes_v2(workspace_id, route_id) ON DELETE RESTRICT,
    FOREIGN KEY(workspace_id, candidate_id)
        REFERENCES actor_candidates_v2(workspace_id, candidate_id) ON DELETE RESTRICT,
    FOREIGN KEY(workspace_id, discovery_id)
        REFERENCES actor_discovery_jobs_v2(workspace_id, discovery_id) ON DELETE RESTRICT
);
CREATE INDEX idx_actor_attempts_v2_route_status
    ON actor_attempts_v2(workspace_id, route_id, status, updated_at);

CREATE TABLE actor_discovery_jobs_v2 (
    discovery_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    route_id TEXT NOT NULL,
    trigger_reason TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'queued','running','retry_wait','completed','failed','cancelled'
    )),
    stage TEXT NOT NULL CHECK(stage IN (
        'store_search','metadata','validation','mapping','ranking','persist'
    )),
    stage_attempt INTEGER NOT NULL DEFAULT 0 CHECK(stage_attempt >= 0),
    retry_after TEXT,
    input_fingerprint TEXT NOT NULL,
    checkpoint_hash TEXT,
    search_cursor TEXT,
    query_count INTEGER NOT NULL DEFAULT 0 CHECK(query_count >= 0),
    candidate_count INTEGER NOT NULL DEFAULT 0 CHECK(candidate_count >= 0),
    rejection_count INTEGER NOT NULL DEFAULT 0 CHECK(rejection_count >= 0),
    failure_class TEXT CHECK(failure_class IS NULL OR failure_class IN (
        'configuration','target','credential','candidate','remote_unknown','internal'
    )),
    error_code TEXT,
    ai_config_id TEXT,
    ai_input_tokens INTEGER,
    ai_completion_tokens INTEGER,
    ai_reasoning_tokens INTEGER,
    ai_finish_reason TEXT,
    ai_latency_ms INTEGER,
    ai_response_bytes INTEGER,
    generation INTEGER NOT NULL DEFAULT 1 CHECK(generation >= 1),
    created_at TEXT NOT NULL,
    terminal_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(workspace_id, idempotency_key),
    UNIQUE(workspace_id, discovery_id),
    FOREIGN KEY(workspace_id, route_id)
        REFERENCES actor_routes_v2(workspace_id, route_id) ON DELETE RESTRICT
);
CREATE INDEX idx_actor_discovery_jobs_v2_route
    ON actor_discovery_jobs_v2(workspace_id, route_id, status, updated_at);

CREATE TABLE actor_discovery_job_candidates_v2 (
    workspace_id TEXT NOT NULL,
    discovery_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    rank INTEGER NOT NULL CHECK(rank >= 0),
    status TEXT NOT NULL CHECK(status IN ('pending','accepted','rejected')),
    rejection_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(workspace_id, discovery_id, candidate_id),
    UNIQUE(workspace_id, discovery_id, rank),
    FOREIGN KEY(workspace_id, discovery_id)
        REFERENCES actor_discovery_jobs_v2(workspace_id, discovery_id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id, candidate_id)
        REFERENCES actor_candidates_v2(workspace_id, candidate_id) ON DELETE RESTRICT
);

CREATE TABLE actor_maintenance_policies_v2 (
    policy_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    route_id TEXT,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
    monthly_budget_usd REAL,
    max_probe_usd REAL,
    max_probes_per_utc_day INTEGER,
    auto_add_standby INTEGER,
    auto_replace_non_last INTEGER,
    generation INTEGER NOT NULL DEFAULT 1 CHECK(generation >= 1),
    authorized_by_user_id TEXT,
    authorized_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(workspace_id, route_id)
        REFERENCES actor_routes_v2(workspace_id, route_id) ON DELETE RESTRICT,
    CHECK(enabled = 0 OR (authorized_by_user_id IS NOT NULL AND authorized_at IS NOT NULL)),
    CHECK(
        (route_id IS NULL AND monthly_budget_usd > 0
            AND max_probe_usd IS NULL AND max_probes_per_utc_day IS NULL
            AND auto_add_standby IS NULL AND auto_replace_non_last IS NULL) OR
        (route_id IS NOT NULL AND monthly_budget_usd IS NULL
            AND max_probe_usd > 0 AND max_probes_per_utc_day > 0
            AND auto_add_standby IN (0,1) AND auto_replace_non_last IN (0,1))
    )
);
CREATE UNIQUE INDEX idx_actor_maintenance_policy_v2_workspace
    ON actor_maintenance_policies_v2(workspace_id) WHERE route_id IS NULL;
CREATE UNIQUE INDEX idx_actor_maintenance_policy_v2_route
    ON actor_maintenance_policies_v2(workspace_id, route_id) WHERE route_id IS NOT NULL;
"""


REQUIRED_INDEXES = frozenset(
    {
        "idx_actor_candidates_v2_active",
        "idx_actor_candidates_v2_standby_priority",
        "idx_actor_maintenance_policy_v2_workspace",
        "idx_actor_maintenance_policy_v2_route",
    }
)
