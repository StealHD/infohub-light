"""Synthetic posts reproduce the observed 2 owned / 1 unproven-author batch.

The real Actor returned flat dotted author keys and no coauthor evidence. URLs,
identifiers, names and dates here are synthetic, not a stored raw Dataset.
"""
from copy import deepcopy
import pytest

from src.services.apify_actor_manifest import ActorManifestError
from tests.test_actorops_structured_mapping import document, row, validate


@pytest.mark.parametrize('author_pointer', ['/user.username', '/unfamiliar_author'])
def test_unproven_row_does_not_discard_owned_posts_or_mix_media(author_pointer):
    doc = document()
    doc['output']['author_handle']['pointers'] = [author_pointer]
    rows = [row(), {**row('brand'), 'k1': 'two', 'k2': 'https://www.instagram.com/p/two/',
                   'k3': '2026-09-02T12:00:00Z', 'username_scrape': 'target',
                   'stuff': ['https://cdn.example/foreign.jpg']},
            {**row(), 'k1': 'three', 'k2': 'https://www.instagram.com/p/three/'}]
    for item in rows:
        item[author_pointer[1:]] = item.pop('k5')
    before = deepcopy(rows)
    batch = validate(doc, rows)
    assert batch.semantic_outcome == 'valid_nonempty'
    assert {item.metadata['native_id'] for item in batch.items} == {'one', 'three'}
    assert batch.rejected_identity_rows == 1
    assert batch.latest_published_at.startswith('2026-09-01')
    assert all('foreign.jpg' not in str(item.metadata) for item in batch.items)
    assert rows == before


@pytest.mark.parametrize('kind', ['only_foreign', 'malformed', 'unsafe_url', 'control_error'])
def test_partial_batch_does_not_hide_unavailable_target_or_invalid_contract(kind):
    foreign = {**row('brand'), 'k1': 'two', 'k2': 'https://www.instagram.com/p/two/'}
    rows = [row(), foreign]
    if kind == 'only_foreign':
        rows = [foreign]
    elif kind == 'malformed':
        foreign.pop('k3')
    elif kind == 'unsafe_url':
        foreign['k2'] = 'https://untrusted.example/post'
    elif kind == 'control_error':
        rows.append({'error': 'Account is private'})
    with pytest.raises(ActorManifestError):
        validate(document(), rows)


def test_declared_contributor_membership_still_accepts_real_collaboration():
    doc = document()
    doc['structures']['contributors'] = {
        'collection': {'pointers': ['/people']}, 'handle': {'pointers': ['/handle']},
    }
    collaborative = {**row('brand'), 'k1': 'two', 'k2': 'https://www.instagram.com/p/two/',
                     'people': [{'handle': 'target'}]}
    batch = validate(doc, [row(), collaborative])
    assert len(batch.items) == 2 and batch.rejected_identity_rows == 0
    assert next(item for item in batch.items if item.metadata['native_id'] == 'two').author == 'brand'


def test_runtime_keeps_partial_content_with_diagnostic_and_no_fallback_run(tmp_path):
    import asyncio
    import json
    from dataclasses import replace
    from datetime import datetime, timezone
    from src.services.actorops.ports import FetchWindow
    from tests.test_actorops_v2_runtime import _runtime
    store, repo, runtime, remote, route_id, source_id, candidates = _runtime(
        tmp_path, ['valid_nonempty'], candidate_count=2,
    )
    try:
        adapter = runtime.registry.require(repo.get_route(route_id).route_key)
        original = adapter.validate_output
        adapter.validate_output = lambda *args: replace(original(*args), rejected_identity_rows=1)
        result = asyncio.run(runtime.fetch(
            route_id=route_id, source_id=source_id, source_config={'target': 'openai'},
            window=FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
            logical_job_id='partial-batch',
        ))
        assert len(result.items) == 1 and len(remote.requests) == 1
        assert result.candidate_id == candidates[0]
        assert result.degraded_reason == 'actorops_partial_identity'
        event = repo.connection.execute("SELECT reason_code,counts_json FROM actor_execution_events_v2 WHERE phase='attempt_result'").fetchone()
        assert event['reason_code'] == 'actorops_partial_identity'
        assert json.loads(event['counts_json'])['rejected_identity_rows'] == 1
    finally:
        store.close()
