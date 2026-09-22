import asyncio
import pytest

from src.services.actorops.domain import AttemptStatus, AssignmentRole, CandidateLifecycle
from src.services.apify_actor_manifest import actor_manifest_hash, parse_actor_manifest
from tests.test_actorops_v2_resilience import _repository, _manifest
from tests.test_actorops_repair_wakeup import authorize


def prove(repo, route, source, candidate='candidate-1'):
    binding = repo.get_binding(source)
    with repo.transaction():
        repo.create_attempt(attempt_id='proof', idempotency_key='proof', route_id=route,
            source_id=source, candidate_id=candidate, kind='probe', attempt_group_id='proof',
            attempt_index=0, route_generation=repo.get_route(route).generation,
            binding_version=binding.binding_version, target_fingerprint=binding.target_fingerprint,
            reserved_usd=.01)
        repo.transition_attempt('proof', AttemptStatus.CREATED, AttemptStatus.STARTING)
        repo.register_attempt_run('proof', expected_generation=2, remote_run_id='run', dataset_id='dataset')
        repo.complete_attempt('proof', status=AttemptStatus.SUCCEEDED,
            semantic_outcome='valid_nonempty', actual_cost_usd=.01, cost_final=True)


@pytest.fixture
def setup(tmp_path):
    store, repo, route, source = _repository(tmp_path)
    authorize(store)
    conn = repo.connection
    conn.execute("UPDATE actor_routes_v2 SET runtime_mode='active' WHERE route_id=?", (route,))
    conn.execute("UPDATE actor_candidates_v2 SET assignment_role='inactive',priority=NULL WHERE candidate_id='candidate-1'")
    conn.commit()
    repair = repo.resilience.ensure_repair(route_id=route, source_id=source,
        origin_job_id='job', trigger_code='actorops_route_exhausted')
    conn.execute("UPDATE actor_route_repairs_v2 SET status='awaiting_probe',candidate_id='candidate-1' WHERE repair_id=?",
                 (repair['repair_id'],))
    conn.commit()
    try:
        yield store, repo, route, source, repair['repair_id']
    finally:
        store.close()


def test_certified_reserve_is_assigned_from_existing_proof_and_repair_finishes(setup):
    _, repo, route, source, repair = setup
    prove(repo, route, source)
    # Local assignment does not require a new paid-probe budget.
    repo.connection.execute('UPDATE actor_maintenance_policies_v2 SET max_probes_per_utc_day=1 WHERE route_id=?', (route,))
    repo.connection.commit()
    result = repo.resilience.advance_repair(repair)
    assert result['status'] == 'recovered'
    assert repo.get_candidate('candidate-1').assignment_role is AssignmentRole.STANDBY
    generation = repo.get_route(route).generation
    assert repo.resilience.advance_repair(repair)['status'] == 'recovered'
    assert repo.get_route(route).generation == generation
    assert repo.connection.execute('SELECT count(*) FROM actor_attempts_v2').fetchone()[0] == 1


def test_certified_reserve_with_obsolete_binding_proof_is_probeable(setup):
    _, repo, route, source, repair = setup
    prove(repo, route, source)
    repo.connection.execute('UPDATE actor_source_bindings_v2 SET binding_version=binding_version+1 WHERE source_id=?', (source,))
    repo.connection.commit()
    assert repo.resilience.advance_repair(repair)['status'] == 'awaiting_probe'
    candidate, binding = repo.maintenance.probe_target(route)
    assert candidate == 'candidate-1' and binding['binding_version'] == 2


@pytest.mark.parametrize('disabled', ['authorization', 'auto_add', 'runtime'])
def test_repair_assignment_respects_current_permission(setup, disabled):
    _, repo, route, source, repair = setup
    prove(repo, route, source)
    sql = {'authorization': 'UPDATE actor_maintenance_policies_v2 SET enabled=0 WHERE route_id=?',
           'auto_add': 'UPDATE actor_maintenance_policies_v2 SET auto_add_standby=0 WHERE route_id=?',
           'runtime': "UPDATE actor_routes_v2 SET runtime_mode='disabled' WHERE route_id=?"}[disabled]
    repo.connection.execute(sql, (route,)); repo.connection.commit()
    result = repo.resilience.advance_repair(repair)
    assert result['status'] == 'blocked'
    assert repo.get_candidate('candidate-1').assignment_role is AssignmentRole.INACTIVE


