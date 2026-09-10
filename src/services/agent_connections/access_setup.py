"""Approved member provisioning, with actor/target separation and restart recovery."""
import asyncio
import threading
from .access_requests import AccessRequests, AccessError
from .service import AgentConnections
from . import managed_setup
from .managed_host import ManagedReloadPending

_lock = threading.Lock()
_running = set()


def identity(context, request_id):
    return str(context.store.data_dir), request_id


def project(context, row):
    if row and row.get('binding_id'):
        from .cleanup import public
        row = {**row, 'cleanup': public(context, row['user_id'], row['binding_id'])}
    if row and row['state'] == 'approved':
        row = dict(row)
        with _lock:
            running = identity(context, row['id']) in _running
        if running:
            target = context.store.get_user(row['user_id'])
            row['phase'] = managed_setup.status(context, target)['phase'] or 'checking'
        elif row['phase'] not in {'failed', 'waiting'}:
            row['phase'] = 'recovery'
    return row


def start(context, actor, request_id):
    requests = AccessRequests(context)
    row = requests.get(request_id, actor)
    target = requests.authorize(actor, row)
    if row['state'] != 'approved':
        raise AccessError('申请尚未允许或已完成。')
    key = identity(context, request_id)
    with _lock:
        if key in _running:
            return
        _running.add(key)
    try:
        threading.Thread(target=run, args=(context, dict(actor), dict(target), request_id),
                         daemon=True, name='approved-agent-setup').start()
    except Exception:
        with _lock:
            _running.discard(key)
        raise


def run(context, actor, target, request_id):
    try:
        requests = AccessRequests(context)
        def authorize():
            row = requests.get(request_id, actor)
            if row['state'] != 'approved':
                raise AccessError('申请授权已变化。')
            binding = AgentConnections(context.store, context.secret_values).row(target['id'])
            if row['binding_id'] and (not binding or binding['binding_id'] != row['binding_id'] or binding['state'] == 'revoked'):
                raise AccessError('本次接入授权已失效，不会恢复旧授权。')
            return requests.authorize(actor, row)
        def prepared(binding):
            requests.conn.execute('UPDATE agent_access_requests SET binding_id=? WHERE id=? AND state=\'approved\'',
                                  (binding['binding_id'], request_id))
            requests.conn.commit()
        with managed_setup._guard:
            managed_setup._operations[managed_setup.key(context, target)] = {
                'state': 'running', 'phase': 'checking', 'error': None}
        requests.conn.execute("UPDATE agent_access_requests SET phase='checking',error=NULL WHERE id=?", (request_id,))
        requests.conn.commit()
        # A new explicit approval permits a new identity after a prior revocation,
        # but never reactivates the old credential or silently creates shared access.
        asyncio.run(managed_setup.provision(context, target, reconnect=True, authorize=authorize, prepared=prepared))
        authorize()
        binding = AgentConnections(context.store, context.secret_values).live(target)
        if not binding:
            raise AccessError('个人绑定尚未通过验证。')
        requests.conn.execute("UPDATE agent_access_requests SET state='ready',phase=NULL,error=NULL,binding_id=?,revision=revision+1 WHERE id=? AND state='approved'",
                              (binding['binding_id'], request_id))
        requests.conn.commit()
    except Exception as error:
        waiting = isinstance(error, ManagedReloadPending)
        context.store.connect().execute("UPDATE agent_access_requests SET phase=?,error=? WHERE id=? AND state='approved'",
            ('waiting' if waiting else 'failed', 'Gateway 等待安全重载，请稍后继续核验。' if waiting else
             '配置未完成，请检查本机 Gateway 和成员状态；重试会核对同一绑定，不重复创建。', request_id))
        context.store.connect().commit()
    finally:
        with managed_setup._guard:
            managed_setup._operations.pop(managed_setup.key(context, target), None)
        with _lock:
            _running.discard(identity(context, request_id))
        context.store.close_current()
