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


async def rpc_models(url, token, agent_id, device_dir, ssl_context=None):
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
        await socket.send(json.dumps({'type':'req','id':'connect','method':'connect','params':connect_params(root,token,nonce)}))
        while True:
            frame = json.loads(await asyncio.wait_for(socket.recv(),15))
            if frame.get('id') == 'connect':
                if not frame.get('ok') or 'models.list' not in frame.get('payload',{}).get('features',{}).get('methods',[]):
                    raise ValueError('model_catalog_unsupported')
                break
        await socket.send(json.dumps({'type':'req','id':'models','method':'models.list','params':{'view':'configured','agentId':agent_id}}))
        while True:
            frame = json.loads(await asyncio.wait_for(socket.recv(),15))
            if frame.get('id') == 'models':
                if not frame.get('ok'):
                    raise ValueError('model_catalog_unavailable')
                return frame['payload']


def discover(url, token, agent_id, device_dir, config_path, ssl_context=None):
    config = json.loads(Path(config_path).read_text())
    payload = asyncio.run(asyncio.wait_for(rpc_models(url,token,agent_id,device_dir,ssl_context),45))
    return project_models(payload,config)
