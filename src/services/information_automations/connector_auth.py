"""Machine-only authentication bound to one live personal Agent."""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timezone
from ...storage.information_connector_schema import ready
from ..agent_connections.service import AgentConnections
from .rules import RuleError, transaction


def token_digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def provision(store, secret_store, user_id):
    if not ready(store.connect()):
        raise RuleError('connector_migration_required', '请先完成 connector 数据迁移。', 503)
    user = store.get_user(user_id)
    binding = AgentConnections(store, None).live(user) if user and user['enabled'] else None
    if not binding or user['role'] == 'viewer':
        raise RuleError('agent_binding_required', '需要有效个人绑定。')
    binding_id = binding['binding_id']
    ref = 'INTELISCOPE_CONNECTOR_' + binding_id.upper()
    current = store.connect().execute('SELECT * FROM information_connectors WHERE binding_id=?', (binding_id,)).fetchone()
    token = secret_store.read().get(ref)
    if current and current['enabled']:
        if not token or not hmac.compare_digest(current['token_hash'], token_digest(token)):
            raise RuleError('connector_secret_mismatch', '连接凭据需要管理员修复。')
        return {'binding_id': binding_id, 'secret_ref': ref, 'agent_id': binding['agent_id']}, token
    token = 'ih_ic_v1_' + binding_id + '.' + secrets.token_urlsafe(32)
    secret_store.set(ref, token)
    now = datetime.now(timezone.utc).isoformat()
    with transaction(store) as conn:
        conn.execute('''INSERT INTO information_connectors VALUES(?,?,?,1,1,NULL,NULL,?,?)
            ON CONFLICT(binding_id) DO UPDATE SET token_hash=excluded.token_hash,generation=generation+1,
            enabled=1,verified_at=NULL,last_seen=NULL,updated_at=excluded.updated_at''',
            (binding_id, user_id, token_digest(token), now, now))
    return {'binding_id': binding_id, 'secret_ref': ref, 'agent_id': binding['agent_id']}, token


def authenticate(store, token):
    if not ready(store.connect()):
        raise RuleError('connector_migration_required', 'Connector 数据未就绪。', 503)
    match = re.fullmatch(r'ih_ic_v1_([a-f0-9]{32})\.([A-Za-z0-9_-]{43})', token)
    row = store.connect().execute('SELECT * FROM information_connectors WHERE binding_id=?', (match[1],)).fetchone() if match else None
    if not row or not row['enabled'] or not hmac.compare_digest(row['token_hash'], token_digest(token)):
        raise RuleError('connector_unauthorized', 'Connector 凭据无效。', 401)
    user = store.get_user(row['user_id'])
    binding = AgentConnections(store, None).live(user) if user and user['enabled'] and user['role'] != 'viewer' else None
    if not binding or binding['binding_id'] != row['binding_id']:
        raise RuleError('connector_unauthorized', 'Connector 个人绑定失效。', 401)
    return {**dict(row), 'agent_id': binding['agent_id']}


def is_verified(store, binding_id):
    if not ready(store.connect()):
        return False
    row = store.connect().execute('SELECT * FROM information_connectors WHERE binding_id=?', (binding_id,)).fetchone()
    if not row or not row['enabled'] or not row['verified_at'] or not row['last_seen']:
        return False
    return 0 <= (datetime.now(timezone.utc) - datetime.fromisoformat(row['last_seen'])).total_seconds() <= 300


def revoke(store, user_id):
    if not ready(store.connect()):
        raise RuleError('connector_migration_required', 'Connector 数据未就绪。', 503)
    from .rules import cancel_unsent
    now = datetime.now(timezone.utc).isoformat()
    with transaction(store) as conn:
        conn.execute('UPDATE information_connectors SET enabled=0,verified_at=NULL,updated_at=? WHERE user_id=?', (now, user_id))
        rows = conn.execute("SELECT id FROM information_rules WHERE user_id=? AND state='active'", (user_id,)).fetchall()
        for row in rows:
            conn.execute("UPDATE information_rules SET state='paused',issue='connector_revoked',updated_at=? WHERE id=?", (now, row['id']))
            cancel_unsent(conn, row['id'], 'connector_revoked')
        conn.execute("UPDATE information_previews SET status='failed',reason='connector_revoked' WHERE user_id=? AND status IN ('pending','judging','quota_wait')", (user_id,))
