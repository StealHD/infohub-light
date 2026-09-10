"""Bounded target-only stop and configuration removal; never agents.delete."""
import asyncio
import json
import hashlib
import os
from .managed_host import ManagedHost, ManagedSetupError, backup, wait_loaded
from .gateway_config import agent_entry, compatible_mcp
from ..secret_store import SecretStore
from .cleanup_config import remove_config


class CleanupBlocked(ManagedSetupError):
    public_message = '系统托管任务尚未确认回收，权限保持撤销；请稍后重试清理。'


def derived_monitor(job, agent):
    return (job.get('agentId') == agent and job.get('payload', {}).get('kind') == 'skillCollectionReview'
            and job.get('declarationKey') == 'skill-collection-review:' + agent)


def retain_monitors(directory, jobs, agent):
    records = [{key: job.get(key) for key in ('id', 'agentId', 'declarationKey', 'enabled', 'schedule')}
               for job in jobs if derived_monitor(job, agent)]
    if records:
        fd = os.open(directory / 'retained-monitor-records.json', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump({'retained_only': True, 'records': records}, handle)


async def rows(gateway, socket, method, field, params):
    result = []
    for offset in range(0, 10000, 100):
        page = await gateway._request(socket, 'cleanup-list', method, {**params, 'limit': 100, 'offset': offset})
        batch = page.get(field)
        if not isinstance(batch, list):
            raise ManagedSetupError('无法核实目标运行清单。')
        result.extend(batch)
        total = page.get('totalCount', page.get('total'))
        if isinstance(total, int) and len(result) >= total:
            return result
        if len(batch) < 100 and page.get('hasMore') is not True:
            return result
    raise ManagedSetupError('目标清单过大，请管理员检查。')


async def stop_owned(gateway, socket, agent, allow_derived=False):
    jobs = await rows(gateway, socket, 'cron.list', 'jobs', {'agentId': agent, 'includeDisabled': True})
    for job in jobs:
        if job.get('agentId') != agent or not isinstance(job.get('id'), str):
            raise ManagedSetupError('定时任务归属不明确，未批量停止。')
        if job.get('payload', {}).get('kind') == 'skillCollectionReview':
            if not derived_monitor(job, agent):
                raise ManagedSetupError('系统任务归属无法核验。')
            continue
        if job.get('enabled') is True:
            await gateway._request(socket, 'cleanup-disable', 'cron.update', {'id': job['id'], 'patch': {'enabled': False}})
    for attempt in range(20):
        sessions = await rows(gateway, socket, 'sessions.list', 'sessions',
                              {'agentId': agent, 'archived': 'all', 'includeGlobal': True, 'includeUnknown': True, 'configuredAgentsOnly': False})
        active = []
        for session in sessions:
            key = session.get('key', '')
            if session.get('agentId') != agent or not key.startswith('agent:' + agent + ':'):
                raise ManagedSetupError('会话归属不明确，未批量停止。')
            if not isinstance(session.get('hasActiveRun'), bool):
                raise ManagedSetupError('Gateway 未提供真实运行状态。')
            if session['hasActiveRun']:
                active.append(key)
        jobs = await rows(gateway, socket, 'cron.list', 'jobs', {'agentId': agent, 'includeDisabled': True})
        if any(job.get('agentId') != agent or (job.get('enabled') is not False and not derived_monitor(job, agent)) for job in jobs):
            raise ManagedSetupError('定时任务尚未确认停用。')
        cron_running = any(job.get('state', {}).get('runningAtMs') is not None for job in jobs)
        awaiting_reclaim = not allow_derived and any(derived_monitor(job, agent) for job in jobs)
        if not active and not cron_running and not awaiting_reclaim:
            return jobs
        for key in active:
            await gateway._request(socket, 'cleanup-stop', 'chat.abort', {'sessionKey': key, 'agentId': agent})
        await asyncio.sleep(.5)
    if awaiting_reclaim:
        raise CleanupBlocked()
    raise ManagedSetupError('停止尚未确认，请稍后重试清理。')


def check_owned(config, manifest, root):
    entries = config.get('agents', {}).get('entries', {})
    entry = entries.get(manifest['agent_id'])
    expected = agent_entry(manifest, root)
    if entry is not None and any(entry.get(key) != expected[key] for key in ('workspace', 'agentDir')):
        raise ManagedSetupError('目标 Agent 目录已变化，未移除配置。')
    server = config.get('mcp', {}).get('servers', {}).get(manifest['mcp_server'])
    if server is not None and not compatible_mcp(server, manifest):
        raise ManagedSetupError('目标 MCP 配置已变化，未移除配置。')
    if config.get('agents', {}).get('defaults', {}).get('authInheritance', {}).get('agentId') == manifest['agent_id']:
        raise ManagedSetupError('目标身份被共享授权引用，需管理员检查。')
    for identity, other in entries.items():
        if identity != manifest['agent_id'] and any(other.get(key) == expected[key] for key in ('workspace', 'agentDir')):
            raise ManagedSetupError('目标目录被其他 Agent 引用，未移除配置。')
    for name, other in config.get('mcp', {}).get('servers', {}).items():
        if name != manifest['mcp_server'] and manifest['secret_ref'] in json.dumps(other):
            raise ManagedSetupError('专用凭据被其他 MCP 引用，需管理员检查。')


class CleanupHost(ManagedHost):
    async def remove(self, manifest, advance):
        from .analysis_cleanup import remove as remove_analysis
        async def stop_personal(socket, hello):
            check_owned(json.loads((self.root / 'openclaw.json').read_text()), manifest, self.root)
            await stop_owned(self.gateway, socket, manifest['agent_id'], allow_derived=True)
        await self.gateway._session(stop_personal)
        await remove_analysis(self, manifest)
        root = self.root
        environment = SecretStore(root, filename='.env')
        async def operation(socket, hello):
            methods = hello.get('features', {}).get('methods', [])
            if not all(method in methods for method in ('config.get', 'agents.list', 'sessions.list', 'chat.abort', 'cron.list', 'cron.update')):
                raise ManagedSetupError('Gateway 不支持安全清理所需接口。')
            advance('stopping')
            check_owned(json.loads((root / 'openclaw.json').read_text()), manifest, root)
            jobs = await stop_owned(self.gateway, socket, manifest['agent_id'], allow_derived=True)
            advance('removing')
            before = (root / 'openclaw.json').read_bytes()
            config = json.loads(before)
            check_owned(config, manifest, root)
            credential = environment.read().get(manifest['secret_ref'])
            if credential is not None and hashlib.sha256(credential.encode()).hexdigest() != manifest['token_sha256']:
                raise ManagedSetupError('专用环境凭据已变化，未覆盖。')
            current = await self.gateway._request(socket, 'cleanup-config', 'config.get', {})
            if current.get('path') != str(root / 'openclaw.json') or not current.get('hash'):
                raise ManagedSetupError('Gateway 配置目录不匹配。')
            if (root / 'openclaw.json').read_bytes() != before:
                raise ManagedSetupError('配置同时被修改，请核对后重试。')
            present = manifest['agent_id'] in config.get('agents', {}).get('entries', {}) or manifest['mcp_server'] in config.get('mcp', {}).get('servers', {})
            if present:
                directory = backup(root)
                retain_monitors(directory, jobs, manifest['agent_id'])
                remove_config(root, before, manifest)
            advance('verifying')
            await wait_loaded(self.gateway, socket)
            installed = json.loads((root / 'openclaw.json').read_text())
            if manifest['agent_id'] in installed.get('agents', {}).get('entries', {}) or manifest['mcp_server'] in installed.get('mcp', {}).get('servers', {}):
                raise ManagedSetupError('目标配置仍存在。')
            for attempt in range(20):
                agents = await self.gateway._request(socket, 'cleanup-agents', 'agents.list', {})
                if isinstance(agents.get('agents'), list) and all(item.get('id') != manifest['agent_id'] for item in agents['agents']):
                    break
                await asyncio.sleep(.5)
            else:
                raise ManagedSetupError('Gateway 尚未卸载目标 Agent。')
            await wait_loaded(self.gateway, socket)
            await stop_owned(self.gateway, socket, manifest['agent_id'])
            with environment._lock:
                if environment.read().get(manifest['secret_ref']) is not None:
                    if environment.read().get(manifest['secret_ref']) != credential:
                        raise ManagedSetupError('环境文件同时被修改，未删除凭据。')
                    backup(root)
                    environment.delete(manifest['secret_ref'])
            if manifest['secret_ref'] in environment.read():
                raise ManagedSetupError('专用环境凭据尚未移除。')
        await asyncio.wait_for(self.gateway._session(operation), 90)
