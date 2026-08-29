"""DDL owned by the optional ActorOps candidate presentation sidecar."""

PRESENTATION_TABLE = "actor_candidate_presentation_mappings_v2"


SCHEMA_SQL = """
CREATE TABLE actor_candidate_presentation_mappings_v2 (
    workspace_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    build_id TEXT NOT NULL CHECK(length(build_id) BETWEEN 1 AND 160),
    output_schema_hash TEXT NOT NULL CHECK(length(output_schema_hash) = 64),
    mapping_status TEXT NOT NULL CHECK(mapping_status IN ('ready','missing')),
    avatar_json_pointer TEXT
        CHECK(avatar_json_pointer IS NULL OR (
            length(avatar_json_pointer) BETWEEN 2 AND 512
            AND substr(avatar_json_pointer, 1, 1) = '/'
        )),
    evidence_kind TEXT NOT NULL CHECK(evidence_kind IN ('manifest','schema','observed')),
    generation INTEGER NOT NULL DEFAULT 1 CHECK(generation >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(workspace_id, candidate_id, build_id, output_schema_hash),
    CHECK(
        (mapping_status = 'ready' AND avatar_json_pointer IS NOT NULL)
        OR (mapping_status = 'missing' AND avatar_json_pointer IS NULL)
    ),
    FOREIGN KEY(workspace_id, candidate_id)
        REFERENCES actor_candidates_v2(workspace_id, candidate_id) ON DELETE RESTRICT
);
CREATE INDEX idx_actor_candidate_presentation_mapping_status_v2
    ON actor_candidate_presentation_mappings_v2(
        workspace_id, mapping_status, updated_at, candidate_id
    );
"""


REQUIRED_COLUMNS = frozenset(
    {
        "workspace_id",
        "candidate_id",
        "build_id",
        "output_schema_hash",
        "mapping_status",
        "avatar_json_pointer",
        "evidence_kind",
        "generation",
        "created_at",
        "updated_at",
    }
)
REQUIRED_INDEXES = frozenset(
    {"idx_actor_candidate_presentation_mapping_status_v2"}
)


__all__ = [
    "PRESENTATION_TABLE",
    "REQUIRED_COLUMNS",
    "REQUIRED_INDEXES",
    "SCHEMA_SQL",
]
