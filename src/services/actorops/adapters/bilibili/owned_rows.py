"""Exclude foreign uploaders only when the Dataset also proves owned videos."""

from ....apify_actor_manifest import parse_actor_manifest, _apply_output_mapping


def owned_video_rows(rows, target, manifest):
    parsed = parse_actor_manifest(manifest.manifest_json)
    identity = parsed.semantics.identity
    if (identity.output_field != "source_native_id" or identity.match != "exact"
            or identity.target_ref != "target.native_id"):
        return rows
    mapping = parsed.output.source_native_id
    if mapping is None:
        return rows
    kept = []
    owned = False
    for row in rows:
        owner = _apply_output_mapping(row, mapping)
        if owner is not None and str(owner) != str(target.native_id):
            continue
        kept.append(row)
        owned = owned or (
            str(owner) == str(target.native_id)
            and _apply_output_mapping(row, parsed.output.native_id) is not None
            and _apply_output_mapping(row, parsed.output.published_at) is not None
        )
    # An unrelated Dataset remains a failure and triggers normal standby rules.
    return kept if owned else rows