def test_probe_budget_still_blocks_new_proofs(setup):
    _, repo, route, source, repair = setup
    prove(repo, route, source)
    repo.connection.execute('UPDATE actor_source_bindings_v2 SET binding_version=2 WHERE source_id=?', (source,))
    repo.connection.execute('UPDATE actor_maintenance_policies_v2 SET max_probes_per_utc_day=1 WHERE route_id=?', (route,))
    repo.connection.commit()
    result = repo.resilience.advance_repair(repair)
    assert result['error_code'] == 'actorops_repair_daily_probe_limit'
    assert repo.connection.execute('SELECT count(*) FROM actor_attempts_v2').fetchone()[0] == 1


def add_standby(repo, route, candidate):
    manifest = _manifest('publisher/' + candidate)
    with repo.transaction():
        repo.create_candidate(candidate_id=candidate, route_id=route, actor_id='publisher/' + candidate,
            publisher='publisher', build_id='build-' + candidate, build_number='1.0.0',
            manifest_json=manifest, manifest_hash=actor_manifest_hash(parse_actor_manifest(manifest)),
            input_schema_hash='e' * 64, output_schema_hash='f' * 64,
            lifecycle=CandidateLifecycle.CERTIFIED)
        priority = repo.connection.execute("SELECT count(*) FROM actor_candidates_v2 WHERE assignment_role!='inactive'").fetchone()[0]
        repo.assign_candidate(route, candidate, AssignmentRole.STANDBY, priority=priority,
            expected_route_generation=repo.get_route(route).generation, expected_candidate_generation=1)


def test_full_slots_report_retryable_blocker_without_quarantining_source_failures(setup):
    _, repo, route, source, repair = setup
    prove(repo, route, source)
    add_standby(repo, route, 'extra-1')
    add_standby(repo, route, 'extra-2')
    binding = repo.get_binding(source)
    for candidate in ('candidate-0', 'extra-1', 'extra-2'):
        repo.resilience.record_paid_candidate_failure(binding=binding, candidate_id=candidate,
                                                      logical_job_id='failed-' + candidate)
    before = repo.list_route_candidates(route)
    result = repo.resilience.advance_repair(repair)
    assert result['status'] == 'blocked'
    assert result['error_code'] == 'actorops_repair_assignment_unavailable'
    assert result['next_attempt_at'] and result['candidate_id'] == 'candidate-1'
    assert repo.list_route_candidates(route) == before
    # An operator frees a slot. A subsequent normal repair pass takes over.
    repo.connection.execute("UPDATE actor_candidates_v2 SET assignment_role='inactive',priority=NULL WHERE candidate_id='extra-2'")
    repo.connection.commit()
    result = repo.resilience.advance_repair(repair)
    assert repo.get_candidate('candidate-1').assignment_role is AssignmentRole.STANDBY
    assert result['status'] == 'queued'  # Still needs a second stable path.
    assert repo.connection.execute('SELECT count(*) FROM actor_attempts_v2').fetchone()[0] == 1


def test_verified_reserve_replaces_confirmed_failure_using_standing_policy(setup):
    _, repo, route, source, repair = setup
    prove(repo, route, source)
    add_standby(repo, route, 'extra')
    with repo.transaction():
        candidate = repo.get_candidate('candidate-0')
        repo.record_candidate_outcome(candidate.candidate_id, expected_generation=candidate.generation,
            succeeded=False, error_class='candidate', error_code='apify_actor_build_unavailable')
    result = repo.resilience.advance_repair(repair)
    assert result['status'] == 'recovered'
    assert repo.get_candidate('candidate-0').lifecycle is CandidateLifecycle.QUARANTINED
    assert repo.get_candidate('extra').assignment_role is AssignmentRole.ACTIVE
    assert repo.get_candidate('candidate-1').assignment_role is AssignmentRole.STANDBY
    assert repo.connection.execute('SELECT count(*) FROM actor_attempts_v2').fetchone()[0] == 1


