"""Bound connector JSON before parsing, including chunked requests."""
from starlette.responses import JSONResponse


class ConnectorBodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope.get('path', '').startswith('/api/connector/information-automations/'):
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body = message.get('body', b'')
            size += len(body)
            if size > 65536:
                response = JSONResponse({'ok': False, 'error': {'code': 'request_too_large', 'message': 'Connector 请求过大。'}}, status_code=413)
                return await response(scope, receive, send)
            chunks.append(body)
            if not message.get('more_body', False):
                break
        consumed = False
        async def replay():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {'type': 'http.request', 'body': b''.join(chunks), 'more_body': False}
            return await receive()
        await self.app(scope, replay, send)
