"""Initial Bilibili candidates require real proofs before assignment or activation."""

import asyncio
import json
from dataclasses import replace

import pytest

from src.services.actorops.adapters import build_default_registry
from src.services.actorops.domain import AssignmentRole, CandidateLifecycle, ReplacementStatus
from src.services.actorops.replacement import ActorOpsReplacementRunner
from src.services.actorops.ports import RemoteRunResult
from src.services.actorops.repository import ActorOpsConflict, ActorOpsRepository
from src.services.actorops.store_metadata import normalize_store_metadata
from src.storage.bilibili_actor_cutover import apply_cutover
from src.storage.service_store import ServiceStore
from tests.test_bilibili_actor_adapter import KEY, UID, WINDOW, manifest, revision, row
from src.services.actorops.discovery_manifest import validate_schema_proven_manifest
from src.services.actorops.ports import ActorManifest
from src.services.apify_actor_manifest import actor_manifest_hash
from tests.test_bilibili_actor_cutover import _source
from tests.test_actorops_v2_operator_controls import _Catalog, _Remote


def test_discovery_handles_nullable_scalar_fields():
    rev = revision()
    for name in ('url', 'title', 'desc'):
        rev.output_schema['properties'][name]['type'] = ['string', 'null']
    mapped = build_default_registry().require(KEY).map_discovery_manifest(rev)
    assert mapped.manifest_json
    assert json.loads(mapped.manifest_json)['output']['url']['pointers'] == ['/url']


def test_refinement_preserves_invalid_and_structured_proposals_for_strict_validation():
    from src.services.actorops.ports import DiscoveryMapping
    adapter = build_default_registry().require(KEY)
    for raw in ('not-json', '[]', '{"row_extraction":{"mode":"top_level"}}', '{"structures":{"contributors":{}}}'):
        mapping = DiscoveryMapping(raw)
        assert adapter.refine_discovery_mapping(revision(), mapping) is mapping


def test_foreign_videos_never_provide_target_evidence_or_enter_owned_batch():
    from src.services.apify_actor_manifest import ActorManifestError
    adapter = build_default_registry().require(KEY)
    target = adapter.normalize_target({'target':UID})
    foreign = {**row('123'), 'bvid':'BV1gsXHYDEU5','url':'https://www.bilibili.com/video/BV1gsXHYDEU5'}
    batch = adapter.validate_output((foreign,row()),target,manifest(),WINDOW)
    assert len(batch.items) == 1 and batch.items[0].metadata['native_id'] == row()['bvid']
    with pytest.raises(ActorManifestError): adapter.validate_output((foreign,),target,manifest(),WINDOW)


@pytest.mark.parametrize('style', ['snake_case', 'uploader'])
def test_public_video_modes_preserve_owner_proof_and_per_creator_limit(style):
    props = {name: {'type': ['string', 'null']} for name in (
        'bvid', 'content_id', 'url', 'share_url', 'title', 'publish_time', 'publishedAt',
        'author_user_id', 'author_name', 'uploaderId', 'uploaderName', 'userId',
    )}
    if style == 'snake_case':
        props.pop('publishedAt'); props.pop('uploaderId'); props.pop('uploaderName'); props.pop('userId')
        inputs = {'user_id': {'type':'string'}, 'max_items': {'type':'integer'},
                  'operation': {'type':'string','enum':['search_videos','list_user_videos']}}
    else:
        props.pop('author_user_id'); props.pop('author_name'); props.pop('publish_time')
        inputs = {'userUrls': {'type':'array'}, 'maxResultsPerInput': {'type':'integer'},
                  'maxItems': {'type':'integer'}, 'mode': {'type':'string','enum':['users'],'default':'users'}}
    rev = replace(revision(), input_schema={'type':'object','properties':inputs},
                  output_schema={'type':'object','properties':props})
    adapter = build_default_registry().require(KEY)
    mapped, error = validate_schema_proven_manifest(rev, adapter.map_discovery_manifest(rev))
    assert mapped, error
    spec = ActorManifest(rev.actor_id, rev.build_id, rev.build_number, mapped, actor_manifest_hash(mapped))
    actor_input = adapter.build_actor_input(adapter.normalize_target({'target':UID}), spec, WINDOW)
    if style == 'snake_case':
        assert actor_input == {'user_id':UID,'operation':'list_user_videos','max_items':3}
        target = adapter.normalize_target({'target':UID})
        batch = adapter.validate_output(({'content_id':'BV1gsXHYDEU4',
            'share_url':'https://www.bilibili.com/video/BV1gsXHYDEU4','title':'Video',
            'publish_time':1791504000,'author_user_id':UID,'author_name':'UP'},),target,spec,WINDOW)
        assert len(batch.items) == 1
    else:
        assert actor_input == {'userUrls':[f'https://space.bilibili.com/{UID}'],'maxResultsPerInput':3}
        assert json.loads(mapped)['output']['source_native_id']['pointers'] == ['/uploaderId', '/userId']
        assert 'maxItems' not in actor_input  # The profile metadata row must not consume the video quota.
        target = adapter.normalize_target({'target':UID})
        from src.services.actorops.adapter_rows import prepare_adapter_rows
        records = ({'type':'user','userId':UID,'url':target.canonical_url},
                   {'type':'searchResult','uploaderId':UID,'bvid':'BV1gsXHYDEU4',
                    'url':'https://www.bilibili.com/video/BV1gsXHYDEU4','title':'Video',
                    'publishedAt':'2026-10-09T00:00:00Z'})
        batch = adapter.validate_output(prepare_adapter_rows(adapter,records,target,spec),target,spec,WINDOW)
        assert len(batch.items) == 1
        wrong = {**records[1], 'uploaderId':'123','userId':UID}
        from src.services.apify_actor_manifest import ActorManifestError
        with pytest.raises(ActorManifestError):
            adapter.validate_output((wrong,), target, spec, WINDOW)
        legacy = json.loads(mapped)
        legacy['input'].pop('maxResultsPerInput'); legacy['input']['maxItems'] = {'$ref':'runtime.max_items'}
        legacy['output']['source_native_id']['pointers'] = ['/userId']
        from src.services.actorops.ports import DiscoveryMapping
        revised = adapter.refine_discovery_mapping(rev,DiscoveryMapping(json.dumps(legacy)))
        assert json.loads(revised.manifest_json)['input'] == json.loads(mapped)['input']
        assert json.loads(revised.manifest_json)['output']['source_native_id']['pointers'] == ['/uploaderId', '/userId']


