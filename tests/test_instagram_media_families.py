"""Synthetic/document-derived shapes; these are NOT live Actor certifications."""

from dataclasses import replace
import json

import pytest

from src.services.actorops.adapters.instagram.media_inventory import extract_media
from src.services.actorops.adapters.instagram.profile_items import InstagramProfileItemsAdapter
from src.services.actorops.ports import DiscoveryRevision
from src.services.actorops.discovery_manifest import validate_schema_proven_manifest
from src.services.actorops.apify_catalog import _schemas, _schemas_with_origin
from test_instagram_actor_media import row, validated
from test_actorops_v2_presentation_mapping import _repository

URLS = [f'https://cdn.example/slide-{n}.jpg' for n in range(3)]


@pytest.mark.parametrize('family', ['childPosts', 'children', 'carouselMedia', 'sidecarChildren',
                                   'carousel_media', 'mediaDownloadUrl', 'edges', 'images', 'image_urls'])
def test_vendor_families_keep_same_three_slides(family):
    nodes = [{'displayUrl': url} for url in URLS]
    if family == 'edges':
        extra = {'edge_sidecar_to_children': {'edges': [{'node': node} for node in nodes]}}
    elif family in {'images', 'image_urls'}:
        extra = {family: URLS}
    else:
        extra = {family: nodes}
    result = extract_media({'mediaType': 'carousel', 'displayUrl': 'https://cdn.example/cover.jpg', **extra})
    assert [image.url for image in result.images] == URLS
    assert result.evidence.status == 'observed_multi'
    assert result.total_count == 3


@pytest.mark.parametrize('family', ['image_versions', 'displayResources', 'allImageVariants'])
def test_thirteen_renditions_are_one_photo(family):
    candidates = [{'url': f'https://cdn.example/size-{i}.jpg', 'width': i * 10, 'height': i * 10}
                  for i in range(1, 14)]
    media = extract_media({'media_type': 'carousel', family: candidates})
    assert media.total_count == 1 and media.images[0].width == 130
    assert media.evidence.status == 'upstream_incomplete'
    assert media.metadata()['upstream_content_format'] == 'gallery'


def test_unknown_media_objects_preserve_cover_without_blame():
    media = extract_media({'mediaType': 'carousel', 'displayUrl': URLS[0],
                           'mediaDownloadUrl': [{'unmapped': {'url': URLS[1]}}]})
    assert [image.url for image in media.images] == URLS[:1]
    assert media.evidence.status == 'mapping_gap'
    assert extract_media({'images': [{'url': url} for url in URLS]}).total_count == 3


def test_video_downloads_and_post_url_are_never_images():
    media = extract_media({'mediaType': 'video', 'url': 'https://instagram.com/p/post',
                           'mediaDownloadUrl': 'https://cdn.example/video-without-extension'})
    assert not media.images and media.video_count == 1
    media = extract_media({'mediaDownloadUrl': [
        {'type': 'video', 'url': 'https://cdn.example/video', 'displayUrl': URLS[0]},
        {'type': 'image', 'url': URLS[1]}]})
    assert media.video_count == media.photo_count == 1
    assert [image.url for image in media.images] == URLS[:2]


def test_invalid_children_dont_collect_avatars_or_fabricate_total():
    media = extract_media({'carousel_media': [
        {'image': URLS[0]}, {'image': 'javascript:bad'}, {'avatar': URLS[1]},
        {'is_video': True, 'video_url': 'https://cdn.example/a.mp4'}]})
    assert media.total_count == 1 and media.video_count == 1
    assert media.evidence.status == 'mapping_gap'
    assert extract_media({'carousel_media_count': 8, 'children': [{'image': URLS[0]}]}).evidence.status == 'upstream_incomplete'


def test_single_download_and_variant_node():
    assert extract_media({'mediaDownloadUrl': URLS[0]}).images[0].url == URLS[0]
    result = extract_media({'carousel_media': [
        {'image_versions2': {'candidates': [{'url': url, 'width': 100, 'height': 200}]}}
        for url in URLS]})
    assert result.total_count == 3


def test_batch_missing_gallery_wins_and_text_survives(tmp_path):
    store, _, candidate = _repository(tmp_path)
    batch = validated(candidate, [row(images=URLS), row(id='two', mediaType='carousel', displayUrl=URLS[0])])
    assert len(batch.items) == 2 and all(item.content == 'caption' for item in batch.items)
    assert batch.media_evidence.status == 'upstream_incomplete'
    assert batch.media_evidence.sample_count == 2
    # A third duplicate must not undo previously established ambiguity.
    batch = validated(candidate, [row(displayUrl=URLS[0]), row(displayUrl=URLS[1]), row(displayUrl=URLS[1])])
    assert all(not item.metadata.get('media_urls') for item in batch.items)
    store.close()


