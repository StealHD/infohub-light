"""Pinned SSH forced-command transport; no shell, remote command or config input."""
import asyncio
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from .managed_host import ManagedSetupError, ManagedReloadPending
from .manifest import validate_receipt

ERROR = '远端自动接入未完成，请管理员检查托管连接；重试前将核对原状态。'


@dataclass(frozen=True)
class VerifiedInstallation:
    config_sha256: str


def protected_file(value):
    path = Path(value)
    if (not value or not path.is_absolute() or path.resolve() != path
            or not path.is_file() or stat.S_IMODE(path.stat().st_mode) & 0o077):
        raise ManagedSetupError('远端托管密钥或主机校验文件未安全配置。')
    return str(path)


def command():
    host = os.getenv('HORIZON_OPENCLAW_MANAGED_SSH_HOST', '')
    user = os.getenv('HORIZON_OPENCLAW_MANAGED_SSH_USER', '')
    port = os.getenv('HORIZON_OPENCLAW_MANAGED_SSH_PORT', '22')
    if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', host)
            or not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', user)
            or not port.isdigit() or not 1 <= int(port) <= 65535):
        raise ManagedSetupError('远端托管主机未配置。')
    identity = protected_file(os.getenv('HORIZON_OPENCLAW_MANAGED_SSH_KEY', ''))
    hosts = protected_file(os.getenv('HORIZON_OPENCLAW_MANAGED_SSH_KNOWN_HOSTS', ''))
    return ['ssh', '-F', '/dev/null', '-T', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10', '-o', 'LogLevel=ERROR',
            '-o', 'ClearAllForwardings=yes', '-o', 'ForwardAgent=no',
            '-o', 'UserKnownHostsFile=' + hosts, '-i', identity, '-p', port,
            user + '@' + host, 'inteliscope-managed-v1']


class SSHHost:
    def __init__(self, context):
        self.command = command()
        self.root = Path(context.store.data_dir)

    async def call(self, payload, advance=None):
        process = await asyncio.create_subprocess_exec(*self.command, stdin=asyncio.subprocess.PIPE,
                                                      stdout=asyncio.subprocess.PIPE,
                                                      stderr=asyncio.subprocess.DEVNULL, limit=65536)
        try:
            async with asyncio.timeout(150):
                process.stdin.write(json.dumps(payload).encode() + b'\n')
                await process.stdin.drain()
                result, count = None, 0
                while line := await process.stdout.readline():
                    count += len(line)
                    if count > 65536:
                        raise ValueError('Oversized host response')
                    message = json.loads(line)
                    if set(message) == {'phase'} and message['phase'] in {'stopping', 'removing', 'verifying'}:
                        if advance:
                            advance(message['phase'])
                        process.stdin.write(json.dumps({'phase_ack': message['phase']}).encode() + b'\n')
                        await process.stdin.drain()
                    elif set(message) == {'result'} and result is None:
                        result = message['result']
                    elif message == {'error': 'reload_pending'}:
                        raise ManagedReloadPending('Gateway 正在等待安全重载，请稍后继续核验。')
                    else:
                        raise ValueError('Invalid host response')
                if await process.wait() != 0 or result is None:
                    raise ValueError('Host operation incomplete')
                return result
        except ManagedReloadPending:
            raise
        except Exception:
            raise ManagedSetupError(ERROR) from None
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()

    async def install(self, manifest, token):
        proof = await self.call({'action': 'install', 'manifest': manifest, 'token': token})
        validate_receipt(manifest, token, proof)
        return VerifiedInstallation(proof['config_sha256'])

    async def remove(self, manifest, advance):
        result = await self.call({'action': 'remove', 'manifest': manifest}, advance)
        if result != {'binding_id': manifest['binding_id'], 'removed': True}:
            raise ManagedSetupError(ERROR)

    async def install_analysis(self, manifest, token):
        return await self.call({'action': 'install_analysis', 'manifest': manifest, 'token': token})
