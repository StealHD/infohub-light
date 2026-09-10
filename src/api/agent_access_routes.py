"""Member requests and workspace administrator decisions; no operator input from members."""
from typing import Literal
from fastapi import Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from .context import ApiContext
from .system_auth import api_context, current_user, current_admin
from .responses import ApiError, ok
from ..storage.agent_access_schema import ready
from ..services.agent_connections.access_requests import AccessRequests, AccessError
from ..services.agent_connections import access_setup


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Decision(EmptyRequest):
    revision: int = Field(strict=True, ge=1)
    decision: Literal['approved', 'rejected']
    reason: str = Field(default='', max_length=200)


def own_status(context, user):
    requests = AccessRequests(context)
    from ..services.agent_connections.cleanup import public
    from ..services.agent_connections.service import AgentConnections
    binding = AgentConnections(context.store, context.secret_values).row(user['id'])
    cleaning = public(context, user['id'], binding['binding_id']) if binding else None
    return {'can_request': user['role'] == 'member' and ready(requests.conn) and (not cleaning or cleaning['phase'] == 'complete'),
            'cleanup': cleaning,
            'request_available': ready(requests.conn),
            'access_request': access_setup.project(context, requests.latest(user))}


async def submit(payload: EmptyRequest, response: Response, user=Depends(current_user), context: ApiContext = Depends(api_context)):
    response.headers['Cache-Control'] = 'no-store'
    if user['role'] != 'member':
        raise ApiError('forbidden', '仅成员可申请接入。', status_code=403)
    try:
        return ok(AccessRequests(context).submit(user))
    except AccessError as error:
        raise ApiError('agent_request_conflict', str(error), status_code=409) from error


async def listing(response: Response, group: Literal['pending','processing','processed'] = 'pending',
                  search: str = Query('', max_length=100), page: int = Query(1, ge=1),
                  user=Depends(current_admin), context: ApiContext = Depends(api_context)):
    response.headers['Cache-Control'] = 'no-store'
    try:
        result = AccessRequests(context).listing(user, group, search.strip(), page)
        result['items'] = [access_setup.project(context, row) for row in result['items']]
        return ok(result)
    except AccessError as error:
        raise ApiError('agent_requests_unavailable', str(error), status_code=409) from error


async def decide(request_id: str, payload: Decision, response: Response, user=Depends(current_admin), context: ApiContext = Depends(api_context)):
    response.headers['Cache-Control'] = 'no-store'
    if payload.decision == 'rejected' and not payload.reason.strip():
        raise ApiError('reason_required', '请填写拒绝原因。', status_code=400)
    try:
        row = AccessRequests(context).decide(request_id, user, payload.revision, payload.decision, payload.reason.strip())
        if row['state'] == 'approved':
            access_setup.start(context, user, request_id)
        return ok(row)
    except AccessError as error:
        raise ApiError('agent_request_conflict', str(error), status_code=409) from error


async def retry(request_id: str, payload: EmptyRequest, response: Response, user=Depends(current_admin), context: ApiContext = Depends(api_context)):
    response.headers['Cache-Control'] = 'no-store'
    try:
        access_setup.start(context, user, request_id)
        return ok({'accepted': True})
    except AccessError as error:
        raise ApiError('agent_request_conflict', str(error), status_code=409) from error


def register(app):
    app.add_api_route('/api/me/agent-access-requests', submit, methods=['POST'])
    app.add_api_route('/api/admin/agent-access-requests', listing, methods=['GET'])
    app.add_api_route('/api/admin/agent-access-requests/{request_id}/decision', decide, methods=['POST'])
    app.add_api_route('/api/admin/agent-access-requests/{request_id}/retry', retry, methods=['POST'])
