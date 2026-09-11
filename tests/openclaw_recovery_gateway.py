"""Stateful protocol fixture for the observed 2026.9.2 default/fork discrepancy."""
import asyncio
import uuid

DEFAULT = 'deepseek/flash'
OTHER = 'google/gemini'


class RecoveryGateway:
    def __init__(self, agent, patched=False):
        self.agent = agent
        self.patched = patched
        self.parent = f'agent:{agent}:parent'
        self.child = f'agent:{agent}:child'
        self.sessions = {self.parent: {'override': OTHER}, self.child: {'parent': self.parent}}
        self.history = {self.child: [{'id': 'prior-user', 'role': 'user', 'text': '切换前的上下文'}, {'id': 'prior-answer', 'role': 'assistant', 'text': '已记住前文'}]}
        self.calls = {}
        self.created = []

    def describe(self, key):
        entry = self.sessions[key]
        provider, model = entry.get('override', DEFAULT).split('/')
        return {'key': key, 'agentId': self.agent, 'modelProvider': provider, 'model': model,
                **({'parentSessionKey': entry['parent']} if entry.get('parent') else {}),
                **({'modelOverrideSource': 'user'} if entry.get('override') else {})}

    def execution_model(self, key):
        entry = self.sessions[key]
        parent = self.sessions.get(entry.get('parent'), {})
        return entry.get('override', parent.get('override', DEFAULT))

    def respond(self, method, params):
        if method == 'connect':
            return {'protocol': 4, 'snapshot': {'sessionDefaults': {'defaultAgentId': self.agent}},
                    'features': {'methods': ['sessions.preview', 'sessions.list', 'skills.status']}}
        if method == 'agents.list':
            return {'agents': [{'id': self.agent, 'model': {'primary': DEFAULT}}]}
        if method == 'models.list':
            return {'models': [{'id': 'flash', 'provider': 'deepseek', 'name': 'DeepSeek', 'input': ['text','image']},
                               {'id': 'gemini', 'provider': 'google', 'name': 'Gemini'}]}
        if method == 'sessions.describe':
            return {'session': self.describe(params['key'])}
        if method == 'sessions.preview':
            return {'previews': [{'key': key, 'status': 'empty'} for key in params['keys']]}
        if method == 'sessions.list':
            return {'sessions': [dict(self.describe(key), displayName='恢复验收', updatedAt=1) for key in self.sessions]}
        if method == 'sessions.create':
            key = f'agent:{self.agent}:root-{uuid.uuid4()}'
            self.sessions[key] = {**({'parent': params['parentSessionKey']} if params.get('parentSessionKey') else {}),
                                  **({'override': params['model']} if params.get('model') not in (None, DEFAULT) else {})}
            if self.patched and params.get('fork') and params.get('model'):
                self.sessions[key]['override'] = params['model']
            if params.get('fork'):
                self.history[key] = list(self.history.get(params['parentSessionKey'], []))
            self.created.append(dict(params))
            return {'key': key}
        if method == 'chat.history':
            return {'messages': self.history.get(params['sessionKey'], [])}
        if method == 'tools.effective':
            return {'groups': [{'tools': [{'id': 'inteliscope', 'source': 'mcp'}]}]}
        if method == 'skills.status':
            return {'skills': []}
        return {}

    async def socket(self, ws):
        await ws.accept()
        await ws.send_json({'type': 'event', 'event': 'connect.challenge', 'payload': {'nonce': 'controlled'}})
        try:
            while True:
                frame = await ws.receive_json()
                method, params = frame['method'], frame.get('params', {})
                if method == 'chat.send':
                    await self.send_turn(ws, frame['id'], params)
                else:
                    await ws.send_json({'type': 'res', 'id': frame['id'], 'ok': True, 'payload': self.respond(method, params)})
        except Exception as exc:
            from starlette.websockets import WebSocketDisconnect
            if not isinstance(exc, WebSocketDisconnect):
                raise

    async def send_turn(self, ws, request_id, params):
        run, key = params['idempotencyKey'], params['sessionKey']
        await ws.send_json({'type': 'res', 'id': request_id, 'ok': True, 'payload': {'runId': run}})
        if run in self.calls:
            return
        actual = self.execution_model(key)
        self.calls[run] = {'actual': actual, 'session': key, 'deliver': params.get('deliver')}
        provider, model = actual.split('/')
        self.history[key] = self.history.get(key, []) + [{'id': run, 'idempotencyKey': run, 'role': 'user', 'text': params['message']},
                             {'id': 'answer-' + run, 'role': 'assistant', 'text': '已有部分回复',
                              'stopReason': 'error', 'provider': provider, 'model': model}]
        await ws.send_json({'type': 'event', 'event': 'chat', 'payload': {
            'sessionKey': key, 'runId': run, 'seq': 1, 'state': 'delta', 'deltaText': '已有部分回复'}})
        await asyncio.sleep(.1)
        await ws.send_json({'type': 'event', 'event': 'chat', 'payload': {
            'sessionKey': key, 'runId': run, 'seq': 2, 'state': 'error', 'errorKind': 'rate_limit',
            'errorMessage': 'SECRET https://private.invalid/token', 'message': {
                'id': 'answer-' + run, 'role': 'assistant', 'provider': provider, 'model': model}}})
