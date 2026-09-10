"""Authorized setup continuation after personal binding verification."""
import asyncio
from datetime import datetime, timezone
from . import analysis_state
from .service import AgentConnections
from .managed_host import ManagedSetupError
from ..information_automations.connector_auth import provision
from ..information_automations.model_catalog import Capabilities, catalog, sync_catalog


async def wait_service(context, binding_id, since, authorize):
    for _ in range(35):
        authorize()
        row = context.store.connect().execute('SELECT last_seen FROM information_connectors WHERE binding_id=? AND enabled=1', (binding_id,)).fetchone()
        if row and row['last_seen'] and datetime.fromisoformat(row['last_seen']) >= since:
            return
        await asyncio.sleep(1)
    raise ManagedSetupError('分析配置已安装，但分析服务尚未上线；请管理员检查托管服务后重试核验。')


async def install(context, user, host, authorize=None):
    connections = AgentConnections(context.store, context.secret_values)
    def authorized():
        actor = authorize() if authorize else context.store.get_user(user['id'])
        live = connections.live(actor) if actor and actor['enabled'] else None
        if (not live or actor['id'] != user['id'] or (not authorize and actor['role'] not in {'owner', 'admin'})):
            raise ManagedSetupError('账号或审批已变化，未继续配置分析服务。')
        return live
    live = authorized()
    base, _ = connections.export(user['id'])
    analysis_state.record(context.store, base, 'preparing')
    try:
        prior = context.store.connect().execute('SELECT enabled FROM information_connectors WHERE binding_id=?', (base['binding_id'],)).fetchone()
        if prior and not prior['enabled']:
            raise ManagedSetupError('原分析授权已撤销，修复不会自动恢复旧授权。请管理员核对后重新审批接入。')
        _, token = provision(context.store, context.secret_values, user['id'])
        authorized()
        analysis_state.record(context.store, base, 'configuring')
        started = datetime.now(timezone.utc)
        result = await host.install_analysis(base, token)
        if authorized()['binding_id'] != live['binding_id'] or result.get('binding_id') != live['binding_id']:
            raise ManagedSetupError('分析绑定已变化，未标记就绪。')
        from ..information_automations.connector_auth import authenticate
        sync_catalog(context.store, authenticate(context.store, token), Capabilities.model_validate(result['capabilities']), runtime_verified=False)
        phase = analysis_state.public(context.store, live['binding_id']).get('phase')
        if phase not in {'ready', 'catalog_only'}:
            analysis_state.record(context.store, base, 'catalog_ready' if catalog(context.store, live['binding_id'])['models'] else 'no_authorized_models')
        await wait_service(context, live['binding_id'], started, authorized)
    except Exception:
        analysis_state.record(context.store, base, 'failed', '自动化分析配置未完成，请管理员重试修复接入。')
        raise
