"""Synthetic families deliberately use names absent from all legacy alias lists."""
import hashlib
import json
from datetime import datetime, timezone
from dataclasses import replace
import pytest

from src.services.apify_actor_manifest import parse_actor_manifest, actor_manifest_hash, ActorManifestError
from src.services.actorops.ports import ActorManifest, FetchWindow, DiscoveryRevision, DiscoveryMapping
from src.services.actorops.adapters.instagram.profile_items import InstagramProfileItemsAdapter
from src.services.actorops.discovery_manifest import validate_schema_proven_manifest
from src.services.actorops.observed_dataset_schema import observed_dataset_schema
from src.services.actorops.structured_schema import prove_structures


def projection(path):
    return {'pointers': [path]}


def document():
    return {
        'version': 1, 'actor_id': 'publisher/arbitrary', 'build_number': '1.0.0',
        'input': {'account': {'$ref': 'target.handle'}},
        'output': {name: {'pointers': [path], 'transforms': transform}
                   for name, path, transform in [
                       ('native_id', '/k1', ['to_string']), ('url', '/k2', ['normalize_url']),
                       ('published_at', '/k3', ['parse_datetime']), ('text', '/k4', ['to_string']),
                       ('author_handle', '/k5', ['to_string'])]},
        'semantics': {'identity': {'output_field': 'author_handle', 'target_ref': 'target.handle',
                                   'match': 'handle'}, 'url_host_allowlist': ['instagram.com']},
        'structures': {'media': {'collection': {'pointers': ['/stuff']}, 'url': projection('')}},
    }


def row(owner='target'):
    return {'k1': 'one', 'k2': 'https://www.instagram.com/p/one/',
            'k3': '2026-09-01T12:00:00Z', 'k4': 'A public post', 'k5': owner,
            'stuff': ['https://cdn.example/1.jpg', 'https://cdn.example/2.jpg', 'https://cdn.example/3.jpg']}


def validate(doc, rows):
    adapter = InstagramProfileItemsAdapter()
    target = adapter.normalize_target({'target': 'target'})
    manifest = ActorManifest('publisher/arbitrary', 'build', '1.0.0', json.dumps(doc), actor_manifest_hash(doc))
    window = FetchWindow(10, datetime(2026, 8, 1, tzinfo=timezone.utc),
                          datetime(2026, 10, 1, tzinfo=timezone.utc))
    return adapter.validate_output(rows, target, manifest, window)


def test_same_photos_via_arbitrary_array_objects_and_nested_wrappers():
    base = row()
    result = validate(document(), [base])
    assert result.items[0].metadata['media_urls'] == base['stuff']
    doc = document()
    doc['structures']['media'] = {'collection': {'pointers': ['/box/*/slides']},
                                 'url': projection('/file/link')}
    nested = {**base, 'box': [{'slides': [{'file': {'link': x}} for x in base['stuff']]}]}
    assert prove_structures(doc['structures'], observed_dataset_schema([nested])) is None
    result = validate(doc, [nested])
    assert result.items[0].metadata['media_urls'] == base['stuff']
    assert result.media_evidence.status == 'observed_multi'


def test_variants_are_one_image_and_video_uses_cover():
    doc = document()
    doc['structures']['media'] = {
        'collection': {'pointers': ['/stuff']}, 'kind': projection('/category'),
        'kind_values': {'image': 'image', 'video': 'video'},
        'url': projection('/file'), 'preview_url': projection('/cover'),
        'variants': {'collection': {'pointers': ['/sizes']}, 'url': projection('/loc'),
                     'width': projection('/w'), 'height': projection('/h')},
    }
    item = row()
    item['stuff'] = [{'category': 'image', 'sizes': [{'loc': f'https://cdn.example/{i}.jpg', 'w': i, 'h': i} for i in range(1, 14)]},
                     {'category': 'video', 'file': 'https://cdn.example/movie.mp4', 'cover': 'https://cdn.example/cover.jpg'}]
    result = validate(doc, [item])
    assert result.items[0].metadata['media_urls'] == ['https://cdn.example/13.jpg', 'https://cdn.example/cover.jpg']
    assert result.items[0].metadata['media_photo_count'] == 1
    assert result.items[0].metadata['media_video_count'] == 1


