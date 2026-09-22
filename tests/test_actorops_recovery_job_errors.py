import pytest

from src.services.actorops.job_failure import job_failure_fields
from src.services.job_queue import JobQueue
from src.services.worker import run_worker_once
from tests.test_worker_logging_completeness import worker_env, _create_job, _events


@pytest.mark.parametrize('job_type,status,code', [
    ('actorops_v2_repair', 'blocked', 'actorops_repair_assignment_unavailable'),
    ('actorops_v2_maintenance', 'recovery_required', 'apify_start_outcome_unknown'),
    ('actorops_v2_replacement', 'failed', 'apify_actor_run_failed'),
])
def test_worker_persists_result_failure_code_in_job_and_event(worker_env, monkeypatch, job_type, status, code):
    store, paths = worker_env
    job = _create_job(store, job_type)
    monkeypatch.setattr('src.services.worker._run_job', lambda *_a, **_kw: {
        '_job_status': 'failed', 'status': status, 'error_code': code, 'ok': False,
    })
    result = run_worker_once(data_dir=str(store.data_dir), enqueue_schedules=False)
    assert result['status'] == 'failed'
    saved = JobQueue(store).get_job(job['id'])
    assert saved['error_code'] == code and saved['error_message']
    event = next(e for e in _events(paths) if e.get('job_id') == job['id'] and e['action'] == 'finish')
    assert event['error_code'] == code


def test_job_error_projection_does_not_accept_upstream_text_or_mark_skips_failed():
    job = {'job_type': 'actorops_v2_maintenance'}
    result = {'error_code': 'https://example.com/private?token=secret', 'status': 'failed'}
    assert job_failure_fields(job, 'failed', result)['error_code'] == 'actorops_job_failed'
    assert job_failure_fields(job, 'succeeded', result) == {}
    assert job_failure_fields({'job_type': 'source_fetch'}, 'failed', result) == {}
