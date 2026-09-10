"""Verify installed native protocol parsing. Live Gateway inventory is a separate check."""
import asyncio
import json
import os
import shutil
from pathlib import Path
from .gateway_config import verify_config
from .managed_host import ManagedSetupError


async def check(root, manifest, token):
    config = json.loads((root / 'openclaw.json').read_text())
    verify_config(config, manifest, root)
    package = Path(os.getenv('INTELISCOPE_OPENCLAW_PACKAGE', ''))
    node = shutil.which('node')
    if not node or not package.is_absolute() or package.resolve() != package or not (package / 'openclaw.mjs').is_file():
        raise ManagedSetupError('安装版本的 MCP 验证未配置，请管理员检查主机适配器。')
    server = dict(config['mcp']['servers'][manifest['mcp_server']])
    server['headers'] = {'Authorization': 'Bearer ' + token}
    payload = {'packageRoot': str(package), 'server': manifest['mcp_server'],
               'config': server, 'requiredTools': manifest['tools']}
    script = Path(__file__).resolve().parents[3] / 'scripts' / 'probe_native_mcp.mjs'
    process = await asyncio.create_subprocess_exec(node, str(script), stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        output, _ = await asyncio.wait_for(process.communicate(json.dumps(payload).encode()), 55)
        if process.returncode or json.loads(output) != {'native_transport': 'streamable-http', 'personal_tools': True}:
            raise ValueError('Native verification failed')
    except BaseException as error:
        if process.returncode is None:
            process.kill()
            await process.wait()
        if isinstance(error, asyncio.CancelledError):
            raise
        raise ManagedSetupError('个人数据工具未通过安装版本的协议与调用验证，请管理员修复接入。') from None