def test_coauthor_mapping_preserves_real_author_and_target_avatar():
    doc, item = document(), row('brand')
    doc['structures']['contributors'] = {'collection': {'pointers': ['/participants']},
                                         'handle': projection('/account/key'), 'avatar_url': projection('/photo')}
    item['participants'] = [{'account': {'key': 'target'}, 'photo': 'https://cdn.example/target.jpg'}]
    result = validate(doc, [item])
    assert result.items[0].author == 'brand'
    assert result.source_avatar_url == 'https://cdn.example/target.jpg'
    assert result.items[0].metadata['contributors'][0]['handle'] == 'target'
    assert item['k5'] == 'brand'
    item['participants'][0]['account']['key'] = 'stranger'
    with pytest.raises(ActorManifestError, match='requested target'):
        validate(doc, [item])


def test_unknown_identity_never_proven_by_tags_or_invites():
    doc, item = document(), row('brand')
    item['invited'] = [{'id': 'target'}]
    with pytest.raises(ActorManifestError):
        validate(doc, [item])
    doc['structures']['contributors'] = {'collection': {'pointers': ['/invited']}, 'handle': projection('/id')}
    assert prove_structures(doc['structures'], observed_dataset_schema([item])) is not None


def test_invalid_media_is_optional_and_overflow_is_bounded():
    item = row();item['stuff'] = ['file:///private', 'https://cdn.example/movie.mp4']
    result = validate(document(), [item])
    assert result.items and result.media_evidence.status == 'mapping_gap'
    assert result.items[0].metadata['media_urls'] == []
    item['stuff'] = ['https://cdn.example/ok.jpg'] * 101
    assert validate(document(), [item]).media_evidence.status == 'mapping_gap'


def test_declared_missing_media_and_cap():
    doc, item = document(), row()
    doc['structures']['media_count'] = projection('/number')
    item['number'] = 9
    result = validate(doc, [item])
    assert result.media_evidence.status == 'upstream_incomplete'
    item['stuff'] = [f'https://cdn.example/{i}.jpg' for i in range(9)]
    result = validate(doc, [item])
    assert len(result.items[0].metadata['media_urls']) == 6
    assert result.media_evidence.media_count == 9


def test_duplicate_post_with_conflicting_media_cannot_cross_associate():
    a = row();b = {**a, 'stuff': ['https://cdn.example/conflict.jpg']}
    result = validate(document(), [a, b])
    assert all('media_urls' not in item.metadata for item in result.items)
    assert result.media_evidence.status == 'mapping_gap'


def test_unknown_field_spellings_compile_using_exact_schema():
    doc = document()
    schema = {'type': 'object', 'properties': {'account': {'type': 'string', 'description': 'Account username to fetch'}}}
    rev = DiscoveryRevision('publisher/arbitrary', 'publisher', 'build', '1.0.0', 0.01,
                            schema, observed_dataset_schema([row()]))
    text, error = validate_schema_proven_manifest(rev, DiscoveryMapping(json.dumps(doc)))
    assert error is None and text
    doc['structures']['media']['url'] = projection('/invented')
    assert validate_schema_proven_manifest(rev, DiscoveryMapping(json.dumps(doc)))[1]


def test_legacy_manifest_hash_excludes_absent_new_contract():
    doc = document();doc.pop('structures')
    parsed = parse_actor_manifest(doc)
    value = parsed.model_dump(mode='json', by_alias=True, exclude_none=True)
    assert 'structures' not in value
    wire = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    assert actor_manifest_hash(parsed) == hashlib.sha256(wire.encode()).hexdigest()


def test_nested_publications_keep_media_and_contributors_with_their_post():
    from src.services.actorops.adapter_rows import prepare_adapter_rows
    doc = document()
    doc['row_extraction'] = {'mode': 'nested_array', 'pointers': ['/payload']}
    for mapping in doc['output'].values():
        mapping['pointers'] = ['/item' + p for p in mapping['pointers']]
    doc['structures']['media']['collection']['pointers'] = ['/item/stuff']
    adapter = InstagramProfileItemsAdapter()
    target = adapter.normalize_target({'target': 'target'})
    manifest = ActorManifest('publisher/arbitrary', 'build', '1.0.0', json.dumps(doc), actor_manifest_hash(doc))
    second = {**row(), 'k1': 'two', 'k2': 'https://www.instagram.com/p/two/',
              'stuff': ['https://cdn.example/second.jpg']}
    raw = [{'payload': [row(), second], 'irrelevant': ['https://cdn.example/unrelated.jpg']}]
    prepared = prepare_adapter_rows(adapter, raw, target, manifest)
    result = validate(doc, prepared)
    by_id = {item.metadata['native_id']: item.metadata['media_urls'] for item in result.items}
    assert by_id == {'one': row()['stuff'], 'two': second['stuff']}
    assert prove_structures(doc['structures'], {'type': 'object', 'properties': {
        'item': observed_dataset_schema([row(), second])}}) is None


