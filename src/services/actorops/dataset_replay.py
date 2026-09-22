"""Bounded Dataset reads pinned to the original Attempt and credential."""
from urllib.parse import quote

import httpx

from .domain import FailureClass
from .errors import ActorOpsRuntimeError
from .ports import DatasetReadRequest


PERMANENT_DATASET_ERRORS = frozenset({
    'actorops_dataset_identity_unproven', 'actorops_dataset_credential_unavailable',
    'actorops_dataset_access_denied', 'actorops_dataset_missing',
    'actorops_dataset_invalid', 'actorops_dataset_too_large',
    'actorops_result_recovery_exhausted',
})


def _error(code):
    return ActorOpsRuntimeError(code, failure_class=FailureClass.REMOTE_UNKNOWN,
                               retryable=code not in PERMANENT_DATASET_ERRORS)


def bound_lease(coordinator, request):
    if coordinator is None or not all((request.attempt_id, request.remote_run_id,
                                       request.dataset_id)):
        raise _error('actorops_dataset_identity_unproven')
    rows = coordinator.store.connect().execute(
        """SELECT r.id FROM apify_actor_runs r JOIN actor_attempts_v2 a
           ON a.workspace_id=r.workspace_id AND a.attempt_id=r.logical_run_id
           WHERE a.workspace_id=? AND a.attempt_id=? AND a.remote_run_id=?
             AND a.dataset_id=? AND r.remote_run_id=a.remote_run_id
             AND r.dataset_id=a.dataset_id AND r.secret_id=a.secret_ref_id
             AND r.secret_version=a.secret_version AND r.pool_generation=a.pool_generation
             AND r.purpose=CASE WHEN a.kind='probe' THEN 'validation' ELSE 'acquisition' END
           LIMIT 2""",
        (coordinator.workspace_id, request.attempt_id, request.remote_run_id, request.dataset_id),
    ).fetchall()
    if len(rows) != 1:
        raise _error('actorops_dataset_identity_unproven')
    try:
        return coordinator.lease_for_run(str(rows[0]['id']))
    except Exception:
        raise _error('actorops_dataset_credential_unavailable') from None


async def read_dataset(client, request):
    if type(request.max_items) is not int or not 1 <= request.max_items <= 100:
        raise _error('actorops_dataset_invalid')
    lease = bound_lease(client.coordinator, request)
    try:
        rows = await client._request_json(
            lease, 'GET', f'/datasets/{quote(request.dataset_id, safe="")}/items',
            params={'clean': 'true', 'limit': str(request.max_items)},
            timeout=30.0, classify_credential=False, max_response_bytes=8 * 1024 * 1024,
        )
    except Exception as exc:
        status = getattr(exc, 'status_code', None)
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
        code = ('actorops_dataset_access_denied' if status in (401, 403) else
                'actorops_dataset_missing' if status == 404 else
                'actorops_dataset_invalid' if isinstance(exc, ValueError) else
                'actorops_dataset_too_large' if getattr(exc, 'code', '') == 'apify_dataset_response_too_large'
                else 'actorops_dataset_read_transient')
        raise _error(code) from None
    if (not isinstance(rows, list) or len(rows) > request.max_items
            or any(not isinstance(row, dict) for row in rows)):
        raise _error('actorops_dataset_invalid')
    return tuple(rows)
