"""Fence the supervisor and remove only an attested owned analysis installation."""
import hashlib
import json
from .analysis_manifest import objects
from .analysis_host import registry_path, write_registry
from .managed_host import ManagedSetupError, backup, host_lock, wait_loaded
from .cleanup_host import stop_owned
from ..secret_store import SecretStore


def validate_owned(config, owned, root):
    entry = config.get('agents', {}).get('entries', {}).get(owned['agent_id'])
    if entry is None:
        return
    expected = root / 'managed' / owned['agent_id']
    if (entry.get('workspace') != str(expected / 'workspace') or entry.get('agentDir') != str(expected / 'agent')
            or entry.get('tools', {}).get('allow') != ['llm-task'] or entry.get('subagents') != {'allowAgents': []}
            or entry.get('skills', []) != []):
        raise ManagedSetupError('分析 Agent 归属或权限已变化，未移除。')
    for identity, other in config['agents']['entries'].items():
        if identity != owned['agent_id'] and any(other.get(key) == entry.get(key) for key in ('workspace', 'agentDir')):
            raise ManagedSetupError('分析目录存在共享引用，未移除。')


async def remove(host, base):
    owned = objects(base)
    path = registry_path(host.root, base)
    config = json.loads((host.root / 'openclaw.json').read_text())
    if not path.exists():
        if owned['agent_id'] in config.get('agents', {}).get('entries', {}) or owned['secret_ref'] in SecretStore(host.root, filename='.env').read():
            raise ManagedSetupError('发现未登记的分析配置，需核对归属后清理。')
        return
    record = json.loads(path.read_text())
    if record.get('objects') != owned or record.get('base') != base:
        raise ManagedSetupError('分析清单已变化，未清理其他对象。')
    write_registry(path, {**record, 'state': 'revoked'})
    directory = host.root / 'managed' / owned['agent_id']
    if directory.resolve() != directory:
        raise ManagedSetupError('分析运行目录类型不安全。')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    async def stop(socket, hello):
        await stop_owned(host.gateway, socket, owned['agent_id'], allow_derived=True)
    # Request target-only stopping even while a completion still holds the lock.
    # A successful session stop does not prove an untracked HTTP completion ended.
    await host.gateway._session(stop)
    # An in-flight synchronous completion holds this lock. Do not declare it stopped.
    with host_lock(directory):
        from ..information_automations.completion_guard import uncertain
        if uncertain(directory / 'result.json'):
            raise ManagedSetupError('分析调用的结束状态尚未确认，权限保持撤销；请管理员核对后继续清理。')
        async def operation(socket, hello):
            await stop_owned(host.gateway, socket, owned['agent_id'], allow_derived=True)
            before = (host.root / 'openclaw.json').read_bytes()
            current_config = json.loads(before)
            validate_owned(current_config, owned, host.root)
            current = await host.gateway._request(socket, 'analysis-remove-read', 'config.get', {})
            if current.get('path') != str(host.root / 'openclaw.json') or not current.get('hash'):
                raise ManagedSetupError('Gateway 配置目录不匹配。')
            if (host.root / 'openclaw.json').read_bytes() != before:
                raise ManagedSetupError('配置同时被修改，未覆盖。')
            if owned['agent_id'] in current_config.get('agents', {}).get('entries', {}):
                backup(host.root)
                from .cleanup_config import remove_config
                remove_config(host.root, before, owned, agent_only=True)
            await wait_loaded(host.gateway, socket)
            agents = await host.gateway._request(socket, 'analysis-removed', 'agents.list', {})
            if not isinstance(agents.get('agents'), list) or any(row.get('id') == owned['agent_id'] for row in agents['agents']):
                raise ManagedSetupError('Gateway 尚未卸载分析身份。')
            await stop_owned(host.gateway, socket, owned['agent_id'])
        await host.gateway._session(operation)
        environment = SecretStore(host.root, filename='.env')
        with environment._lock:
            token = environment.read().get(owned['secret_ref'])
            if token is not None:
                if hashlib.sha256(token.encode()).hexdigest() != record['token_sha256']:
                    raise ManagedSetupError('分析凭据已变化，未覆盖。')
                backup(host.root)
                environment.delete(owned['secret_ref'])
        write_registry(path, {**record, 'state': 'removed'})
