"""Capability observations cannot cause another paid run within one job."""

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from src.services.actorops.capability_evidence import MediaCapabilityEvidence
from src.services.actorops.ports import FetchWindow
from src.services.actorops.repository import ActorOpsRepository
from src.services.actorops.admin_service import ActorOpsAdminService
from src.storage.actor_media_evidence_schema import ready, apply_migration
from scripts.migrate_actor_media_evidence_v48 import preview, migrate
from test_actorops_v2_runtime import _runtime, _Adapter

WINDOW = FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None)


def fetch(runtime, route_id, source_id, job):
    return asyncio.run(runtime.fetch(route_id=route_id, source_id=source_id,
        source_config={'target': 'openai'}, window=WINDOW, logical_job_id=job))


def install_observer(monkeypatch):
    original = _Adapter.validate_output
    def validate(self, rows, target, manifest, window):
        batch = original(self, rows, target, manifest, window)
        bad = manifest.actor_id.endswith('-0')
        evidence = MediaCapabilityEvidence('upstream_incomplete' if bad else 'observed_multi',
            'gallery_cover_only' if bad else 'multiple_media_observed', 1, 1 if bad else 3)
        return replace(batch, media_evidence=evidence)
    monkeypatch.setattr(_Adapter, 'validate_output', validate)


def test_quality_changes_next_job_but_replay_never_pays_again(tmp_path, monkeypatch):
    install_observer(monkeypatch)
    store, repo, runtime, remote, route, source, candidates = _runtime(tmp_path, ['valid_nonempty'] * 3)
    result = fetch(runtime, route, source, 'job-1')
    assert len(remote.requests) == 1 and result.items and result.candidate_id == candidates[0]
    binding, primary = repo.get_binding(source), repo.get_candidate(candidates[0])
    assert repo.media_evidence.summary(binding, primary)['status'] == 'upstream_incomplete'
    assert repo.get_candidate(candidates[0]).last_error_code is None
    # A replay must resume its already paid dataset, despite its lower media rank.
    replay = fetch(runtime, route, source, 'job-1')
    assert replay.items and len(remote.requests) == 1
    assert repo.connection.execute('SELECT COUNT(*) FROM actor_media_evidence_v2').fetchone()[0] == 1
    assert fetch(runtime, route, source, 'job-2').candidate_id == candidates[1]
    assert len(remote.requests) == 2
    detail = ActorOpsAdminService(store, workspace_id=repo.workspace_id).route_detail(route)
    summaries = detail['bindings'][0]['media_capabilities']
    assert {value['status'] for value in summaries} == {'observed_multi', 'upstream_incomplete'}
    assert set(summaries[0]) == {'candidate_id', 'status', 'reason', 'sample_count', 'media_count', 'observed_at'}
    store.close()


def test_evidence_revision_binding_workspace_isolation(tmp_path, monkeypatch):
    install_observer(monkeypatch)
    store, repo, runtime, _, route, source, candidates = _runtime(tmp_path, ['valid_nonempty'])
    fetch(runtime, route, source, 'job')
    binding, candidate = repo.get_binding(source), repo.get_candidate(candidates[0])
    assert repo.media_evidence.rank(binding, candidate) == 2
    for changed in (replace(candidate, build_id='new'), replace(candidate, output_schema_hash='new'),
                    replace(candidate, manifest_hash='new'), replace(candidate, input_schema_hash='new')):
        assert repo.media_evidence.rank(binding, changed) == 1
    assert repo.media_evidence.rank(replace(binding, binding_version=2), candidate) == 1
    assert repo.media_evidence.rank(replace(binding, source_id='other'), candidate) == 1
    other = ActorOpsRepository(repo.connection, 'other-workspace')
    assert other.media_evidence.rank(binding, candidate) == 1
    repo.connection.execute('UPDATE actor_media_evidence_v2 SET parser_version=parser_version+1')
    repo.connection.commit()
    assert repo.media_evidence.rank(binding, candidate) == 1
    store.close()


def test_single_image_does_not_clear_gallery_evidence_and_single_candidate_works(tmp_path, monkeypatch):
    install_observer(monkeypatch)
    store, repo, runtime, remote, route, source, candidates = _runtime(tmp_path, ['valid_nonempty'] * 2, candidate_count=1)
    fetch(runtime, route, source, 'job-1')
    original = _Adapter.validate_output
    monkeypatch.setattr(_Adapter, 'validate_output', lambda *args: replace(original(*args),
                        media_evidence=MediaCapabilityEvidence(sample_count=1, media_count=1)))
    result = fetch(runtime, route, source, 'job-2')
    assert result.items and len(remote.requests) == 2
    assert repo.media_evidence.rank(repo.get_binding(source), repo.get_candidate(candidates[0])) == 2
    store.close()