@pytest.mark.parametrize('awaited', [False, True])
def test_certified_repair_selection_reaches_paid_admission_only_for_missing_proof(tmp_path, awaited):
    from tests.test_actorops_v2_maintenance import _repository as maintenance_repository
    from tests.test_actorops_v2_maintenance import _authorize, _prober, _Remote, _Preflight
    store, repo, route, source = maintenance_repository(tmp_path)
    try:
        _authorize(repo, route)
        with repo.transaction():
            candidate = repo.get_candidate('candidate')
            candidate = repo.transition_candidate(candidate.candidate_id, candidate.lifecycle,
                CandidateLifecycle.PROBATIONARY, expected_generation=candidate.generation)
            repo.transition_candidate(candidate.candidate_id, candidate.lifecycle,
                CandidateLifecycle.CERTIFIED, expected_generation=candidate.generation)
        if awaited:
            repair = repo.resilience.ensure_repair(route_id=route, source_id=source,
                origin_job_id='repair', trigger_code='actorops_route_exhausted')
            repo.connection.execute("UPDATE actor_route_repairs_v2 SET status='awaiting_probe',candidate_id='candidate' WHERE repair_id=?",
                                    (repair['repair_id'],))
            repo.connection.commit()
            assert repo.maintenance.probe_target(route)[0] == 'candidate'
        remote = _Remote()
        result = asyncio.run(_prober(repo, remote, _Preflight()).probe(route_id=route,
            candidate_id='candidate', source_id=source, source_config={'target': 'openai'},
            maintenance_slot='missing-proof', expected_binding_version=1))
        assert len(remote.requests) == int(awaited)
        assert result.status == ('promoted' if awaited else 'skipped')
        if awaited:
            assert repo.maintenance.successful_probe_targets('candidate') == 1
            again = asyncio.run(_prober(repo, remote, _Preflight()).probe(route_id=route,
                candidate_id='candidate', source_id=source, source_config={'target': 'openai'},
                maintenance_slot='already-proved', expected_binding_version=1))
            assert again.status == 'skipped'
            assert len(remote.requests) == 1
    finally:
        store.close()


def test_capacity_blocked_repair_wakes_when_slot_is_available(setup):
    from src.services.actorops.repair_wakeup import wake_assignable_repairs
    _, repo, route, source, repair = setup
    prove(repo, route, source)
    add_standby(repo, route, 'extra-1')
    add_standby(repo, route, 'extra-2')
    binding = repo.get_binding(source)
    for candidate in ('extra-1', 'extra-2'):
        repo.resilience.record_paid_candidate_failure(binding=binding, candidate_id=candidate,
                                                      logical_job_id='failure-' + candidate)
    result = repo.resilience.advance_repair(repair)
    assert result['error_code'] == 'actorops_repair_assignment_unavailable'
    due = result['next_attempt_at']
    with repo.transaction():
        assert wake_assignable_repairs(repo, route) == 0
    assert repo.resilience.get_repair(repair)['next_attempt_at'] == due
    repo.connection.execute("UPDATE actor_candidates_v2 SET assignment_role='inactive',priority=NULL WHERE candidate_id='extra-2'")
    repo.connection.commit()
    with repo.transaction():
        assert wake_assignable_repairs(repo, route) == 1
    assert repo.resilience.get_repair(repair)['next_attempt_at'] < due
    assert repo.resilience.advance_repair(repair)['status'] == 'recovered'
    assert repo.get_candidate('candidate-1').assignment_role is AssignmentRole.STANDBY


def test_capacity_wakeup_does_not_override_disabled_policy(setup):
    from src.services.actorops.repair_wakeup import wake_assignable_repairs
    _, repo, route, source, repair = setup
    repo.connection.execute("UPDATE actor_route_repairs_v2 SET status='blocked',error_code='actorops_repair_assignment_unavailable',next_attempt_at='2099-01-01' WHERE repair_id=?", (repair,))
    repo.connection.execute('UPDATE actor_maintenance_policies_v2 SET enabled=0 WHERE route_id=?', (route,))
    repo.connection.commit()
    with repo.transaction():
        assert wake_assignable_repairs(repo, route) == 0
    assert repo.resilience.get_repair(repair)['next_attempt_at'] == '2099-01-01'
