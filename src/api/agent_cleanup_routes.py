"""Workspace-scoped member revocation; identities come from persisted requests."""
from fastapi import Depends, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from .system_auth import current_admin, api_context
from .responses import ApiError, ok
from ..services.agent_connections.access_requests import AccessRequests, AccessError
from ..services.agent_connections import cleanup, cleanup_store


class Revoke(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(strict=True, ge=1)
    confirmed: StrictBool


async def revoke(request_id: str, payload: Revoke, response: Response,
                 actor=Depends(current_admin), context=Depends(api_context)):
    response.headers['Cache-Control'] = 'no-store'
    if payload.confirmed is not True:
        raise ApiError('confirmation_required', '请确认撤销成员接入。', status_code=400)
    try:
        request = AccessRequests(context).get(request_id, actor)
        target = context.store.get_user(request['user_id'])
        if not target or target['role'] in {'owner', 'admin'}:
            raise AccessError('此入口仅用于撤销成员接入。')
        row = cleanup_store.begin(context, actor, target, request, payload.revision)
        cleanup.start(context, row, actor)
        return ok(cleanup.public(context, target['id'], row['binding_id']))
    except AccessError as error:
        raise ApiError('agent_cleanup_conflict', str(error), status_code=409) from error


async def retry(request_id: str, payload: Revoke, response: Response,
                actor=Depends(current_admin), context=Depends(api_context)):
    response.headers['Cache-Control'] = 'no-store'
    try:
        request = AccessRequests(context).get(request_id, actor)
        row = cleanup_store.get(context.store, request['user_id'], request['binding_id']) if request['binding_id'] else None
        if not row or row['request_id'] != request_id or row['revision'] != payload.revision or payload.confirmed is not True:
            raise AccessError('清理状态已变化，请刷新核对。')
        cleanup.start(context, row, actor)
        return ok(cleanup.public(context, request['user_id'], row['binding_id']))
    except AccessError as error:
        raise ApiError('agent_cleanup_conflict', str(error), status_code=409) from error


def register(app):
    app.add_api_route('/api/admin/agent-access-requests/{request_id}/revoke', revoke, methods=['POST'])
    app.add_api_route('/api/admin/agent-access-requests/{request_id}/cleanup-retry', retry, methods=['POST'])