def remove_migration(conn):
    conn.execute('DROP TABLE actor_media_evidence_v2')
    conn.execute('DROP TABLE actor_output_schema_provenance_v2')
    conn.execute('DELETE FROM schema_migrations WHERE version=48')
    conn.commit()


def test_optional_migration_does_not_block_fetch_and_is_explicit(tmp_path, monkeypatch):
    install_observer(monkeypatch)
    store, repo, runtime, _, route, source, _ = _runtime(tmp_path, ['valid_nonempty'])
    remove_migration(repo.connection)
    assert fetch(runtime, route, source, 'job').items
    store.close()
    # Opening an existing database must not auto-migrate.
    from src.storage.service_store import ServiceStore
    reopened = ServiceStore(tmp_path / 'data')
    reopened.initialize()
    assert not ready(reopened.connect())
    reopened.close()
    assert preview(tmp_path / 'data')['status'] == 'migration_required'
    result = migrate(tmp_path / 'data', tmp_path / 'backups')
    assert result['status'] == 'migrated'
    from pathlib import Path
    assert Path(result['backup']).stat().st_mode & 0o777 == 0o600
    assert preview(tmp_path / 'data')['status'] == 'ready'
    assert migrate(tmp_path / 'data', tmp_path / 'backups')['status'] == 'ready'


def test_migration_rolls_back_partial_ddl(tmp_path, monkeypatch):
    store, repo, *_ = _runtime(tmp_path, [])
    remove_migration(repo.connection)
    import src.storage.actor_media_evidence_schema as schema
    monkeypatch.setattr(schema, 'PROVENANCE_SQL', 'INVALID SQL')
    with pytest.raises(Exception):
        apply_migration(repo.connection)
    assert not ready(repo.connection)
    assert not repo.connection.execute("SELECT 1 FROM sqlite_master WHERE name='actor_media_evidence_v2'").fetchone()
    store.close()


def test_schema_origin_persists_without_raw_schema(tmp_path):
    store, repo, _, _, _, _, candidates = _runtime(tmp_path, [])
    candidate = repo.get_candidate(candidates[0])
    with repo.transaction():
        repo.media_evidence.record_schema_origin(candidate, 'dataset_view')
    assert repo.media_evidence.schema_origin(candidate) == 'dataset_view'
    other = ActorOpsRepository(repo.connection, 'other')
    assert other.media_evidence.schema_origin(candidate) == 'unknown'
    store.close()


@pytest.mark.parametrize(('payload', 'expected'), [
    ({'pictures': ['https://cdn.example/a.jpg', 'https://cdn.example/b.jpg']}, 'observed_multi'),
    ({'pictures': ['https://cdn.example/a.jpg'], 'count': 3}, 'upstream_incomplete'),
    ({'pictures': [{'unknown': 'https://cdn.example/a.jpg'}]}, 'mapping_gap'),
])
def test_generic_interpreter_evidence_reaches_repository_and_admin(tmp_path, monkeypatch, payload, expected):
    from src.services.apify_actor_structures import StructuredOutput
    from src.services.actorops.structured_media import interpret_media
    structures = StructuredOutput.model_validate({
        'media': {'collection': {'pointers': ['/pictures']}, 'url': {'pointers': ['']}},
        'media_count': {'pointers': ['/count']}})
    observation = interpret_media(payload, structures).evidence
    original = _Adapter.validate_output
    def validate(self, rows, target, manifest, window):
        return replace(original(self, rows, target, manifest, window), media_evidence=observation)
    monkeypatch.setattr(_Adapter, 'validate_output', validate)
    store, repo, runtime, remote, route, source, candidates = _runtime(tmp_path, ['valid_nonempty'])
    assert fetch(runtime, route, source, 'structured-job').items
    assert len(remote.requests) == 1
    summary = repo.media_evidence.summary(repo.get_binding(source), repo.get_candidate(candidates[0]))
    assert summary['status'] == expected
    assert summary['reason'] == observation.reason
    detail = ActorOpsAdminService(store, workspace_id=repo.workspace_id).route_detail(route)
    assert detail['bindings'][0]['media_capabilities'][0]['status'] == expected
    store.close()
