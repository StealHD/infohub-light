"""Actual installed transport against a bounded local MCP server, without model calls."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import subprocess
import threading

import pytest


def test_installed_transport_initializes_lists_and_reads_without_sse():
    package = os.getenv('INTELISCOPE_OPENCLAW_PACKAGE')
    node = shutil.which('node')
    if not package or not node:
        pytest.skip('Installed OpenClaw unavailable; not native transport acceptance')
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(request['method'])
            if 'id' not in request:
                self.send_response(202)
                self.end_headers()
                return
            results = {
                'initialize': {'protocolVersion': '2025-03-26', 'capabilities': {'tools': {}},
                               'serverInfo': {'name': 'isolated-fixture', 'version': '1'}},
                'tools/list': {'tools': [{'name': 'list_subscriptions', 'inputSchema': {'type': 'object'},
                                         'annotations': {'readOnlyHint': True}}]},
                'tools/call': {'content': [{'type': 'text', 'text': '[]'}], 'isError': False},
            }
            body = json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': results[request['method']]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = {'packageRoot': package, 'server': 'fixture', 'requiredTools': ['list_subscriptions'],
                   'config': {'url': f'http://127.0.0.1:{server.server_port}/mcp', 'transport': 'streamable-http'}}
        script = Path(__file__).resolve().parents[1] / 'scripts/probe_native_mcp.mjs'
        result = subprocess.run([node, str(script)], input=json.dumps(payload), text=True,
                                capture_output=True, timeout=25)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {'native_transport': 'streamable-http', 'personal_tools': True}
        assert calls == ['initialize', 'notifications/initialized', 'tools/list', 'tools/call']
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()
