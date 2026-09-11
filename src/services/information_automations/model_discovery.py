"""Read configured Gateway models and host-owned llm-task authorization only."""
import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from websockets.asyncio.client import connect
from ..openclaw_relay.identity import connect_params


def project_models(payload, config):
    plugin = config.get('plugins', {}).get('entries', {}).get('llm-task', {})
    policy = plugin.get('llm', {})
    if plugin.get('enabled') is not True or policy.get('allowModelOverride') is not True:
        return []
    allowed = policy.get('allowedCompletionModels')
    result, seen = [], set()
    for row in payload.get('models', []):
        if not isinstance(row, dict) or row.get('available') is False:
            continue
        identity, provider = row.get('id'), row.get('provider')
        if not isinstance(identity, str) or not isinstance(provider, str):
            continue
        identity = identity if identity.startswith(provider + '/') else provider + '/' + identity
        if identity in seen or (allowed is not None and identity not in allowed):
            continue
        seen.add(identity)
        levels = [value['id'] for value in row.get('thinkingLevels', [])
                  if isinstance(value, dict) and isinstance(value.get('id'), str)]
        result.append({'id': identity, 'name': row.get('name') or identity, 'thinking_levels': levels})
    return result


async def rpc_models(url, token, agent_id, device_dir, ssl_context=None, *, operation=None, scopes=None):
    parsed = urlsplit(url)
    socket_url = urlunsplit(('wss' if parsed.scheme == 'https' else 'ws', parsed.netloc, parsed.path, '', ''))
    root = Path(device_dir)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    options = {'ssl': ssl_context} if parsed.scheme == 'https' and ssl_context else {}
    async with connect(socket_url, proxy=None, open_timeout=15, close_timeout=5, max_size=2*1024*1024, **options) as socket:
        challenge = json.loads(await asyncio.wait_for(socket.recv(), 15))
        nonce = challenge.get('payload', {}).get('nonce')
        if challenge.get('event') != 'connect.challenge' or not isinstance(nonce, str):
            raise ValueError('model_catalog_handshake')
        await socket.send(json.dumps({'type':'req','id':'connect','method':'connect','params':connect_params(root,token,nonce,scopes=scopes)}))
        while True:
            frame = json.loads(await asyncio.wait_for(socket.recv(),15))
            if frame.get('id') == 'connect':
                if not frame.get('ok') or 'models.list' not in frame.get('payload',{}).get('features',{}).get('methods',[]):
                    raise ValueError('model_catalog_unsupported')
                break
        if operation:
            return await operation(socket)
        return await model_request(socket,'models','models.list',{'view':'configured','agentId':agent_id})


async def model_request(socket, identity, method, params):
    await socket.send(json.dumps({'type':'req','id':identity,'method':method,'params':params}))
    for _ in range(128):
        frame = json.loads(await asyncio.wait_for(socket.recv(),15))
        if frame.get('id') == identity:
            if not frame.get('ok'):
                raise ValueError('model_catalog_unavailable')
            return frame.get('payload',{})
    raise ValueError('model_catalog_response_missing')


def discover(url, token, agent_id, device_dir, config_path, ssl_context=None):
    from types import SimpleNamespace
    from ..agent_connections.analysis_model_policy import reconcile, project_discovery, policy_path
    root = Path(config_path).parent
    config = json.loads(Path(config_path).read_text())
    async def operation(socket):
        personal = await model_request(socket,'personal-models','models.list',{'view':'configured','agentId':'ih-'+agent_id.removeprefix('ic-')})
        host = SimpleNamespace(root=root,gateway=SimpleNamespace(_request=model_request))
        updated, reason = await reconcile(host,socket,personal,config)
        payload = await model_request(socket,'analysis-models','models.list',{'view':'configured','agentId':agent_id})
        return project_discovery(personal,payload,updated,reason)
    policy = policy_path(root)
    owned = policy.exists() and json.loads(policy.read_text()).get('owner') == 'system'
    return asyncio.run(asyncio.wait_for(rpc_models(url,token,agent_id,device_dir,ssl_context,
        operation=operation,scopes=['operator.admin'] if owned else None),90))
