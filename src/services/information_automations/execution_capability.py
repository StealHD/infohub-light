"""Execution permission is an explicit, generation-bound machine attestation."""
import json
from datetime import datetime, timezone
from ...storage.information_recovery_schema import ready
from .rules import RuleError

MODES = ('catalog_only', 'previews_only', 'full')
REASONS = {
    'information_migration_required': '请先完成 global 45 迁移。',
    'connector_upgrade_required': '分析执行器未上报执行能力，请升级执行器。',
    'offline': '分析服务离线，请检查执行器。',
    'execution_disabled': '分析服务仅同步目录，请切换为仅手动测试模式。',
    'completion_unknown': '先前推理是否完成未知，请管理员核对执行记录后恢复。',
    'formal_execution_disabled': '正式自动化执行尚未开启。',
}


def capability(store, binding_id, now=None):
    now = now or datetime.now(timezone.utc)
    conn = store.connect()
    if not ready(conn):
        return {'execution_mode': None, 'preview_executable': False, 'execution_reason': 'information_migration_required'}
    row = conn.execute('''SELECT e.*,c.enabled,c.generation AS current_generation,c.last_seen
        FROM information_connectors c LEFT JOIN information_execution_state e USING(binding_id)
        WHERE c.binding_id=?''', (binding_id,)).fetchone()
    reason = None
    if not row or not row['enabled'] or not row['last_seen'] or not 0 <= (now-datetime.fromisoformat(row['last_seen'])).total_seconds() <= 300:
        reason = 'offline'
    elif row['mode'] is None or row['generation'] != row['current_generation']:
        reason = 'connector_upgrade_required'
    elif not 0 <= (now-datetime.fromisoformat(row['updated_at'])).total_seconds() <= 300:
        reason = 'offline'
    elif row['runtime_block']:
        reason = row['runtime_block']
    elif row['mode'] == 'catalog_only':
        reason = 'execution_disabled'
    return {'execution_mode': row['mode'] if row else None, 'preview_executable': reason is None, 'execution_reason': reason, 'filtered_models': json.loads(row['filtered_json']) if row and row['mode'] else []}


def require_execution(store, binding_id, now=None, *, formal=False):
    value = capability(store, binding_id, now)
    reason = value['execution_reason']
    if not reason and formal and value['execution_mode'] != 'full':
        reason = 'formal_execution_disabled'
    if reason:
        raise RuleError(reason, REASONS[reason], 503 if reason in {'offline','information_migration_required'} else 409)
    return value


def attest(conn, machine, mode, now, filtered=(), runtime_block=None):
    if ready(conn) and mode is None:
        conn.execute('DELETE FROM information_execution_state WHERE binding_id=?',(machine['binding_id'],))
    if ready(conn) and mode is not None:
        conn.execute('''INSERT INTO information_execution_state VALUES(?,?,?,?,?,?)
            ON CONFLICT(binding_id) DO UPDATE SET generation=excluded.generation,
            mode=excluded.mode,updated_at=excluded.updated_at,filtered_json=excluded.filtered_json,runtime_block=excluded.runtime_block''',
            (machine['binding_id'], machine['generation'], mode, now.isoformat(),json.dumps(filtered),runtime_block))