def test_url_or_object_union_and_unknown_variant_keep_other_media():
    doc, item = document(), row()
    doc['structures']['media'] = {
        'collection': {'pointers': ['/stuff'], 'shape': 'array_or_single'},
        'url': {'pointers': ['', '/file']},
    }
    item['stuff'] = ['https://cdn.example/a.jpg', {'file': 'https://cdn.example/b.jpg'}]
    assert prove_structures(doc['structures'], observed_dataset_schema([item])) is None
    assert validate(doc, [item]).items[0].metadata['media_urls'] == [
        'https://cdn.example/a.jpg', 'https://cdn.example/b.jpg']
    doc['structures']['media']['variants'] = {
        'collection': {'pointers': ['/sizes']}, 'url': projection('/file')}
    item['stuff'][1]['sizes'] = {'invalid': 'not an array'}
    result = validate(doc, [item])
    assert result.media_evidence.status == 'mapping_gap'
    assert len(result.items[0].metadata['media_urls']) == 2


@pytest.mark.parametrize('valid_second', [True, False])
def test_observed_ai_mapping_uses_two_bounded_rounds_with_runtime_proof(valid_second):
    import asyncio
    from types import SimpleNamespace
    from src.services.actorops.dataset_adaptation import DatasetAdaptationService
    from src.services.actorops.ports import DiscoveryAiResult
    adapter, doc = InstagramProfileItemsAdapter(), document()
    doc['structures']['contributors'] = {
        'collection': {'pointers': ['/partners']}, 'handle': projection('/login')}
    item = {**row('brand'), 'partners': [{'login': 'target'}]}
    rev = DiscoveryRevision('publisher/arbitrary', 'publisher', 'build', '1.0.0', 0.01,
                            {'type': 'object', 'properties': {'account': {
                                'type': 'string', 'description': 'Account username to fetch'}}}, {})
    calls = []

    class Mapper:
        async def map(self, route, revisions):
            calls.append(revisions[0])
            assert 'cdn.example' not in json.dumps(revisions[0].output_schema)
            proposal = json.loads(json.dumps(doc))
            if len(calls) == 1 or not valid_second:
                # Valid Schema paths, but fails actual target identity validation.
                proposal['structures'].pop('contributors')
            return DiscoveryAiResult(mappings={rev.actor_id: DiscoveryMapping(json.dumps(proposal))})

    service = DatasetAdaptationService(None, None, None, None, ai_mapper=Mapper())
    result = asyncio.run(service._find_manifest(
        adapter, adapter.route_key, rev, [item], adapter.normalize_target({'target': 'target'}),
        FetchWindow(10, datetime(2026, 8, 1, tzinfo=timezone.utc), None),
        SimpleNamespace(actor_id=rev.actor_id, build_id=rev.build_id, build_number=rev.build_number)))
    assert len(calls) == 2
    assert bool(result) is valid_second
    if result:
        batch = validate(json.loads(result), [item])
        assert batch.items[0].author == 'brand'
        assert len(batch.items[0].metadata['media_urls']) == 3
        assert 'avatar_url' not in batch.items[0].metadata['contributors'][0]


def test_uninterpretable_children_are_not_blamed_on_upstream():
    doc, item = document(), row()
    doc['structures']['media_count'] = projection('/number')
    item.update(number=3, stuff=[{'unknown': 'https://cdn.example/exists.jpg'}] * 3)
    assert validate(doc, [item]).media_evidence.status == 'mapping_gap'


def test_empty_structures_keeps_legacy_gallery_and_quality_evidence():
    doc = document()
    doc['structures'] = {}
    item = row()
    item['media_type'] = 'carousel'
    item['childPosts'] = [{'displayUrl': url} for url in item.pop('stuff')]
    result = validate(doc, [item])
    assert len(result.items[0].metadata['media_urls']) == 3
    assert result.media_evidence.status == 'observed_multi'
    item.pop('childPosts')
    item['displayUrl'] = 'https://cdn.example/cover.jpg'
    result = validate(doc, [item])
    assert result.media_evidence.status == 'upstream_incomplete'
