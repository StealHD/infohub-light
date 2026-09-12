"""Account-owned setup coordinator; persistent bindings survive browser lifetimes."""
import asyncio
import threading

from .managed_host import ManagedSetupError, host_lock, local_root
from .host_dispatch import ManagedHost, installation_digest
from .manifest import receipt
from .service import AgentConnections
from .mcp_verification import check_mcp

_guard = threading.Lock()
_operations = {}


def key(context, user):
    return str(context.store.data_dir), user['id']


def status(context, user):
    available, reason = True, None
    try:
        if not context.remote_mcp_settings.enabled:
            raise ManagedSetupError('管理员尚未启用数据接入。')
        ManagedHost(context)
    except Exception:
        available, reason = False, '自动接入暂不可用，请管理员检查托管连接和管理凭据。'
    with _guard:
        operation = dict(_operations.get(key(context, user), {}))
    return {'available': available, 'state': operation.get('state', 'idle'),
            'phase': operation.get('phase'), 'error': operation.get('error') or reason}


def update(context, user, **fields):
    with _guard:
        _operations[key(context, user)].update(fields)


async def provision(context, user, reconnect=False, authorize=None, prepared=None):
    connections = AgentConnections(context.store, context.secret_values)
    host = ManagedHost(context)
    with host_lock(host.root):
        from .cleanup_store import pending
        if pending(context.store, user['id']):
            raise ManagedSetupError('OpenClaw 清理尚未完成，暂不能重新接入。')
        current_user = authorize() if authorize else context.store.get_user(user['id'])
        if not current_user or not current_user['enabled'] or (not authorize and current_user['role'] not in {'owner', 'admin'}):
            raise ManagedSetupError('当前账号无配置权限。')
        row = connections.row(user['id'])
        if row and row['state'] == 'revoked' and reconnect:
            connections.retire(user['id'])
            row = None
        if row and row['state'] != 'pending':
            if not connections.live(current_user):
                raise ManagedSetupError('绑定已撤销或失效，不会自动重建，请管理员检查。')
        update(context, user, phase='preparing')
        if not row:
            connections.prepare(user['id'], context.remote_mcp_settings.public_url)
        if prepared:
            prepared(connections.row(user['id']))
        manifest, token = connections.export(user['id'])
        if manifest['version'] != 3:
            from .manifest import USER_TOOLS, canonical
            manifest = {**manifest, 'version': 3, 'skills': manifest.get('skills', []), 'tools': list(USER_TOOLS)}
        update(context, user, phase='configuring')
        config = await host.install(manifest, token)
        if manifest['version'] == 3:
            from .manifest import canonical
            connections.store.connect().execute('UPDATE agent_connections SET manifest_json=? WHERE user_id=?',
                                              (canonical(manifest), user['id']))
            connections.store.connect().commit()
        update(context, user, phase='verifying')
        await asyncio.wait_for(check_mcp(manifest, token), 45)
        current_user = authorize() if authorize else context.store.get_user(user['id'])
        if not current_user or not current_user['enabled'] or (not authorize and current_user['role'] not in {'owner', 'admin'}):
            raise ManagedSetupError('账号权限已变化，接入未激活。')
        connections.activate(user['id'], receipt(manifest, token, installation_digest(config)))
        from .analysis_setup import install as install_analysis
        update(context, user, phase='analysis')
        await install_analysis(context, user, host, authorize)


def run(context, user, reconnect=False):
    try:
        asyncio.run(provision(context, user, reconnect))
        update(context, user, state='complete', phase=None, error=None)
    except ManagedSetupError as error:
        update(context, user, state='failed', phase=None, error=str(error))
    except Exception:
        # Never expose a Gateway response, secret, filesystem path or exception text.
        update(context, user, state='failed', phase=None,
               error='接入未完成。请检查本机 Gateway、管理授权和配置；重试会先核对原绑定，不会重复创建。')
    finally:
        context.store.close_current()


def start(context, user, reconnect=False):
    ManagedHost(context)  # Fail before accepting work or creating an identity.
    with _guard:
        identity = key(context, user)
        if _operations.get(identity, {}).get('state') == 'running':
            return
        _operations[identity] = {'state': 'running', 'phase': 'checking', 'error': None}
        threading.Thread(target=run, args=(context, dict(user), reconnect), daemon=True,
                         name='personal-agent-setup').start()
