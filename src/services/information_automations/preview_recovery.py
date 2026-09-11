"""Transaction-scoped deduplication and diagnostics for explicitly confirmed previews."""
import hashlib
import json
from datetime import datetime, timezone
from .rules import RuleError
from .execution_capability import capability
from ...storage.information_recovery_schema import ready


def fingerprint(user_id, rule_id, version, article_ids):
    return hashlib.sha256(json.dumps([user_id,rule_id,version,sorted(set(article_ids))], separators=(',',':')).encode()).hexdigest()


def existing(conn, user_id, request_id, digest):
    if request_id:
        row = conn.execute('SELECT * FROM information_preview_requests WHERE user_id=? AND request_id=?', (user_id,request_id)).fetchone()
        if row:
            if row['fingerprint'] != digest:
                raise RuleError('preview_request_conflict', '请求编号已用于其他测试。', 409)
            return row['preview_id']
    row = conn.execute('''SELECT p.id FROM information_previews p JOIN information_preview_confirmations c ON c.preview_id=p.id
        WHERE c.fingerprint=? AND c.superseded_by IS NULL AND (p.status IN ('pending','judging','quota_wait','completed') OR p.reason='completion_unknown')
        ORDER BY p.created_at DESC LIMIT 1''', (digest,)).fetchone()
    if row:
        remember(conn,user_id,request_id,digest,row['id'])
        return row['id']
    return None


def remember(conn, user_id, request_id, digest, identity):
    if request_id:
        conn.execute('INSERT INTO information_preview_requests VALUES(?,?,?,?)', (user_id,request_id,digest,identity))


def confirm(conn, user, rule, article_ids, identity, digest, now):
    old = conn.execute('''SELECT p.* FROM information_previews p LEFT JOIN information_preview_confirmations c ON c.preview_id=p.id
        WHERE p.user_id=? AND p.rule_id=? AND p.version=? AND c.preview_id IS NULL
        AND (p.status IN ('pending','quota_wait','judging') OR p.attempts>0)''', (user['id'],rule['id'],rule['version'])).fetchall()
    for row in old:
        ids = [item['article_id'] for item in json.loads(row['input_json'])]
        if set(ids) != set(article_ids):
            continue
        if row['attempts']:
            raise RuleError('completion_unknown', '旧测试已经领取，请先核对分析记录，不能自动重新推理。',409)
        conn.execute('INSERT INTO information_preview_confirmations VALUES(?,?,?,?)', (row['id'],digest,now,identity))
        conn.execute("UPDATE information_previews SET status='failed',reason='preview_superseded' WHERE id=?", (row['id'],))
    conn.execute('INSERT INTO information_preview_confirmations VALUES(?,?,?,NULL)', (identity,digest,now))


def diagnostics(store, row):
    conn = store.connect()
    if not ready(conn):
        return {'reason':'information_migration_required'}
    confirmation = conn.execute('SELECT * FROM information_preview_confirmations WHERE preview_id=?',(row['id'],)).fetchone()
    if row['reason'] == 'completion_unknown':
        return {'reason':'completion_unknown','requires_review':True}
    if row['status'] not in {'pending','judging','quota_wait'}:
        return {}
    if not confirmation:
        return {'reason':'completion_unknown' if row['attempts'] else 'preview_confirmation_required','requires_review':True}
    reason = capability(store,row['binding_id'])['execution_reason']
    if reason:
        return {'reason':reason}
    if row['status'] in {'pending','quota_wait'}:
        from .model_catalog import require_model
        from .config import RuleConfig
        rule = conn.execute('SELECT config_json FROM information_rules WHERE id=?',(row['rule_id'],)).fetchone()
        try:
            require_model(store,row['binding_id'],RuleConfig.model_validate_json(rule['config_json']).model)
        except RuleError as error:
            return {'reason':error.code}
    if row['status'] == 'pending' and conn.execute("SELECT 1 FROM information_claims WHERE user_id=? AND status='claimed' AND expires_at>?", (row['user_id'],datetime.now(timezone.utc).isoformat())).fetchone():
        return {'reason':'user_concurrency'}
    return {}


def latest_preview(rules, user_id, rule_id):
    rules.row(rules.actor(user_id),rule_id)
    row = rules.store.connect().execute('SELECT id FROM information_previews WHERE user_id=? AND rule_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(user_id,rule_id)).fetchone()
    if not row:
        return None
    from .semantic_previews import get_preview
    return get_preview(rules,user_id,rule_id,row['id'])


def request_preview(rules, user_id, rule_id, version, article_ids, request_id):
    conn = rules.store.connect()
    if not request_id or not ready(conn):
        return None
    row = conn.execute('SELECT * FROM information_preview_requests WHERE user_id=? AND request_id=?',(user_id,request_id)).fetchone()
    if not row:
        return None
    if row['fingerprint'] != fingerprint(user_id,rule_id,version,article_ids):
        raise RuleError('preview_request_conflict','请求编号已用于其他测试。',409)
    from .semantic_previews import get_preview
    return get_preview(rules,user_id,rule_id,row['preview_id'])