def _setup(tmp_path):
    store = ServiceStore(tmp_path)
    store.initialize()
    ids = [_source(store, uid) for uid in ('39627524', '383578614')]
    disabled = _source(store, '123', enabled=False)
    repo = ActorOpsRepository(store.connect(), 'default')
    route_id = repo.connection.execute("SELECT route_id FROM actor_routes_v2 WHERE platform='bilibili'").fetchone()[0]
    m = manifest(actor='publisher/bootstrap')
    with repo.transaction():
        apply_cutover(store)
        repo.create_candidate(candidate_id='bootstrap', route_id=route_id, actor_id=m.actor_id,
            publisher='publisher', build_id=m.build_id, build_number=m.build_number,
            manifest_json=m.manifest_json, manifest_hash=m.manifest_hash,
            input_schema_hash='a'*64, output_schema_hash='b'*64, lifecycle=CandidateLifecycle.STATIC_VALID)
        repo.operator.upsert_metadata('bootstrap', normalize_store_metadata(
            {'actorId':m.actor_id,'title':'Bootstrap','username':'publisher'}, fallback_slug=m.actor_id))
    return store, repo, route_id, ids, disabled


def _plan(repo, route_id):
    with repo.transaction():
        return repo.operator.create_plan(plan_id='initial-primary', route_id=route_id,
            target_assignment=AssignmentRole.ACTIVE, target_priority=0, proposed_candidate_id='bootstrap',
            idempotency_key='bilibili-initial-primary', created_by_user_id='owner',
            per_probe_cap_usd=0.02, total_cap_usd=0.04)


class _BiliRemote(_Remote):
    async def execute(self, request, events):
        self.requests.append(request)
        run_id = f'bootstrap-run-{len(self.requests)}'
        events.starting(secret_ref_id='ref', secret_version=1, pool_generation=1)
        events.registered(remote_run_id=run_id, dataset_id='dataset')
        events.running()
        return RemoteRunResult((row(str(request.actor_input['uid'])),), run_id, 'dataset', 0.001, True)


def test_initial_primary_freezes_pending_bindings_and_proves_both_targets(tmp_path):
    store, repo, route_id, ids, disabled = _setup(tmp_path)
    plan = _plan(repo, route_id)
    assert plan.binding_count == 2
    assert disabled not in {x[0] for x in repo.operator.binding_set(route_id)}
    assert {repo.get_binding(x).status for x in ids} == {'pending'}
    with repo.transaction():
        plan = repo.operator.transition_plan(plan.plan_id, current=plan.status,
                    target=ReplacementStatus.AUTHORIZED, expected_generation=plan.generation)
    remote = _BiliRemote()
    runner = ActorOpsReplacementRunner(repo, build_default_registry(), remote, _Catalog())
    sources = {x:store.get_source(x)['config'] for x in ids}
    asyncio.run(runner.run(plan.plan_id, sources))
    assert len(remote.requests) == 1
    asyncio.run(runner.run(plan.plan_id, sources))
    assert len(remote.requests) == 2
    asyncio.run(runner.run(plan.plan_id, sources))
    assert len(remote.requests) == 2
    plan = repo.operator.get_plan(plan.plan_id)
    assert plan.status is ReplacementStatus.READY
    with repo.transaction():repo.operator.apply_plan(plan.plan_id, expected_generation=plan.generation)
    assert repo.get_candidate('bootstrap').assignment_role is AssignmentRole.ACTIVE
    assert repo.get_route(route_id).runtime_mode.value == 'disabled'
    assert all(not store.get_source(x)['enabled'] for x in ids)
    store.close()


def test_initial_plan_becomes_stale_when_a_pending_target_is_disabled(tmp_path):
    store, repo, route_id, ids, _ = _setup(tmp_path)
    plan = _plan(repo, route_id)
    with repo.transaction():repo.connection.execute("UPDATE actor_source_bindings_v2 SET status='disabled' WHERE source_id=?", (ids[0],))
    with pytest.raises(ActorOpsConflict, match='stale'):
        repo.operator.assert_plan_current(plan)
    store.close()
