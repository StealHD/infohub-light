"""Join canonical media and identities to validated publications by exact identity."""
from dataclasses import replace
from .structured_media import interpret_media
from .structured_identity import contributors, normalized_handle, safe_image_url
from .structured_paths import StructureError
from .capability_evidence import MediaCapabilityEvidence


def enrich_structured_batch(batch, rows, target, manifest, window):
    from ..apify_actor_manifest import parse_actor_manifest, map_actor_output, ActorTarget, ActorRuntime
    parsed = parse_actor_manifest(manifest.manifest_json)
    if parsed.structures is None:
        return batch
    actor_target = ActorTarget(canonical_url=target.canonical_url, native_id=target.native_id,
                               handle=target.handle)
    runtime = ActorRuntime(max_items=100, since_iso=window.since.isoformat(),
                           until_iso=window.until.isoformat() if window.until else None)
    indexed, direct_avatar, contributor_avatar = {}, None, None
    for row in rows[:100]:
        mapped = map_actor_output(parsed, (row,), actor_target, runtime)
        if len(mapped.items) != 1:
            continue
        item = mapped.items[0]
        media = interpret_media(row, parsed.structures)
        try:
            people = contributors(row, parsed.structures)
        except StructureError:
            people = ()
        if normalized_handle(item.author_handle) == normalized_handle(target.handle):
            direct_avatar = direct_avatar or safe_image_url(item.author_avatar_url)
        else:
            contributor_avatar = contributor_avatar or next((p['avatar_url'] for p in people
                                    if normalized_handle(p['handle']) == normalized_handle(target.handle)
                                    and p['avatar_url']), None)
        key = (item.native_id, item.url)
        evidence = (media, people)
        indexed[key] = None if key in indexed and indexed[key] != evidence else evidence
    items, observations = [], []
    for item in batch.items:
        evidence = indexed.get((item.metadata.get('native_id'), str(item.url)))
        metadata = dict(item.metadata)
        if evidence is not None:
            media, people = evidence
            if media is not None:
                metadata.update(media.metadata())
                observations.append(media.evidence)
            if people:
                metadata['contributors'] = [{k: v for k, v in p.items() if k != 'avatar_url'}
                                            for p in people]
        elif parsed.structures.media:
            for key in ('image_url', 'media_urls', 'remote_image_url', 'remote_media_urls'):
                metadata.pop(key, None)
            observations.append(MediaCapabilityEvidence(status='mapping_gap',
                                                       reason='unmapped_media_items'))
        items.append(item.model_copy(update={'metadata': metadata}))
    priority = {'unknown': 0, 'observed_multi': 1, 'mapping_gap': 2, 'upstream_incomplete': 3}
    strongest = max(observations, key=lambda e: priority[e.status], default=MediaCapabilityEvidence())
    strongest = replace(strongest, sample_count=len(observations),
                        media_count=sum(e.media_count for e in observations))
    return replace(batch, items=tuple(items), media_evidence=strongest,
                   source_avatar_url=direct_avatar or contributor_avatar, presentation_evidence=None)
