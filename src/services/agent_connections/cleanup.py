"""Recoverable revocation worker, never restoring revoked authority."""
import json
import threading
from . import cleanup_store as journal
from .cleanup_host import CleanupHost, CleanupBlocked
from .managed_host import host_lock
from .service import AgentConnections
from .access_requests import AccessError

_lock = threading.Lock()
_running = set()


def public(context, user_id, binding_id=None):
    row = journal.get(context.store, user_id, binding_id)
    result = journal.public(row)
    if result and result['phase'] not in {'complete', 'failed'}:
        with _lock:
            if (str(context.store.data_dir), row['binding_id']) not in _running:
                result['phase'] = 'recovery'
    return result


def start(context, row, actor):
    current = context.store.get_user(actor['id'])
    if (not current or not current['enabled'] or current['workspace_id'] != row['workspace_id']
            or (current['id'] != row['user_id'] and current['role'] not in {'owner', 'admin'})):
        raise AccessError('无权重试此清理。')
    if row['phase'] == 'complete':
        return
    key = (str(context.store.data_dir), row['binding_id'])
    with _lock:
        if key in _running:
            return
        _running.add(key)
    row = {**row, 'actor_id': current['id']}
    try:
        context.store.connect().execute('UPDATE agent_cleanup SET actor_id=? WHERE binding_id=?', (current['id'], row['binding_id']))
        context.store.connect().commit()
        journal.phase(context.store, row['binding_id'], 'queued')
        threading.Thread(target=run, args=(context, row, key), daemon=True, name='agent-cleanup').start()
    except Exception:
        with _lock:
            _running.discard(key)
        raise


def run(context, row, key):
    try:
        import asyncio
        manifest = json.loads(row['snapshot'])
        # Revoke bearer again on recovery; metadata denial was already committed.
        current = AgentConnections(context.store, context.secret_values).row(row['user_id'])
        if not current or current['binding_id'] != row['binding_id'] or current['state'] != 'revoked':
            raise AccessError('绑定已变化，未清理其他身份。')
        AgentConnections(context.store, context.secret_values).revoke(row['user_id'])
        host = CleanupHost(context)
        with host_lock(host.root):
            def advance(value):
                actor = context.store.get_user(row['actor_id'])
                if (not actor or not actor['enabled'] or actor['workspace_id'] != row['workspace_id']
                        or (actor['id'] != row['user_id'] and actor['role'] not in {'owner', 'admin'})):
                    raise AccessError('管理员权限已变化，清理待其他管理员接续。')
                journal.phase(context.store, row['binding_id'], value)
            asyncio.run(host.remove(manifest, advance))
        if context.store.get_active_agent_delegation_principal(manifest['delegation_id']):
            raise AccessError('数据授权尚未失效。')
        journal.phase(context.store, row['binding_id'], 'complete')
    except Exception as error:
        journal.phase(context.store, row['binding_id'], 'failed',
                      error.public_message if isinstance(error, CleanupBlocked) else
                      '权限已撤销，OpenClaw 清理待完成。请核对 Gateway、运行状态或配置冲突后重试清理。')
    finally:
        with _lock:
            _running.discard(key)
        context.store.close_current()
