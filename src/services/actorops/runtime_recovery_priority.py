"""Keep a logical job's settled result or unresolved paid attempt ahead of quality."""

from .attempt_recovery import attempt_identity


def recovery_candidates(repository, binding, candidates, logical_job_id):
    if not logical_job_id:
        return frozenset()
    result = set()
    for candidate in candidates:
        key = attempt_identity(repository.workspace_id, logical_job_id, binding.source_id,
                               binding.binding_version, candidate.candidate_id, kind='fetch')
        attempt = repository.get_attempt_by_idempotency(key)
        if attempt and (attempt['status'] not in {'failed', 'cancelled'} or not attempt['cost_final']):
            result.add(candidate.candidate_id)
    return frozenset(result)
