"""Offline, safe v1 summary backfill for global 28 metadata rows."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from ..services.actorops.store_metadata import normalize_store_metadata, pricing_json


def backfill_v1_metadata(connection: sqlite3.Connection) -> int:
    """Copy only existing public labels/pricing/quality for exact v2 revisions."""

    stamp = datetime.now(timezone.utc).isoformat()
    rows = connection.execute(
        """SELECT v2.candidate_id, v2.workspace_id, v2.actor_id, v2.publisher,
                  candidate.display_name, revision.pricing_json, revision.security_evidence_json
           FROM actor_candidates_v2 AS v2
           JOIN apify_actor_adapter_revisions AS revision
             ON revision.workspace_id=v2.workspace_id AND revision.revision_id=v2.candidate_id
           JOIN apify_actor_candidates AS candidate
             ON candidate.workspace_id=revision.workspace_id AND candidate.id=revision.candidate_id
           ORDER BY v2.workspace_id, v2.candidate_id"""
    ).fetchall()
    count = 0
    for row in rows:
        evidence = _object(row["security_evidence_json"])
        quality = evidence.get("store_quality") if isinstance(evidence.get("store_quality"), dict) else {}
        pricing = _object(row["pricing_json"])
        source = {
            "actorId": row["actor_id"], "title": row["display_name"], "username": row["publisher"],
            "pricingInfos": pricing.get("pricingInfos", pricing.get("pricing", [])),
            "stats": {
                "rating": quality.get("rating"), "reviewCount": quality.get("rating_count"),
                "totalUsers": quality.get("user_count"),
            },
        }
        metadata = normalize_store_metadata(
            source, fallback_slug=str(row["actor_id"]), fallback_name=str(row["display_name"] or ""),
        )
        connection.execute(
            """INSERT INTO actor_candidate_store_metadata_v2 (
                   candidate_id, workspace_id, actor_slug, display_name, short_description,
                   developer_name, maintained_by_apify, rating, review_count, bookmark_count,
                   total_users, monthly_active_users, pricing_json, last_modified_at,
                   observed_at, generation, created_at, updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row["candidate_id"], row["workspace_id"], metadata.actor_slug, metadata.display_name,
                metadata.short_description, metadata.developer_name, int(metadata.maintained_by_apify),
                metadata.rating, metadata.review_count, metadata.bookmark_count, metadata.total_users,
                metadata.monthly_active_users, pricing_json(metadata), metadata.last_modified_at, stamp,
                1, stamp, stamp,
            ),
        )
        count += 1
    return count


def _object(value: object) -> dict[str, object]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


__all__ = ["backfill_v1_metadata"]
