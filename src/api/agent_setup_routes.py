"""Explicit, current-account setup for trusted Owner/Admin operators."""
import base64
import io
import tarfile

from fastapi import Depends, FastAPI, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .context import ApiContext
from .responses import ApiError, ok
from .system_auth import api_context, current_admin
from ..services.agent_connections.manifest import canonical
from ..services.agent_connections.service import AgentConnections, BindingError
from ..storage.service_store import AgentDelegationLimitError

MUTATION_OPERATION_ROUTES = {
    ('POST', '/api/me/agent-connection/setup'): ('agent', 'personal_setup'),
    ('POST', '/api/me/agent-connection/setup/bundle'): ('agent', 'personal_bundle_export'),
    ('POST', '/api/me/agent-connection/setup/activate'): ('agent', 'personal_setup_activate'),
}


class SetupRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirmed: StrictBool


class ActivationRequest(SetupRequest):
    receipt_json: str = Field(min_length=1, max_length=8192)


def operator(payload, context, response):
    response.headers['Cache-Control'] = 'no-store'
    if payload.confirmed is not True:
        raise ApiError('confirmation_required', '请确认这是你管理的 OpenClaw。', status_code=400)
    if not context.remote_mcp_settings.enabled or not context.remote_mcp_settings.public_url:
        raise ApiError('remote_mcp_disabled', '管理员需先配置本站 Remote MCP 地址。', status_code=409)
    return AgentConnections(context.store, context.secret_values)


async def prepare(payload: SetupRequest, response: Response, user=Depends(current_admin),
                  context: ApiContext = Depends(api_context)):
    connections = operator(payload, context, response)
    try:
        # A repeat after an ambiguous response resumes the same identity, never creates another.
        if not connections.row(user['id']):
            connections.prepare(user['id'], context.remote_mcp_settings.public_url)
    except (BindingError, AgentDelegationLimitError, ValueError) as error:
        raise ApiError('agent_setup_unavailable', '无法准备接入，请检查迁移状态及有效数据连接数量。', status_code=409) from error
    return ok(connections.status(user))


async def bundle(payload: SetupRequest, response: Response, user=Depends(current_admin),
                 context: ApiContext = Depends(api_context)):
    connections = operator(payload, context, response)
    row = connections.row(user['id'])
    if not row or row['state'] != 'pending':
        raise ApiError('agent_setup_not_pending', '仅待验证的个人接入可下载配置。', status_code=409)
    try:
        manifest, token = connections.export(user['id'])
    except (BindingError, ValueError) as error:
        raise ApiError('agent_setup_export_failed', '配置已失效，请联系运维修复，不要重复创建数据连接。', status_code=409) from error
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        directory = tarfile.TarInfo('personal-agent')
        directory.type, directory.mode = tarfile.DIRTYPE, 0o700
        archive.addfile(directory)
        for name, value in [('manifest.json', canonical(manifest)), ('token', token)]:
            content = (value + '\n').encode()
            entry = tarfile.TarInfo('personal-agent/' + name)
            entry.mode, entry.size = 0o600, len(content)
            archive.addfile(entry, io.BytesIO(content))
    return ok({'archive_base64': base64.b64encode(output.getvalue()).decode()})


async def activate(payload: ActivationRequest, response: Response, user=Depends(current_admin),
                   context: ApiContext = Depends(api_context)):
    import json
    connections = operator(payload, context, response)
    try:
        proof = json.loads(payload.receipt_json)
        if not isinstance(proof, dict):
            raise ValueError('Invalid receipt')
        connections.activate(user['id'], proof)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise ApiError('agent_setup_verification_failed', '验证回执无效、已过期或不属于当前接入，请重新运行 verify。', status_code=400) from error
    return ok(connections.status(user))


def register_agent_setup_routes(app: FastAPI):
    for path, handler in [('', prepare), ('/bundle', bundle), ('/activate', activate)]:
        app.add_api_route('/api/me/agent-connection/setup' + path, handler, methods=['POST'])
