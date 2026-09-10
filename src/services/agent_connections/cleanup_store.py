"""Revocation authority precedes all remote work and survives process loss."""
import json
from datetime import datetime, timezone
from ...storage.agent_cleanup_schema import ready
from .service import AgentConnections
from .manifest import validate_manifest
from .access_requests import AccessError


def now():
    return datetime.now(timezone.utc).isoformat()


def get(store, user_id, binding_id=None):
    conn = store.connect()
    if not ready(conn):
        return None
    sql = 'SELECT * FROM agent_cleanup WHERE user_id=?'
    args = [user_id]
    if binding_id:
        sql += ' AND binding_id=?'
        args.append(binding_id)
    row = conn.execute(sql + ' ORDER BY created_at DESC LIMIT 1', args).fetchone()
    return dict(row) if row else None


def public(row):
    return {key: row[key] for key in ('phase', 'error', 'revision')} if row else None


def pending(store, user_id):
    row = get(store, user_id)
    return bool(row and row['phase'] != 'complete')


def begin(context, actor, target, request=None, revision=None):
    conn = context.store.connect()
    if not ready(conn):
        raise AccessError('请先完成撤销流程数据库迁移。')
    service = AgentConnections(context.store, context.secret_values)
    try:
        conn.execute('BEGIN IMMEDIATE')
        current = context.store.get_user(actor['id'])
        if not current or not current['enabled'] or current['workspace_id'] != target['workspace_id']:
            raise AccessError('无权撤销此接入。')
        if actor['id'] != target['id'] and current['role'] not in {'owner', 'admin'}:
            raise AccessError('无权撤销此接入。')
        binding = service.row(target['id'])
        if not binding:
            raise AccessError('没有可撤销的绑定。')
        if not request:
            own_request = conn.execute('SELECT * FROM agent_access_requests WHERE user_id=? AND binding_id=? ORDER BY created_at DESC LIMIT 1',
                                       (target['id'], binding['binding_id'])).fetchone()
            if own_request:
                request, revision = dict(own_request), own_request['revision']
        previous = get(context.store, target['id'], binding['binding_id'])
        if previous:
            if request and previous['request_id'] != request['id']:
                raise AccessError('申请与撤销记录不匹配。')
            conn.commit()
            return previous
        if request:
            row = conn.execute('SELECT * FROM agent_access_requests WHERE id=? AND workspace_id=?',
                               (request['id'], current['workspace_id'])).fetchone()
            if (not row or row['user_id'] != target['id'] or row['revision'] != revision
                    or row['state'] not in {'approved', 'ready'} or row['binding_id'] != binding['binding_id']):
                raise AccessError('申请或绑定已变化，请刷新核对。')
        manifest = json.loads(binding['manifest_json'])
        validate_manifest(manifest)
        conn.execute('INSERT INTO agent_cleanup VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                     (binding['binding_id'], target['id'], target['workspace_id'], actor['id'],
                      request['id'] if request else None, json.dumps(manifest), 'queued', None, 1, now(), now()))
        conn.execute("UPDATE agent_connections SET state='revoked' WHERE binding_id=?", (binding['binding_id'],))
        conn.execute('''UPDATE agent_delegations SET revoked_at=COALESCE(revoked_at,?),
                     revocation_reason=COALESCE(revocation_reason,'agent_binding_revoked'),updated_at=?
                     WHERE id=? AND user_id=? AND workspace_id=?''',
                     (now(), now(), manifest['delegation_id'], target['id'], target['workspace_id']))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    service.revoke(target['id'])
    return get(context.store, target['id'], binding['binding_id'])


def phase(store, binding_id, value, error=None):
    store.connect().execute('UPDATE agent_cleanup SET phase=?,error=?,revision=revision+1,updated_at=? WHERE binding_id=?',
                            (value, error, now(), binding_id))
    if value == 'complete':
        store.connect().execute("UPDATE agent_access_requests SET state='ready',revision=revision+1 WHERE binding_id=? AND state='approved'", (binding_id,))
    store.connect().commit()
