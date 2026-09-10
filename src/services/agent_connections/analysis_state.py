"""Persistent installation phases; query paths never install or mint credentials."""
import json
from datetime import datetime, timezone
from ...storage.agent_analysis_schema import ready
from .analysis_manifest import objects
from .managed_host import ManagedSetupError


def record(store, base, phase, error=None):
    if not ready(store.connect()):
        raise ManagedSetupError('请管理员先完成自动化分析接入数据迁移。')
    now = datetime.now(timezone.utc).isoformat()
    changed = store.connect().execute('''INSERT INTO agent_analysis(binding_id,user_id,phase,objects_json,error,updated_at)
        SELECT ?,?,?,?,?,? WHERE ? IN ('revoking','removed') OR EXISTS(
            SELECT 1 FROM agent_connections WHERE binding_id=? AND user_id=? AND state='active')
        ON CONFLICT(binding_id) DO UPDATE SET phase=excluded.phase,error=excluded.error,
        revision=revision+1,updated_at=excluded.updated_at
        WHERE excluded.phase IN ('revoking','removed') OR agent_analysis.phase NOT IN ('revoking','removed')''',
        (base['binding_id'], base['user_id'], phase, json.dumps(objects(base)), error, now,
         phase, base['binding_id'], base['user_id'])).rowcount
    store.connect().commit()
    if not changed:
        raise ManagedSetupError('分析接入已撤销，未恢复安装状态。')


def public(store, binding_id):
    if not ready(store.connect()):
        return {'phase': 'not_configured', 'reason': 'migration_required'}
    row = store.connect().execute('SELECT phase,error,updated_at FROM agent_analysis WHERE binding_id=?', (binding_id,)).fetchone()
    if row and row['phase'] in {'ready', 'catalog_only'}:
        from ..information_automations.connector_auth import is_verified
        if not is_verified(store, binding_id):
            return {**dict(row), 'phase': 'offline'}
    return dict(row) if row else {'phase': 'not_configured', 'error': None}
