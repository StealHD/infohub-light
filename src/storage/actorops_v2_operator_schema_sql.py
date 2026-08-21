"""DDL for the additive ActorOps v2 operator controls schema."""

OPERATOR_TABLES = (
    "actor_candidate_store_metadata_v2",
    "actor_replacement_plans_v2",
)


SCHEMA_SQL = """
CREATE TABLE actor_candidate_store_metadata_v2 (
    candidate_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    actor_slug TEXT NOT NULL CHECK(length(actor_slug) <= 160),
    display_name TEXT NOT NULL CHECK(length(display_name) <= 160),
    short_description TEXT CHECK(short_description IS NULL OR length(short_description) <= 600),
    developer_name TEXT CHECK(developer_name IS NULL OR length(developer_name) <= 120),
    maintained_by_apify INTEGER NOT NULL DEFAULT 0 CHECK(maintained_by_apify IN (0,1)),
    rating REAL CHECK(rating IS NULL OR (rating >= 0 AND rating <= 5)),
    review_count INTEGER CHECK(review_count IS NULL OR review_count >= 0),
    bookmark_count INTEGER CHECK(bookmark_count IS NULL OR bookmark_count >= 0),
    total_users INTEGER CHECK(total_users IS NULL OR total_users >= 0),
    monthly_active_users INTEGER CHECK(monthly_active_users IS NULL OR monthly_active_users >= 0),
    pricing_json TEXT NOT NULL CHECK(length(pricing_json) <= 4096),
    last_modified_at TEXT,
    observed_at TEXT NOT NULL,
    generation INTEGER NOT NULL DEFAULT 1 CHECK(generation >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(workspace_id, candidate_id)
        REFERENCES actor_candidates_v2(workspace_id, candidate_id) ON DELETE RESTRICT
);
CREATE INDEX idx_actor_store_metadata_v2_workspace
    ON actor_candidate_store_metadata_v2(workspace_id, actor_slug);

CREATE TABLE actor_replacement_plans_v2 (
    plan_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    route_id TEXT NOT NULL,
    target_assignment TEXT NOT NULL CHECK(target_assignment IN ('active','standby')),
    target_priority INTEGER NOT NULL CHECK(target_priority >= 0),
    current_candidate_id TEXT NOT NULL,
    current_candidate_generation INTEGER NOT NULL CHECK(current_candidate_generation >= 1),
    proposed_candidate_id TEXT NOT NULL,
    proposed_candidate_generation INTEGER NOT NULL CHECK(proposed_candidate_generation >= 1),
    pricing_hash TEXT NOT NULL CHECK(length(pricing_hash)=64),
    route_generation INTEGER NOT NULL CHECK(route_generation >= 1),
    binding_set_hash TEXT NOT NULL CHECK(length(binding_set_hash)=64),
    binding_count INTEGER NOT NULL CHECK(binding_count >= 1),
    per_probe_cap_usd REAL NOT NULL CHECK(per_probe_cap_usd > 0 AND per_probe_cap_usd <= 0.20),
    total_cap_usd REAL NOT NULL CHECK(total_cap_usd > 0 AND total_cap_usd <= 0.60),
    status TEXT NOT NULL CHECK(status IN ('previewed','authorized','running','ready','applied','failed','cancelled')),
    idempotency_key TEXT NOT NULL,
    created_by_user_id TEXT NOT NULL,
    error_code TEXT,
    generation INTEGER NOT NULL DEFAULT 1 CHECK(generation >= 1),
    authorized_at TEXT,
    terminal_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(workspace_id, idempotency_key),
    FOREIGN KEY(workspace_id, route_id)
        REFERENCES actor_routes_v2(workspace_id, route_id) ON DELETE RESTRICT,
    FOREIGN KEY(workspace_id, current_candidate_id)
        REFERENCES actor_candidates_v2(workspace_id, candidate_id) ON DELETE RESTRICT,
    FOREIGN KEY(workspace_id, proposed_candidate_id)
        REFERENCES actor_candidates_v2(workspace_id, candidate_id) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX idx_actor_replacement_plans_v2_one_open
    ON actor_replacement_plans_v2(workspace_id, route_id)
    WHERE status IN ('previewed','authorized','running','ready');
CREATE INDEX idx_actor_replacement_plans_v2_due
    ON actor_replacement_plans_v2(workspace_id, status, updated_at, plan_id);
"""


REQUIRED_INDEXES = frozenset({
    "idx_actor_store_metadata_v2_workspace",
    "idx_actor_replacement_plans_v2_one_open",
    "idx_actor_replacement_plans_v2_due",
})
