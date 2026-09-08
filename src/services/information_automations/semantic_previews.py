"""Explicit semantic tests never create production runs, advance cursors or send."""
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from .connector_auth import is_verified, token_digest
from .content import evidence_input
from .rules import InformationRules, RuleConfig, RuleError, transaction
from .semantic_validation import eligible, validate_result, apply_current_privacy
from ..user_content_store import UserContentStore


def public_preview(row):
    return {'preview_id': row['id'], 'version': row['version'], 'status': row['status'], 'reason': row['reason'],
            'results': json.loads(row['results_json']), 'sends_notification': False, 'advances_cursor': False}


def get_preview(rules, user_id, rule_id, preview_id):
    rules.actor(user_id)
    rules.row(rules.actor(user_id), rule_id)
    row = rules.store.connect().execute('SELECT * FROM information_previews WHERE id=? AND user_id=? AND rule_id=?',
                                       (preview_id, user_id, rule_id)).fetchone()
    if not row:
        raise RuleError('not_found', '测试不存在。', 404)
    return public_preview(row)


def create_preview(rules, user, row, config, article_ids):
    binding = rules.binding(user)
    if not is_verified(rules.store, binding['binding_id']):
        raise RuleError('semantic_connector_required', '请先验证独立语义判断服务。')
    if not config.requirement.strip():
        raise RuleError('incomplete_rule', '请填写完整判断要求。')
    inputs, remaining = [], 32000 - len(config.requirement) - 1024
    for article_id in dict.fromkeys(article_ids):
        stored = UserContentStore(rules.store).get_item(workspace_id=user['workspace_id'], user_id=user['id'], article_id=article_id)
        if not stored:
            raise RuleError('not_found', '测试文章不存在。', 404)
        item = evidence_input(stored, max(0, remaining))
        if not set(config.source_ids) & set(item['source_ids']):
            raise RuleError('test_source_mismatch', '测试文章不属于所选来源。', 400)
        overhead = len(json.dumps(item, ensure_ascii=False)) - len(item['text']) + 2
        if remaining <= overhead:
            raise RuleError('test_input_too_large', '请选择更少的测试文章。', 400)
        if len(item['text']) + overhead > remaining:
            item['text'] = item['text'][:remaining-overhead]; item['truncated'] = True
        remaining -= len(json.dumps(item, ensure_ascii=False)) + 2
        inputs.append(item)
    now = datetime.now(timezone.utc).isoformat()
    identity = 'iapreview_' + uuid.uuid4().hex
    with transaction(rules.store) as conn:
        current = rules.row(rules.actor(user['id'], write=True), row['id'])
        if current['version'] != row['version']:
            raise RuleError('rule_version_conflict', '请刷新后重新测试。')
        pending = conn.execute("SELECT count(*) FROM information_previews WHERE user_id=? AND status IN ('pending','judging','quota_wait')", (user['id'],)).fetchone()[0]
        if pending >= 5:
            raise RuleError('preview_limit', '请等待已有测试完成。', 429)
        conn.execute('''INSERT INTO information_previews
            (id,rule_id,user_id,version,binding_id,input_json,requirement,status,ready_at,created_at)
            VALUES(?,?,?,?,?,?,?,'pending',?,?)''',
            (identity, row['id'], user['id'], row['version'], binding['binding_id'], json.dumps(inputs, ensure_ascii=False), config.requirement, now, now))
    return get_preview(rules, user['id'], row['id'], identity)


def expire_preview(conn, claim, now, max_attempts):
    row = conn.execute('SELECT * FROM information_previews WHERE id=?', (claim['preview_id'],)).fetchone()
    if row and row['status'] == 'judging' and row['claim_hash'] == claim['token_hash']:
        conn.execute('UPDATE information_previews SET status=?,reason=?,claim_hash=NULL WHERE id=?',
            ('pending' if row['attempts'] < max_attempts else 'failed', 'semantic_lease_expired', row['id']))


