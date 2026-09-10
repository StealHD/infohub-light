"""Local-only provisioning boundary. No request-controlled path or executable."""
import asyncio
import fcntl
import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from ..agent_skill_gateway import AgentSkillGateway
from ..secret_store import SecretStore
from .gateway_config import configure, verify_config


class ManagedSetupError(ValueError):
    pass


class ManagedReloadPending(ManagedSetupError):
    pass


async def wait_loaded(gateway, socket):
    for attempt in range(20):
        state = await gateway._request(socket, 'setup-loaded', 'config.get', {})
        if state.get('configRevisionHash') and state.get('appliedConfigHash') == state['configRevisionHash']:
            return
        await asyncio.sleep(.5)
    raise ManagedReloadPending('Gateway 正在等待安全重载，请稍后继续核验。')


def loopback_url(value, schemes):
    parsed = urlsplit(value)
    if (parsed.scheme not in schemes or parsed.hostname not in {'127.0.0.1', '::1', 'localhost'}
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ManagedSetupError('仅允许本机测试环境，未执行配置。')
    return parsed


def local_root(mcp_url):
    if os.getenv('HORIZON_OPENCLAW_MANAGED_LOCAL_ENABLED') != 'true':
        raise ManagedSetupError('管理员尚未启用本机自动接入。')
    gateway = loopback_url(os.getenv('HORIZON_OPENCLAW_SERVER_URL', ''), {'ws', 'wss'})
    loopback_url(mcp_url, {'http', 'https'})
    raw = os.getenv('HORIZON_OPENCLAW_MANAGED_ROOT', '')
    root = Path(raw)
    if not raw or not root.is_absolute() or root.resolve() != root:
        raise ManagedSetupError('本机 OpenClaw 配置目录不可用。')
    for path in (root / 'openclaw.json', root / '.env'):
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ManagedSetupError('配置文件类型不安全，未执行配置。')
    config = json.loads((root / 'openclaw.json').read_text())
    settings = config.get('gateway', {})
    if settings.get('bind') != 'loopback' or settings.get('port', 18789) != gateway.port:
        raise ManagedSetupError('Gateway 与本机配置不一致，未执行配置。')
    return root


@contextmanager
def host_lock(root):
    fd = os.open(root / '.inteliscope-setup.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise ManagedSetupError('其他接入正在配置，请稍后重试。') from None
    try:
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def backup(root):
    directory = root / ('inteliscope-setup-backup-' + uuid.uuid4().hex)
    directory.mkdir(mode=0o700)
    for name in ('openclaw.json', '.env'):
        source = root / name
        if source.exists():
            fd = os.open(directory / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'wb') as handle:
                handle.write(source.read_bytes())
    return directory


class ManagedHost:
    def __init__(self, context):
        self.root = local_root(context.remote_mcp_settings.public_url)
        self.gateway = AgentSkillGateway(context.secret_values, context.store.data_dir)
        self.gateway._credentials()

    async def install(self, manifest, token):
        root = self.root
        before = (root / 'openclaw.json').read_bytes()
        config = json.loads(before)
        if config.get('gateway', {}).get('reload', {}).get('mode') == 'off':
            raise ManagedSetupError('Gateway 未启用安全热加载，未执行配置；请管理员检查。')
        target = configure(config, manifest, root)
        # Gateway validates patches against its normalized runtime config, where
        # legacy default=true markers have been stripped. Keep ownership explicit.
        target['agents']['ownership'] = 'explicit'
        for entry in target['agents']['entries'].values():
            if entry.get('default') is True:
                entry.pop('default')
        environment = SecretStore(root, filename='.env')
        prior_secret = environment.read().get(manifest['secret_ref'])

        async def operation(socket, hello):
            methods = hello.get('features', {}).get('methods', [])
            if not all(method in methods for method in ('config.get', 'config.patch', 'agents.list')):
                raise ManagedSetupError('本机 Gateway 不支持自动配置。')
            current = await self.gateway._request(socket, 'setup-config', 'config.get', {})
            if Path(current.get('path', '')) != root / 'openclaw.json' or not current.get('hash'):
                raise ManagedSetupError('Gateway 使用的配置文件与本机目标不一致。')
            if (root / 'openclaw.json').read_bytes() != before:
                raise ManagedSetupError('配置已被修改，请核对后重试。')
            if target != config or environment.read().get(manifest['secret_ref']) != token:
                backup(root)
                prior = environment.read().get(manifest['secret_ref'])
                if prior and prior != token:
                    raise ManagedSetupError('个人凭据存在冲突，未覆盖。')
                environment.set(manifest['secret_ref'], token)
                for field in ('workspace', 'agentDir'):
                    path = Path(target['agents']['entries'][manifest['agent_id']][field])
                    if path.resolve() != path:
                        raise ManagedSetupError('个人目录存在冲突。')
                    path.mkdir(mode=0o700, parents=True, exist_ok=True)
                # Only managed entries and isolation denies are submitted; never secrets or model settings.
                entries = {}
                for identity, entry in target['agents']['entries'].items():
                    old = config.get('agents', {}).get('entries', {}).get(identity)
                    if old != entry:
                        entries[identity] = entry if old is None else {
                            key: value for key, value in entry.items() if old.get(key) != value}
                        if old and old.get('default') is True:
                            entries[identity]['default'] = None
                patch = {'agents': {'ownership': 'explicit', 'entries': entries}, 'mcp': {'servers': {
                    manifest['mcp_server']: target['mcp']['servers'][manifest['mcp_server']]}}}
                if (root / 'openclaw.json').read_bytes() != before:
                    raise ManagedSetupError('配置已被修改；接入保留待验证，请核对后重试。')
                await self.gateway._request(socket, 'setup-patch', 'config.patch', {
                    'raw': json.dumps(patch), 'baseHash': current['hash'],
                    'note': 'Inteliscope personal Agent setup',
                    'replacePaths': [f'agents.entries.{identity}.tools.deny' for identity in entries],
                })
            from ..openclaw_relay.bridge import verify_agent
            await wait_loaded(self.gateway, socket)
            await verify_agent(socket, manifest['agent_id'])
        try:
            await asyncio.wait_for(self.gateway._session(operation), 90)
        except Exception:
            # Roll back only our credential when the configuration provably never changed.
            # Unknown/applied writes remain pending for read-before-retry; never restore a full snapshot.
            if (root / 'openclaw.json').read_bytes() == before:
                with environment._lock:
                    if environment.read().get(manifest['secret_ref']) == token:
                        environment.replace_many({manifest['secret_ref']: prior_secret})
            raise
        installed = json.loads((root / 'openclaw.json').read_text())
        verify_config(installed, manifest, root)
        if environment.read().get(manifest['secret_ref']) != token:
            raise ManagedSetupError('个人凭据校验失败。')
        return installed
