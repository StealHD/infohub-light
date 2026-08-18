"""Safe YouTube fallback from an opaque Store schema to one observed probe."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from .apify_actor_manifest import actor_manifest_hash
from .apify_actor_discovery_pricing import safe_pricing_summary


YOUTUBE_OBSERVATION_POLICY = "youtube_observation_probe_v1"


def observation_probe_eligible(
    *,
    platform: str,
    target_type: str,
    capability: str,
    output_schema_proves_items: bool,
) -> bool:
    """Allow only YouTube item Builds whose input still passed free checks."""

    return (
        (platform, target_type, capability) == ("youtube", "channel", "items")
        and not output_schema_proves_items
    )


def output_schema_supports_youtube_item_contract(
    schema: Mapping[str, Any],
) -> bool:
    """Keep ordinary schema-backed manifests on the normal, free path."""

    properties = schema.get("properties")
    fields = properties if isinstance(properties, Mapping) else schema
    names = {
        re.sub(r"[^a-z0-9]+", "", str(name).casefold())
        for name, value in fields.items()
        if isinstance(name, str) and isinstance(value, Mapping)
    }
    return all((
        names & {"id", "videoid", "videoids"},
        names & {"url", "videourl", "link"},
        names & {"published", "publishedat", "date", "createdat", "timestamp"},
        names & {"title", "text", "description", "caption"},
        names & {"channelid", "authorid", "ownerid", "channelhandle", "authorhandle"},
    ))


def observation_probe_manifest(
    *, actor_id: str, build_number: str, input_template: Mapping[str, Any]
) -> dict[str, Any]:
    """Create a value-free manifest; Canary may replace it only with evidence."""

    return {
        "version": 1,
        "actor_id": actor_id,
        "build_number": build_number,
        "input": dict(input_template),
        "output": {
            "native_id": {"pointers": ["/__probe_native_id"]},
            "url": {"pointers": ["/__probe_url"]},
            "published_at": {"pointers": ["/__probe_published_at"]},
            "title": {"pointers": ["/__probe_title"]},
            "source_native_id": {"pointers": ["/__probe_source_native_id"]},
        },
        "semantics": {
            "identity": {
                "output_field": "source_native_id",
                "target_ref": "target.native_id",
                "match": "exact",
            },
            "url_host_allowlist": ["youtube.com", "youtu.be"],
        },
    }


def observation_probe_evidence_fingerprint(evidence_fingerprint: str) -> str:
    """Separate an observed-probe evaluation from old schema-only evidence."""

    return hashlib.sha256(
        f"{YOUTUBE_OBSERVATION_POLICY}:{evidence_fingerprint}".encode("ascii")
    ).hexdigest()


def observation_probe_manifest_hash(
    *, actor_id: str, build_number: str, input_template: Mapping[str, Any]
) -> str:
    """Fingerprint the exact paid probe contract, not only its Build schema."""

    return actor_manifest_hash(
        observation_probe_manifest(
            actor_id=actor_id,
            build_number=build_number,
            input_template=input_template,
        )
    )


def observation_probe_deterministic_failure(
    connection: Any,
    *,
    workspace_id: str,
    route_id: str,
    candidate_id: str,
    actor_id: str,
    build_id: str,
    build_number: str,
    input_schema_hash: str,
    output_schema_hash: str,
    manifest_hash: str,
    pricing: Mapping[str, Any],
) -> str | None:
    """Return a paid terminal result only when its free evidence still matches."""

    failures = {
        "apify_actor_contract_mismatch",
        "apify_actor_identity_mismatch",
        "apify_actor_target_identity_mismatch",
        "apify_actor_metadata_only",
    }
    rows = connection.execute(
        """
        SELECT validation.semantic_outcome, revision.pricing_json
        FROM apify_actor_validations AS validation
        JOIN apify_actor_adapter_revisions AS revision
          ON revision.workspace_id = validation.workspace_id
         AND revision.revision_id = validation.revision_id
        WHERE validation.workspace_id = ? AND validation.route_id = ?
          AND validation.kind = 'route_reference' AND validation.status = 'failed'
          AND validation.cost_final = 1 AND revision.candidate_id = ?
          AND revision.actor_id = ? AND revision.build_id = ?
          AND revision.build_number = ? AND revision.input_schema_hash = ?
          AND revision.output_schema_hash = ?
          AND revision.manifest_hash = ?
        ORDER BY validation.completed_at DESC, validation.validation_id DESC
        """,
        (
            workspace_id, route_id, candidate_id, actor_id, build_id,
            build_number, input_schema_hash, output_schema_hash, manifest_hash,
        ),
    ).fetchall()
    for row in rows:
        reason = str(row["semantic_outcome"] or "")
        try:
            observed_pricing = json.loads(str(row["pricing_json"] or "{}"))
        except json.JSONDecodeError:
            continue
        if reason in failures and observed_pricing == dict(pricing):
            return reason
    return None


def candidate_observation_probe_failure(
    connection: Any,
    *,
    workspace_id: str,
    route_id: str,
    candidate_id: str,
    candidate: Any,
) -> str | None:
    """Find an unchanged opaque-YouTube Build's settled terminal result."""

    return observation_probe_deterministic_failure(
        connection,
        workspace_id=workspace_id,
        route_id=route_id,
        candidate_id=candidate_id,
        actor_id=str(candidate.actor_id),
        build_id=str(candidate.build_id),
        build_number=str(candidate.build_number),
        input_schema_hash=_mapping_hash(candidate.input_schema),
        output_schema_hash=_mapping_hash(candidate.output_schema),
        manifest_hash=observation_probe_manifest_hash(
            actor_id=str(candidate.actor_id),
            build_number=str(candidate.build_number),
            input_template=candidate.input_template,
        ),
        pricing=safe_pricing_summary(candidate.pricing),
    )


def _mapping_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(value), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "YOUTUBE_OBSERVATION_POLICY",
    "candidate_observation_probe_failure",
    "observation_probe_evidence_fingerprint",
    "observation_probe_deterministic_failure",
    "observation_probe_eligible",
    "observation_probe_manifest",
    "observation_probe_manifest_hash",
    "output_schema_supports_youtube_item_contract",
]
