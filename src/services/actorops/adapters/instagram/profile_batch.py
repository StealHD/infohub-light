"""Keep verified profile posts when a mixed batch lacks some identity evidence."""
from dataclasses import replace

from .....models import SourceType
from ....apify_actor_manifest import ActorManifestError
from .._manifest import validate_and_map


def validate_profile_batch(rows, target, manifest, window):
    def validate(selected):
        return validate_and_map(selected, target, manifest, window,
                                platform='instagram', source_type=SourceType.INSTAGRAM)

    try:
        return rows, validate(rows)
    except ActorManifestError as original:
        if original.code != 'apify_actor_target_identity_mismatch':
            raise
        accepted, rejected = [], 0
        for row in rows:
            try:
                validate((row,))
            except ActorManifestError as error:
                if error.code != 'apify_actor_target_identity_mismatch':
                    raise
                rejected += 1
            else:
                accepted.append(row)
        if not accepted:
            raise original
        batch = validate(accepted)
        if not batch.items:
            raise original
        # Only verified rows may contribute media, avatars, or a source watermark.
        return accepted, replace(batch, rejected_identity_rows=rejected)
