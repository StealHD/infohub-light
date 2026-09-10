"""Native transport selection must be exercised, not bypassed by a Python client."""
import json
from pathlib import Path
import shutil
import subprocess
import pytest


@pytest.fixture(params=['js', 'mjs', 'split'])
def package(tmp_path, request):
    root = tmp_path / 'openclaw'
    (root / 'dist').mkdir(parents=True)
    (root / 'package.json').write_text('{"type":"module"}')
    (root / f'dist/mcp-transport-controlled.{request.param}').write_text('''
function resolveMcpTransport(name, config) { return { transportType: config.transport ?? 'sse', transport: {} } }
async function connectMcpClient() {}
async function disposeMcpClient() {}
export { resolveMcpTransport as t, connectMcpClient as c, disposeMcpClient as l };
''')
    if request.param == 'split':
        (root / 'dist/mcp-transport-controlled.mjs').write_text('''
function resolveMcpTransport(name, config) { return { transportType: config.transport ?? 'sse', transport: {} } }
export { resolveMcpTransport as t };
''')
        (root / 'dist/mcp-client-lifecycle-controlled.mjs').write_text('''
async function connectMcpClient() {}
async function disposeMcpClient() {}
export { connectMcpClient as n, disposeMcpClient as r };
''')
    sdk = root / 'node_modules/@modelcontextprotocol/sdk'
    (sdk / 'dist/esm/client').mkdir(parents=True)
    (sdk / 'package.json').write_text('{"type":"module"}')
    (sdk / 'dist/esm/client/index.js').write_text('''
export class Client {
  async listTools() { return { tools: [{name: 'list_subscriptions', annotations: {readOnlyHint: true}}] } }
  async callTool(request) { if(request.name !== 'list_subscriptions') throw Error('Unexpected tool'); return {isError:false} }
}
''')
    return root


@pytest.mark.parametrize('transport,required,success', [(None, ['list_subscriptions'], False),
    ('streamable-http', ['list_subscriptions'], True), ('streamable-http', ['other_account_tool'], False)])
def test_native_transport_and_exact_personal_catalog(package, transport, required, success):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node unavailable')
    script = Path(__file__).resolve().parents[1] / 'scripts/probe_native_mcp.mjs'
    result = subprocess.run([node, str(script)], input=json.dumps({'packageRoot': str(package),
        'server': 'personal', 'config': {'transport': transport} if transport else {}, 'requiredTools': required}),
        text=True, capture_output=True, timeout=10)
    assert (result.returncode == 0) == success
    assert result.stderr == ''
    if success:
        assert json.loads(result.stdout) == {'native_transport': 'streamable-http', 'personal_tools': True}
    else:
        assert result.stdout == ''
