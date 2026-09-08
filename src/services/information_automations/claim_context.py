"""Shared authorization and parent state transitions for batch steps."""
import json
from datetime import timedelta
from .rules import InformationRules, RuleConfig, RuleError
from .execution import approved_context
from .model_catalog import require_model
from .semantic_validation import apply_current_privacy, eligible
from .batches import finish


def parent_context(store, targets, batch, machine, now):
    conn = store.connect()
    table, identity = ('information_runs', batch['run_id']) if batch['run_id'] else ('information_previews', batch['preview_id'])
    parent = dict(conn.execute(f'SELECT * FROM {table} WHERE id=?', (identity,)).fetchone())
    rules = InformationRules(store, targets)
    user = rules.actor(machine['user_id'], write=True)
    rule = rules.row(user, parent['rule_id'])
    config = RuleConfig.model_validate_json(rule['config_json'])
    if parent['version'] != rule['version'] or rule['state'] == 'archived':
        raise RuleError('rule_changed', '规则已变化。')
    if batch['run_id']:
        approved_context(rules, rule)
        if parent['confirmation_id'] != rule['confirmation_id'] or parent['status'] not in {'pending','judging','quota_wait'}:
            raise RuleError('rule_changed', '规则确认或运行状态已变化。')
    else:
        rules.validate_sources(user, config)
        if parent['binding_id'] != machine['binding_id'] or parent['status'] not in {'pending','judging','quota_wait'}:
            raise RuleError('rule_changed', '测试或个人绑定已变化。')
    require_model(store, machine['binding_id'], config.model, now)
    inputs = apply_current_privacy(store, machine['user_id'], json.loads(parent['input_json']))
    if any(not eligible(item) for item in inputs):
        finish(conn, batch['id'], {'status':'insufficient','reason':'input_incomplete',
               'summary':'内容不完整或分析权限已变化。','evidence':[],'covered_ids':[]})
        raise RuleError('input_incomplete', '内容不完整或不允许分析。')
    return parent, config, inputs


def parent_state(conn, batch, state, reason=None, ready_at=None):
    table, identity = ('information_runs', batch['run_id']) if batch['run_id'] else ('information_previews', batch['preview_id'])
    conn.execute(f'UPDATE {table} SET status=?,reason=?,claim_hash=NULL WHERE id=?', (state,reason,identity))
    if ready_at:
        conn.execute(f'UPDATE {table} SET ready_at=? WHERE id=?', (ready_at,identity))


def context_error(conn, batch, error, now):
    if error.code == 'input_incomplete':
        return
    waiting = error.code in {'analysis_model_unavailable','analysis_thinking_unavailable'}
    parent_state(conn,batch,'pending' if waiting else 'cancelled' if batch['run_id'] else 'failed',error.code,
                 (now + timedelta(seconds=60)).isoformat() if waiting else None)