def revision(input_fields):
    fields = {'id': {'type': 'string'}, 'url': {'type': 'string'}, 'createdAt': {'type': 'string'},
              'text': {'type': 'string'}, 'author': {'type': 'string'}}
    return DiscoveryRevision('vendor/actor', 'vendor', 'build', '1.0.0', 0.01,
        {'type': 'object', 'properties': input_fields}, {'type': 'object', 'properties': fields})


@pytest.mark.parametrize('key,type_', [('username', 'array'), ('username', 'string'),
                                     ('usernames', 'array'), ('profiles', 'string'), ('directUrls', 'array')])
def test_schema_typed_profile_inputs_and_basic_data(key, type_):
    schema = {'type': type_}
    if type_ == 'array':
        schema['items'] = {'type': 'string'}
    rev = revision({key: schema, 'resultsLimit': {'type': 'integer'},
                    'resultsType': {'type': 'string', 'enum': ['posts', 'details']},
                    'dataDetailLevel': {'type': 'string', 'enum': ['basicData', 'detailedData'], 'default': 'detailedData'}})
    adapter = InstagramProfileItemsAdapter()
    mapped = adapter.map_discovery_manifest(rev)
    inputs = json.loads(mapped.manifest_json)['input']
    assert isinstance(inputs[key], list) == (type_ == 'array')
    assert inputs['dataDetailLevel'] == 'basicData' and inputs['resultsType'] == 'posts'
    assert 'resultsLimit' in inputs
    proven, error = validate_schema_proven_manifest(rev, mapped)
    assert proven, error
    plan, error = adapter.map_discovery_input_plan(rev)
    assert plan, error


def test_detail_only_actor_not_deterministically_mapped():
    mapped = InstagramProfileItemsAdapter().map_discovery_manifest(
        revision({'postUrls': {'type': 'array', 'items': {'type': 'string'}}}))
    assert mapped.manifest_json is None


def test_schema_origin_does_not_change_schema_hash_input():
    build = {'inputSchema': {'properties': {'username': {'type': 'string'}}},
             'actorDefinition': {'storages': {'dataset': {'views': {'default': {
                 'display': {'properties': {'displayUrl': {'format': 'image'}}}}}}}}}
    inputs, output, origin = _schemas_with_origin(build)
    assert origin == 'dataset_view'
    assert _schemas(build) == (inputs, output)
    assert 'childPosts' not in output['properties']
    build['datasetSchema'] = {'properties': {'childPosts': {'type': 'array'}}}
    assert _schemas_with_origin(build)[2] == 'declared_fields'


def test_request_object_inputs_and_ai_safety():
    from src.services.actorops.ports import DiscoveryMapping
    adapter = InstagramProfileItemsAdapter()
    rev = revision({'startUrls': {'type': 'array', 'items': {'type': 'object',
        'properties': {'url': {'type': 'string'}}, 'required': ['url']}}})
    mapping = adapter.map_discovery_manifest(rev)
    proven, error = validate_schema_proven_manifest(rev, mapping)
    assert proven, error
    assert json.loads(proven)['input']['startUrls'] == [{'url': {'$ref': 'target.canonical_url'}}]
    detail = replace(rev, input_schema={'properties': {'postUrls': {'type': 'array'}}})
    assert adapter.refine_discovery_mapping(detail, mapping).rejection_code == 'wrong_actor_type'
    rev = revision({'username': {'type': 'string'}, 'resultsType': {'enum': ['posts', 'comments']},
                    'dataDetailLevel': {'enum': ['basicData', 'detailedData']}})
    raw = json.loads(adapter.map_discovery_manifest(rev).manifest_json)
    raw['input'].update(resultsType='comments', dataDetailLevel='detailedData')
    repaired = adapter.refine_discovery_mapping(rev, DiscoveryMapping(json.dumps(raw)))
    inputs = json.loads(repaired.manifest_json)['input']
    assert inputs['resultsType'] == 'posts' and inputs['dataDetailLevel'] == 'basicData'


def test_video_images_are_cover_renditions_not_gallery_evidence():
    media = extract_media({'type': 'Video', 'images': URLS})
    assert media.total_count == media.video_count == 1
    assert media.metadata()['upstream_content_format'] == 'video'
    assert media.evidence.status == 'unknown'


def test_unknown_gallery_container_is_mapping_gap_not_provider_fault():
    media = extract_media({'type': 'Sidecar', 'displayUrl': URLS[0],
                           'galleryItems': [{'unexpectedUrlField': URLS[1]}]})
    assert media.evidence.status == 'mapping_gap'
    assert [image.url for image in media.images] == URLS[:1]
