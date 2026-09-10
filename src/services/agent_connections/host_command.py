"""SSH forced command on the Gateway host. Only pinned-service install/remove."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from ..agent_skill_gateway import AgentSkillGateway
from ..secret_store import SecretStore
from .cleanup_host import CleanupHost
from .managed_host import ManagedHost, ManagedReloadPending, host_lock, local_root
from .manifest import validate_manifest, receipt, digest
from .mcp_verification import check_mcp


class Host(ManagedHost):
    def __init__(self, context):
        # Remote MCP is separately pinned to the deployment, never caller-selected.
        self.root = local_root('http://127.0.0.1/mcp')
        self.gateway = AgentSkillGateway(context.secret_values, context.store.data_dir)
        self.gateway._credentials()


class RemovalHost(Host, CleanupHost):
    pass


def validate_request(payload, mcp_url):
    if not isinstance(payload, dict) or payload.get('action') not in {'install', 'remove'}:
        raise ValueError('Invalid action')
    fields = {'action', 'manifest'} | ({'token'} if payload['action'] == 'install' else set())
    if set(payload) != fields:
        raise ValueError('Invalid fields')
    manifest = validate_manifest(payload['manifest'])
    url = urlsplit(mcp_url)
    if (url.scheme != 'https' or url.path != '/mcp' or url.username or url.password
            or url.query or url.fragment or not url.hostname or manifest['mcp_url'] != mcp_url):
        raise ValueError('MCP deployment mismatch')
    if payload['action'] == 'install':
        token = SecretStore.validate_value(payload['token'])
        if hashlib.sha256(token.encode()).hexdigest() != manifest['token_sha256']:
            raise ValueError('Credential mismatch')
    return manifest


async def execute(payload, context, emit):
    if payload == {'action': 'check'}:
        host = Host(context)
        async def check(socket, hello):
            config = await host.gateway._request(socket, 'host-check', 'config.get', {})
            if config.get('path') != str(host.root / 'openclaw.json'):
                raise ValueError('Gateway root mismatch')
            methods = hello.get('features', {}).get('methods', [])
            required = {'config.get', 'config.patch', 'agents.list', 'sessions.list', 'chat.abort', 'cron.list', 'cron.update'}
            if not required <= set(methods):
                raise ValueError('Missing managed capabilities')
            return {'ready': True}
        return await host.gateway._session(check)
    manifest = validate_request(payload, os.environ['INTELISCOPE_MANAGED_MCP_URL'])
    host = Host(context) if payload['action'] == 'install' else RemovalHost(context)
    with host_lock(host.root):
        journal = host.root / 'inteliscope-revoked'
        if journal.is_symlink():
            raise ValueError('Unsafe journal')
        journal.mkdir(mode=0o700, exist_ok=True)
        tombstone = journal / manifest['binding_id']
        if payload['action'] == 'install':
            if tombstone.exists():
                raise ValueError('Revoked identity cannot be reinstalled')
            installed = await host.install(manifest, payload['token'])
            await check_mcp(manifest, payload['token'])
            return receipt(manifest, payload['token'], digest(installed))
        # Persist the fence before side effects; retries never resurrect the identity.
        if not tombstone.exists():
            fd = os.open(tombstone, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w') as handle:
                handle.write(digest(manifest))
                handle.flush()
                os.fsync(handle.fileno())
        if tombstone.is_symlink() or tombstone.read_text() != digest(manifest):
            raise ValueError('Revocation manifest changed')
        await host.remove(manifest, lambda phase: emit({'phase': phase}))
        return {'binding_id': manifest['binding_id'], 'removed': True}
