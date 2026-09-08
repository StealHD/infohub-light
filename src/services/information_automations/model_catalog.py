"""Machine-attested model metadata; browser input never grants model access."""
import json
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field
from .config import Term
from .rules import RuleError, transaction


class AvailableModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: Term
    name: Term
    thinking_levels: list[Term] = Field(default_factory=list, max_length=16)


class Capabilities(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    protocol_version: int = Field(ge=2, le=2)
    models: list[AvailableModel] = Field(max_length=500)


def sync_catalog(store, machine, capabilities, now=None):
    now = now or datetime.now(timezone.utc)
    models = capabilities.models
    if len({model.id for model in models}) != len(models):
        raise RuleError('invalid_model_catalog', '模型目录包含重复项。', 400)
    with transaction(store) as conn:
        encoded = json.dumps([model.model_dump() for model in models])
        previous = conn.execute('SELECT generation,models_json FROM information_model_catalog WHERE binding_id=?',(machine['binding_id'],)).fetchone()
        changed = not previous or previous['generation'] != machine['generation'] or previous['models_json'] != encoded
        conn.execute('''INSERT INTO information_model_catalog(binding_id,generation,models_json,updated_at,refresh_requested) VALUES(?,?,?,?,0)
            ON CONFLICT(binding_id) DO UPDATE SET generation=excluded.generation,models_json=excluded.models_json,
            updated_at=excluded.updated_at,refresh_requested=0''',
            (machine['binding_id'], machine['generation'], encoded, now.isoformat()))
        conn.execute('UPDATE information_connectors SET verified_at=?,last_seen=? WHERE binding_id=?',
                     (now.isoformat(), now.isoformat(), machine['binding_id']))
    return {'accepted': True, 'changed': bool(changed)}


def catalog(store, binding_id, now=None):
    now = now or datetime.now(timezone.utc)
    row = store.connect().execute('''SELECT m.*,c.enabled,c.generation AS current_generation FROM information_model_catalog m
        JOIN information_connectors c USING(binding_id) WHERE binding_id=?''', (binding_id,)).fetchone()
    valid = row and row['enabled'] and row['generation'] == row['current_generation']
    fresh = valid and 0 <= (now - datetime.fromisoformat(row['updated_at'])).total_seconds() <= 300
    return {'models': [model for model in json.loads(row['models_json']) if model['id'] not in json.loads(row['blocked_models_json'])] if valid else [], 'updated_at': row['updated_at'] if valid else None,
            'status': 'ready' if fresh else 'stale' if valid else 'unavailable'}


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
