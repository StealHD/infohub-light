"""A stalled repair must use current partial proof toward a usable backup."""

import pytest

from src.services.actorops.domain import AssignmentRole, AttemptStatus, CandidateLifecycle
from src.services.apify_actor_manifest import actor_manifest_hash, parse_actor_manifest
from src.services.actorops.repair_candidate_selection import prefer_proved_reserve
from tests.test_actorops_repair_assignment import setup  # noqa: F401
from tests.test_actorops_v2_resilience import _manifest


def proof(repo, route, source, candidate, name, *, succeeded=True, cost_final=True):
    binding = repo.get_binding(source)
    with repo.transaction():
        repo.create_attempt(
            attempt_id=name, idempotency_key=name, route_id=route,
            source_id=source, candidate_id=candidate, kind='probe',
            attempt_group_id=name, attempt_index=0,
            route_generation=repo.get_route(route).generation,
            binding_version=binding.binding_version,
            target_fingerprint=binding.target_fingerprint, reserved_usd=.01,
        )
        repo.transition_attempt(name, AttemptStatus.CREATED, AttemptStatus.STARTING)
        repo.register_attempt_run(name, expected_generation=2,
                                  remote_run_id=name, dataset_id=name)
        repo.complete_attempt(name, status=AttemptStatus.SUCCEEDED if succeeded else AttemptStatus.FAILED,
                              semantic_outcome='valid_nonempty' if succeeded else 'empty',
                              actual_cost_usd=.01, cost_final=cost_final)


def reserve_with_partial_proof(store, repo, route, source, **proof_options):
    second = store.create_source(
        workspace_id='default', scope='workspace', owner_user_id=None,
        source_type='apify_social', display_name='Second target',
        config={'platform': 'x', 'kind': 'profile', 'target': 'second'},
    )
    repo.connection.execute(
        """INSERT INTO actor_source_bindings_v2
           (binding_id,workspace_id,source_id,route_id,target_fingerprint,
            status,binding_version,created_at,updated_at)
           VALUES ('second-binding','default',?,?,'second-fingerprint',
                   'ready',1,'2026-09-22','2026-09-22')""", (second, route),
    )
    repo.connection.commit()
    manifest = _manifest('publisher/progress')
    with repo.transaction():
        repo.create_candidate(
            candidate_id='progress', route_id=route, actor_id='publisher/progress',
            publisher='publisher', build_id='progress-build', build_number='1.0.0',
            manifest_json=manifest,
            manifest_hash=actor_manifest_hash(parse_actor_manifest(manifest)),
            input_schema_hash='b' * 64, output_schema_hash='c' * 64,
            lifecycle=CandidateLifecycle.PROBATIONARY,
        )
    proof(repo, route, second, 'progress', 'first-proof', **proof_options)
    return second


def test_stalled_repair_completes_backup_proof_then_bypasses_cooling_primary(setup):
    store, repo, route, source, repair = setup
    reserve_with_partial_proof(store, repo, route, source)
    binding = repo.get_binding(source)
    repo.resilience.record_paid_candidate_failure(
        binding=binding, candidate_id='candidate-0', logical_job_id='primary-failure',
    )
    # Even before the repair coordinator runs, finish the partially proved reserve.
    candidate, target = repo.maintenance.probe_target(route)
    assert (candidate, target['source_id']) == ('progress', source)
    result = repo.resilience.advance_repair(repair)
    assert (result['status'], result['candidate_id']) == ('awaiting_probe', 'progress')
    assert repo.connection.execute('SELECT count(*) FROM actor_attempts_v2').fetchone()[0] == 1
    proof(repo, route, source, 'progress', 'second-proof')
    repo.resilience.advance_repair(repair)
    assert repo.get_candidate('progress').assignment_role is AssignmentRole.STANDBY
    plan = repo.resilience.plan_candidates(
        binding=binding, candidates=(repo.get_candidate('candidate-0'),
                                     repo.get_candidate('progress')),
        natural_schedule=False, logical_job_id='next-fetch',
    )
    assert [c.candidate_id for c in plan.candidates] == ['progress']
    assert repo.connection.execute('SELECT count(*) FROM actor_attempts_v2').fetchone()[0] == 2


@pytest.mark.parametrize('invalid', ['binding', 'fingerprint', 'pending', 'unsettled', 'failed'])
def test_repair_does_not_retarget_from_invalid_or_obsolete_proof(setup, invalid):
    store, repo, route, source, _ = setup
    second = reserve_with_partial_proof(store, repo, route, source,
                                       succeeded=invalid != 'failed', cost_final=invalid != 'unsettled')
    change = {
        'binding': 'binding_version=99',
        'fingerprint': "target_fingerprint='different'",
        'pending': "status='pending'",
    }.get(invalid)
    if change:
        repo.connection.execute(f"UPDATE actor_source_bindings_v2 SET {change} WHERE source_id=?", (second,))
        repo.connection.commit()
    current = repo.get_candidate('candidate-1')
    assert prefer_proved_reserve(repo, route, current).candidate_id == current.candidate_id


def test_repair_does_not_choose_a_confirmed_failed_reserve(setup):
    store, repo, route, source, _ = setup
    reserve_with_partial_proof(store, repo, route, source)
    with repo.transaction():
        candidate = repo.get_candidate('progress')
        repo.record_candidate_outcome(
            candidate.candidate_id, expected_generation=candidate.generation,
            succeeded=False, error_class='candidate', error_code='apify_actor_build_unavailable',
        )
    current = repo.get_candidate('candidate-1')
    assert prefer_proved_reserve(repo, route, current).candidate_id == current.candidate_id
