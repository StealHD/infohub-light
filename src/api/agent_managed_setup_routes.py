"""One fixed local setup action; no browser-controlled operator parameters."""
from fastapi import Depends, Response

from .agent_setup_routes import SetupRequest, operator
from .context import ApiContext
from .responses import ApiError, ok
from .system_auth import api_context, current_admin
from ..services.agent_connections import managed_setup


async def managed_setup_action(payload: SetupRequest, response: Response, user=Depends(current_admin),
                               context: ApiContext = Depends(api_context)):
    operator(payload, context, response)
    try:
        managed_setup.start(context, user)
    except Exception as error:
        raise ApiError('managed_setup_unavailable', '本机自动接入不可用，请管理员检查本机配置及管理授权。',
                       status_code=409) from error
    response.status_code = 202
    return ok(managed_setup.status(context, user))


async def managed_reconnect_action(payload: SetupRequest, response: Response, user=Depends(current_admin),
                                   context: ApiContext = Depends(api_context)):
    operator(payload, context, response)
    try:
        managed_setup.start(context, user, reconnect=True)
    except Exception as error:
        raise ApiError('managed_setup_unavailable', '本机重新接入不可用，请检查配置后重试。',
                       status_code=409) from error
    response.status_code = 202
    return ok(managed_setup.status(context, user))
