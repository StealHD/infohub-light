"""Fixed host-side analysis install; configuration and service ownership are derived."""
import json
import os
import uuid
from pathlib import Path
from .analysis_manifest import objects, validate_token
from .connector_config import configure
from .managed_host import ManagedSetupError, backup, wait_loaded
from ..secret_store import SecretStore
from ..information_automations.model_discovery import project_models


def registry_path(root, base):
    path = root / 'inteliscope-analysis' / (base['binding_id'] + '.json')
    if path.parent.is_symlink() or path.is_symlink():
        raise ManagedSetupError('分析运行目录类型不安全。')
    return path


def write_registry(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name('.' + uuid.uuid4().hex)
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def installation_options(prior):
    return {key:prior[key] for key in ("catalog_only","execution_mode") if key in prior} if prior else {"execution_mode":"previews_only"}


async def install(host, base, token):
    owned = objects(base)
    token_hash = validate_token(base, token)
    root = host.root
    registry = registry_path(root, base)
    before = (root / 'openclaw.json').read_bytes()
    config = json.loads(before)
    prior = json.loads(registry.read_text()) if registry.exists() else None
    if prior and (prior.get('objects') != owned or prior.get('token_sha256') != token_hash or prior.get('state') in {'revoked', 'removed'}):
        raise ManagedSetupError('分析配置归属或凭据已变化，未覆盖。')
    plugin = config.get('plugins', {}).get('entries', {}).get('llm-task', {})
    if plugin.get('enabled') is False or plugin.get('llm', {}).get('allowModelOverride') is False:
        raise ManagedSetupError('主机明确禁止独立分析，请管理员核对授权策略。')
    environment = SecretStore(root, filename='.env')
    previous = environment.read().get(owned['secret_ref'])
    if previous and previous != token:
        raise ManagedSetupError('分析专用凭据冲突，未覆盖。')
    async def operation(socket, hello):
        current = await host.gateway._request(socket, 'analysis-config', 'config.get', {})
        if current.get('path') != str(root / 'openclaw.json') or not current.get('hash'):
            raise ManagedSetupError('Gateway 配置目录不匹配。')
        models = await host.gateway._request(socket, 'analysis-models', 'models.list', {'view': 'configured', 'agentId': base['agent_id']})
        target, agent_id = configure(config, base, root)
        llm = target['plugins']['entries']['llm-task']['llm']
        created_policy = 'allowedCompletionModels' not in llm
        if created_policy:
            llm['allowedCompletionModels'] = [row['id'] for row in project_models(models, target)]
        if not llm['allowedCompletionModels']:
            raise ManagedSetupError('主机没有获准的独立分析模型，未放开全部模型。')
        if (root / 'openclaw.json').read_bytes() != before:
            raise ManagedSetupError('配置同时被修改，未覆盖。')
        if target != config or previous != token:
            backup(root)
            write_registry(registry, {'base': base, 'objects': owned, 'token_sha256': token_hash,
                                     'state': 'installing', **installation_options(prior)})
            environment.set(owned['secret_ref'], token)
            for field in ('workspace', 'agentDir'):
                path = Path(target['agents']['entries'][agent_id][field])
                if path.resolve() != path:
                    raise ManagedSetupError('分析目录存在归属冲突。')
                path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                path.mkdir(mode=0o700, parents=True, exist_ok=True)
            entries = {key: value for key, value in target['agents']['entries'].items()
                       if config['agents']['entries'].get(key) != value}
            await host.gateway._request(socket, 'analysis-patch', 'config.patch', {
                'baseHash': current['hash'], 'raw': json.dumps({'agents': {'entries': entries},
                    'plugins': {'entries': {'llm-task': target['plugins']['entries']['llm-task']}}}),
                'note': 'Inteliscope isolated analysis setup',
                'replacePaths': [f'agents.entries.{key}.tools.deny' for key in entries],
            })
        await wait_loaded(host.gateway, socket)
        from ..openclaw_relay.bridge import verify_agent
        await verify_agent(socket, agent_id)
        installed = json.loads((root / 'openclaw.json').read_text())
        if configure(installed, base, root)[0] != installed:
            raise ManagedSetupError('分析配置未实际加载。')
        available = await host.gateway._request(socket, 'analysis-catalog', 'models.list', {'view': 'configured', 'agentId': agent_id})
        if created_policy:
            from .analysis_model_policy import record_policy
            record_policy(root,llm['allowedCompletionModels'])
        permitted = {row['id'] for row in project_models(models, installed)}
        # The supervisor's host setting defaults to catalog-only during deployment.
        write_registry(registry, {'base': base, 'objects': owned, 'token_sha256': token_hash,
                                 'state': 'installed', **installation_options(prior)})
        return {'binding_id': base['binding_id'], 'capabilities': {'protocol_version': 2,
                'models': [row for row in project_models(available, installed) if row['id'] in permitted]}}
    return await host.gateway._session(operation)
