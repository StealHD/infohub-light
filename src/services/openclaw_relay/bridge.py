"""Bounded WebSocket RPC bridge with upstream authentication and tenant filtering."""
import asyncio
import json
import time
from collections import deque
from websockets.asyncio.client import connect
from .identity import connect_params
from .ownership import Ownership
from .policy import request_params, response_payload, visible_event
from .settings import SCOPES, settings

MAX_FRAME = 2 * 1024 * 1024


class RelayFailure(Exception):
    pass


async def authenticate(upstream, root, token):
    challenge = json.loads(await asyncio.wait_for(upstream.recv(), 15))
    nonce = challenge.get('payload', {}).get('nonce')
    if challenge.get('event') != 'connect.challenge' or not isinstance(nonce, str):
        raise RelayFailure('OpenClaw handshake unavailable')
    params = connect_params(root, token, nonce)
    await upstream.send(json.dumps({'type': 'req', 'id': 'server-connect', 'method': 'connect', 'params': params}))
    reply = json.loads(await asyncio.wait_for(upstream.recv(), 20))
    if not reply.get('ok'):
        code = reply.get('error', {}).get('details', {}).get('code', '')
        if 'PAIRING' in str(code).upper() or 'pairing' in reply.get('error', {}).get('message', '').lower():
            raise RelayFailure('Server device pairing required; contact administrator')
        raise RelayFailure('Server OpenClaw authentication failed; contact administrator')
    hello = reply['payload']
    agent = hello.get('snapshot', {}).get('sessionDefaults', {}).get('defaultAgentId')
    if hello.get('protocol') != 4 or not isinstance(agent, str) or not agent:
        raise RelayFailure('Server OpenClaw protocol incompatible')
    return agent


def error_reply(request_id, message):
    return {'type': 'res', 'id': request_id, 'ok': False, 'error': {'code': 'RELAY_UNAVAILABLE', 'message': message}}


async def browser_requests(browser, upstream, owner, agent, pending, valid_session):
    arrivals = deque()
    while True:
        raw = await browser.receive_text()
        now = time.monotonic()
        while arrivals and arrivals[0] < now - 60:
            arrivals.popleft()
        if len(arrivals) >= 120:
            raise RelayFailure("Too many requests")
        arrivals.append(now)
        if len(raw.encode()) > MAX_FRAME or not valid_session():
            raise RelayFailure('Session expired or message too large')
        frame = json.loads(raw)
        request_id = frame.get('id')
        if frame.get('type') != 'req' or not isinstance(request_id, str) or len(request_id) > 128:
            raise RelayFailure('Invalid request')
        method, params = frame.get('method'), frame.get('params', {})
        if not isinstance(params, dict) or len(pending) >= 32 or request_id in pending:
            raise RelayFailure('Invalid or excessive requests')
        try:
            safe = request_params(method, params, owner, agent)
        except PermissionError:
            await browser.send_json(error_reply(request_id, '当前账号无权执行该操作或访问该会话。'))
            continue
        pending[request_id] = method
        await upstream.send(json.dumps({'type': 'req', 'id': request_id, 'method': method, 'params': safe}))


async def gateway_events(browser, upstream, owner, agent, pending):
    async for raw in upstream:
        frame = json.loads(raw)
        if frame.get('type') == 'res':
            method = pending.pop(frame.get('id'), None)
            if method is None:
                continue
            if frame.get('ok'):
                frame['payload'] = response_payload(method, frame.get('payload', {}), owner, agent)
            else:
                frame = error_reply(frame.get('id'), 'OpenClaw 未能完成请求，请重试或联系管理员。')
            await browser.send_json(frame)
        elif visible_event(frame, owner):
            await browser.send_json(frame)
    raise RelayFailure('OpenClaw disconnected')


async def session_watch(valid_session):
    while True:
        await asyncio.sleep(15)
        if not valid_session():
            raise RelayFailure('InfoHub login expired')


async def relay(browser, user_id, valid_session):
    url, token, root = settings()
    owner = Ownership(root, user_id)
    async with connect(url, proxy=None, open_timeout=15, ping_interval=20, ping_timeout=20,
                       max_size=MAX_FRAME, max_queue=16, close_timeout=5) as upstream:
        agent = await authenticate(upstream, root, token)
        await browser.send_json({'type': 'event', 'event': 'connect.challenge', 'payload': {'nonce': 'infohub-session'}})
        request = json.loads(await asyncio.wait_for(browser.receive_text(), 15))
        if request.get('method') != 'connect' or request.get('type') != 'req':
            raise RelayFailure('Connect required')
        await browser.send_json({'type': 'res', 'id': request.get('id'), 'ok': True, 'payload': {
            'features': {'methods': ['sessions.preview']},
            'protocol': 4, 'auth': {'role': 'operator', 'scopes': SCOPES},
            'snapshot': {'sessionDefaults': {'defaultAgentId': agent}},
        }})
        pending = {}
        tasks = [asyncio.create_task(browser_requests(browser, upstream, owner, agent, pending, valid_session)),
                 asyncio.create_task(gateway_events(browser, upstream, owner, agent, pending)),
                 asyncio.create_task(session_watch(valid_session))]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
