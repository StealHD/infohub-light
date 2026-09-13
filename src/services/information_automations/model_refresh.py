"""Durable refresh receipts; only the matching successful sync releases model blocks."""
import json
import uuid
from datetime import datetime, timezone
from ...storage.information_recovery_schema import ready
from .rules import RuleError, transaction


def latest(conn, binding_id):
    if not ready(conn):
        return None
    row = conn.execute('''SELECT r.* FROM information_refresh_requests r JOIN information_connectors c
        ON c.binding_id=r.binding_id AND c.generation=r.generation WHERE r.binding_id=?
        ORDER BY r.rowid DESC LIMIT 1''', (binding_id,)).fetchone()
    return dict(row) if row else None


def public_refresh(conn, binding_id):
    row = latest(conn, binding_id)
    return {'refresh': {key: row[key] for key in ('id','status','requested_at','completed_at','reason','changed')} if row else None}


def request_refresh(store, binding_id):
    with transaction(store) as conn:
        if not ready(conn):
            raise RuleError('information_migration_required', '请先完成 global 45 迁移。', 503)
        connector = conn.execute('SELECT * FROM information_connectors WHERE binding_id=? AND enabled=1', (binding_id,)).fetchone()
        if not connector:
            raise RuleError('connector_upgrade_required', '请安装并启动分析执行器。', 409)
        now = datetime.now(timezone.utc)
        previous = latest(conn, binding_id)
        if not previous or previous['status'] != 'pending' or (now-datetime.fromisoformat(previous['requested_at'])).total_seconds() >= 120:
            if previous and previous['status'] == 'pending':
                conn.execute("UPDATE information_refresh_requests SET status='failed',reason='refresh_timeout',completed_at=? WHERE id=?", (now.isoformat(),previous['id']))
            conn.execute('''INSERT INTO information_refresh_requests(id,binding_id,generation,status,requested_at)
                VALUES(?,?,?,'pending',?)''', ('refresh_'+uuid.uuid4().hex,binding_id,connector['generation'],now.isoformat()))
        conn.execute('UPDATE information_model_catalog SET refresh_requested=1 WHERE binding_id=?', (binding_id,))
    return {'requested': True, **public_refresh(store.connect(),binding_id)}


def acknowledge(conn, machine, request_id, now, changed):
    current = latest(conn, machine['binding_id'])
    if not request_id or not current or current['id'] != request_id or current['status'] != 'pending':
        return
    conn.execute("UPDATE information_refresh_requests SET status='completed',completed_at=?,changed=? WHERE id=?",
                 (now.isoformat(),int(changed),request_id))
    conn.execute("UPDATE information_model_catalog SET refresh_requested=0,blocked_models_json='[]' WHERE binding_id=?", (machine['binding_id'],))


def control(store, machine, mode, runtime_block):
    """Record connector liveness without touching the OpenClaw model list."""
    if not ready(store.connect()):
        raise RuleError('information_migration_required', '请先完成 global 45 迁移。', 503)
    now = datetime.now(timezone.utc)
    with transaction(store) as conn:
        row = latest(conn, machine['binding_id'])
        catalog = conn.execute('''SELECT generation,updated_at FROM information_model_catalog
            WHERE binding_id=?''', (machine['binding_id'],)).fetchone()
        # The model directory is user-controlled OpenClaw configuration.  A
        # periodic worker must not refresh it: the Codex runtime starts an
        # online cache process for that read, which can interfere with an
        # isolated completion.  Initial setup, a changed connector generation,
        # and the explicit browser Refresh action are the only refresh paths.
        catalog_refresh_required = not catalog or catalog['generation'] != machine['generation']
        existing = conn.execute('SELECT filtered_json FROM information_execution_state WHERE binding_id=?',
                                (machine['binding_id'],)).fetchone()
        from .execution_capability import attest
        attest(conn, machine, mode, now, json.loads(existing['filtered_json']) if existing else (), runtime_block)
        conn.execute('UPDATE information_connectors SET verified_at=?,last_seen=? WHERE binding_id=?',
                     (now.isoformat(), now.isoformat(), machine['binding_id']))
    return {'refresh_request_id': row['id'] if row and row['status']=='pending' else None,
            'catalog_refresh_required': catalog_refresh_required}


def fail_refresh(store, machine, request_id):
    with transaction(store) as conn:
        row = latest(conn,machine['binding_id'])
        if row and row['id']==request_id and row['status']=='pending':
            conn.execute("UPDATE information_refresh_requests SET status='failed',reason='model_discovery_failed',completed_at=? WHERE id=?",
                         (datetime.now(timezone.utc).isoformat(),request_id))
    return {'accepted':True}