def claim_preview(store, machine, now, count, daily_limit, start):
    conn = store.connect()
    rows = conn.execute("SELECT * FROM information_previews WHERE user_id=? AND status IN ('pending','quota_wait') AND ready_at<=? ORDER BY created_at,id LIMIT 5",
                        (machine['user_id'], now.isoformat())).fetchall()
    for row in rows:
        rule = conn.execute('SELECT * FROM information_rules WHERE id=?', (row['rule_id'],)).fetchone()
        if row['binding_id'] != machine['binding_id'] or not rule or rule['version'] != row['version'] or rule['state'] == 'archived':
            conn.execute("UPDATE information_previews SET status='failed',reason='rule_changed' WHERE id=?", (row['id'],)); continue
        if count >= daily_limit:
            conn.execute("UPDATE information_previews SET status='quota_wait',reason='daily_semantic_limit',ready_at=? WHERE id=?",
                         ((start + timedelta(days=1)).astimezone(timezone.utc).isoformat(), row['id']))
            return {'task': None, 'reason': 'daily_semantic_limit', 'retry_after': 60}
        inputs = apply_current_privacy(store, machine['user_id'], json.loads(row['input_json']))
        conn.execute('UPDATE information_previews SET input_json=? WHERE id=?', (json.dumps(inputs, ensure_ascii=False), row['id']))
        usable = [item for item in inputs if eligible(item)]
        if not usable:
            results = [{'article_id': item['article_id'], 'title': item['title'], 'status': 'insufficient'} for item in inputs]
            conn.execute("UPDATE information_previews SET status='completed',results_json=? WHERE id=?", (json.dumps(results), row['id'])); continue
        claim_id, token = 'icclaim_' + uuid.uuid4().hex, secrets.token_urlsafe(32)
        expires = (now + timedelta(seconds=180)).isoformat()
        conn.execute('''INSERT INTO information_claims
            (id,preview_id,user_id,binding_id,connector_generation,token_hash,status,created_at,expires_at)
            VALUES(?,?,?,?,?,?,'claimed',?,?)''',
            (claim_id, row['id'], machine['user_id'], machine['binding_id'], machine['generation'], token_digest(token), now.isoformat(), expires))
        conn.execute("UPDATE information_previews SET status='judging',reason=NULL,claim_hash=?,attempts=attempts+1 WHERE id=?", (token_digest(token), row['id']))
        return {'task': {'claim_id': claim_id, 'claim_token': token, 'preview_id': row['id'], 'agent_id': machine['agent_id'],
                        'requirement': row['requirement'], 'articles': [{'article_id': item['article_id'], 'title': item['title'], 'text': item['text']} for item in usable],
                        'expires_at': expires}, 'retry_after': 0}
    return None


def finish_preview(store, claim, machine, result, digest, now):
    conn = store.connect()
    row = conn.execute('SELECT * FROM information_previews WHERE id=?', (claim['preview_id'],)).fetchone()
    rule = conn.execute('SELECT * FROM information_rules WHERE id=?', (row['rule_id'],)).fetchone()
    valid = (row['status'] == 'judging' and row['claim_hash'] == claim['token_hash'] and rule
             and rule['version'] == row['version'] and rule['state'] != 'archived' and row['binding_id'] == machine['binding_id'])
    try:
        if not valid:
            raise ValueError('changed')
        _, evidence = validate_result(result, apply_current_privacy(store, machine['user_id'], json.loads(row['input_json'])))
        status, reason = 'completed', None
    except (ValueError, TypeError):
        status, reason, evidence = 'failed', 'invalid_model_output' if valid else 'rule_changed', []
    conn.execute('UPDATE information_previews SET status=?,reason=?,results_json=? WHERE id=?', (status, reason, json.dumps(evidence, ensure_ascii=False), row['id']))
    conn.execute("UPDATE information_claims SET status='completed',result_hash=?,completed_at=? WHERE id=?", (digest, now.isoformat(), claim['id']))
    return {'accepted': True, 'status': status, 'duplicate': False}
