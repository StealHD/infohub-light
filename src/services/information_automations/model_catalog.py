"""Machine-attested model metadata; browser input never grants model access."""
import json
from typing import Literal
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field
from .config import Term
from .rules import RuleError, transaction


class AvailableModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: Term
    name: Term
    thinking_levels: list[Term] = Field(default_factory=list, max_length=16)


class FilteredModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: Term
    reason: Literal["allowlist_ownership_unknown", "model_unauthorized", "agent_model_unavailable"]


class Capabilities(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    protocol_version: int = Field(ge=2, le=2)
    catalog_only: bool = False
    execution_mode: Literal["catalog_only", "previews_only", "full"] | None = None
    refresh_request_id: Term | None = None
    runtime_block: Literal["completion_unknown"] | None = None
    filtered_models: list[FilteredModel] = Field(default_factory=list,max_length=500)
    models: list[AvailableModel] = Field(max_length=500)


def sync_catalog(store, machine, capabilities, now=None, *, runtime_verified=True):
    now = now or datetime.now(timezone.utc)
    models = sorted(capabilities.models,key=lambda model:model.id)
    if capabilities.catalog_only and capabilities.execution_mode not in {None,"catalog_only"}:
        raise RuleError("invalid_execution_mode","执行模式上报冲突。",400)
    if len({model.id for model in models}) != len(models):
        raise RuleError('invalid_model_catalog', '模型目录包含重复项。', 400)
    with transaction(store) as conn:
        current = conn.execute('SELECT enabled,generation FROM information_connectors WHERE binding_id=?', (machine['binding_id'],)).fetchone()
        if not current or not current['enabled'] or current['generation'] != machine['generation']:
            raise RuleError('connector_revoked', '分析服务授权已变化。', 403)
        from .model_refresh import latest
        request = latest(conn,machine['binding_id'])
        if capabilities.refresh_request_id and (not request or request['id'] != capabilities.refresh_request_id or request['status'] != 'pending'):
            return {'accepted':False,'changed':False,'reason':'refresh_superseded'}
        encoded = json.dumps([model.model_dump() for model in models])
        previous = conn.execute('SELECT generation,models_json FROM information_model_catalog WHERE binding_id=?',(machine['binding_id'],)).fetchone()
        changed = not previous or previous['generation'] != machine['generation'] or previous['models_json'] != encoded
        conn.execute('''INSERT INTO information_model_catalog(binding_id,generation,models_json,updated_at,refresh_requested) VALUES(?,?,?,?,0)
            ON CONFLICT(binding_id) DO UPDATE SET generation=excluded.generation,models_json=excluded.models_json,
            updated_at=excluded.updated_at''',
            (machine['binding_id'], machine['generation'], encoded, now.isoformat()))
        if runtime_verified:
            from .execution_capability import attest
            from .model_refresh import acknowledge
            attest(conn, machine, capabilities.execution_mode, now, [row.model_dump() for row in capabilities.filtered_models],capabilities.runtime_block)
            acknowledge(conn, machine, capabilities.refresh_request_id, now, changed)
            conn.execute('UPDATE information_connectors SET verified_at=?,last_seen=? WHERE binding_id=?',
                         (now.isoformat(), now.isoformat(), machine['binding_id']))
            from ...storage.agent_analysis_schema import ready
            if ready(conn):
                conn.execute("UPDATE agent_analysis SET phase=?,error=NULL,updated_at=? WHERE binding_id=? AND phase IN ('configuring','catalog_ready','catalog_only','ready','no_authorized_models','failed')",
                             ('no_authorized_models' if not models else 'catalog_only' if capabilities.catalog_only else 'ready', now.isoformat(), machine['binding_id']))
    return {'accepted': True, 'changed': bool(changed)}


def catalog(store, binding_id, now=None):
    now = now or datetime.now(timezone.utc)
    row = store.connect().execute('''SELECT m.*,c.enabled,c.last_seen,c.generation AS current_generation FROM information_model_catalog m
        JOIN information_connectors c USING(binding_id) WHERE binding_id=?''', (binding_id,)).fetchone()
    valid = row and row['enabled'] and row['generation'] == row['current_generation']
    online = valid and row['last_seen'] and 0 <= (now - datetime.fromisoformat(row['last_seen'])).total_seconds() <= 300
    fresh = online and 0 <= (now - datetime.fromisoformat(row['updated_at'])).total_seconds() <= 300
    models = [model for model in json.loads(row['models_json']) if model['id'] not in json.loads(row['blocked_models_json'])] if valid else []
    reason = 'not_configured' if not row else 'offline' if not online else 'catalog_stale' if not fresh else 'no_authorized_models' if not models else None
    from .execution_capability import capability
    from .model_refresh import public_refresh
    return {**capability(store, binding_id, now), **public_refresh(store.connect(), binding_id), 'models': models, 'updated_at': row['updated_at'] if valid else None,
            'status': 'ready' if fresh else 'stale' if valid else 'unavailable', 'reason': reason,
            'recovery_action': {'not_configured': 'repair_connection', 'offline': 'check_service',
                                'catalog_stale': 'refresh_catalog', 'no_authorized_models': 'review_models'}.get(reason)}


def require_model(store, binding_id, selection, now=None):
    value = catalog(store, binding_id, now)
    model = next((item for item in value['models'] if selection and item['id'] == selection.id), None)
    if value['status'] != 'ready' or not model:
        raise RuleError('analysis_model_unavailable', '请刷新 OpenClaw 模型目录并选择可用的独立分析模型。')
    if selection.thinking and selection.thinking not in model['thinking_levels']:
        raise RuleError('analysis_thinking_unavailable', '所选模型不支持此推理强度。')
    return model


def block_model(conn, binding_id, model_id):
    row = conn.execute('SELECT blocked_models_json FROM information_model_catalog WHERE binding_id=?',(binding_id,)).fetchone()
    blocked = set(json.loads(row['blocked_models_json'])) if row else set()
    blocked.add(model_id)
    conn.execute('UPDATE information_model_catalog SET blocked_models_json=? WHERE binding_id=?',(json.dumps(sorted(blocked)),binding_id))
