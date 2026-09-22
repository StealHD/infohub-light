"""Compile the existing Instagram coauthor compatibility shape to the generic port."""
from dataclasses import replace
from collections.abc import Mapping

from ....apify_actor_manifest import MAX_DATASET_ROWS, actor_manifest_hash, parse_actor_manifest
from ...observed_dataset_schema import observed_dataset_schema
from ...structured_schema import prove_structures
from ...presentation_row_paths import avatar_alias_rank, normalized_key


def legacy_contributors_manifest(rows, manifest):
    """Keep persisted contracts frozen; validate this bounded runtime projection.

    The coauthor collection is an existing platform compatibility contract. Other
    field names still require a schema-proven explicit structures mapping.
    Scalar author paths come from the original manifest and are never rewritten.
    """
    parsed = parse_actor_manifest(manifest.manifest_json)
    if parsed.structures is not None or len(rows) > MAX_DATASET_ROWS:
        return manifest
    if any(len(row) > 512 or any(isinstance(row.get(key), Mapping) and len(row[key]) > 64
                                for key in ("owner", "user")) for row in rows):
        return manifest
    rule = parsed.semantics.identity
    if rule.target_ref != "target.handle" or rule.match != "handle":
        return manifest
    if not any(isinstance(row.get("coauthor_producers"), list)
               and row["coauthor_producers"] for row in rows):
        return manifest
    people = {
        "collection": {"pointers": ["/coauthor_producers"]},
        "handle": {"pointers": ["/username"]},
    }
    schema = observed_dataset_schema([
        {"coauthor_producers": row.get("coauthor_producers", [])} for row in rows
    ])
    structures = {"contributors": people}
    if prove_structures(structures, schema) is not None:
        return manifest
    ranks = avatar_alias_rank("instagram")
    avatar_keys = {key for row in rows for person in (row.get("coauthor_producers") or [])
                   if isinstance(person, Mapping) and len(person) <= 64 for key in person
                   if normalized_key(key) in ranks}
    projections = [("name", "/full_name")] + [
        ("avatar_url", "/" + key.replace("~", "~0").replace("/", "~1"))
        for key in sorted(avatar_keys, key=lambda key: (ranks[normalized_key(key)], key))
    ]
    for field, pointer in projections:
        if field in people:
            continue
        proposal = {"contributors": {**people, field: {"pointers": [pointer]}}}
        if prove_structures(proposal, schema) is None:
            people[field] = {"pointers": [pointer]}
    effective = parse_actor_manifest({
        **parsed.model_dump(mode="json", by_alias=True, exclude_none=True),
        "structures": structures,
    })
    return replace(manifest, manifest_json=effective.model_dump_json(by_alias=True, exclude_none=True),
                   manifest_hash=actor_manifest_hash(effective))
