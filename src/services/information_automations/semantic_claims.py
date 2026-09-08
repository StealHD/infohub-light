"""Durable semantic leases, quota accounting and fenced result acceptance."""
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from .connector_auth import authenticate, token_digest
from .execution import approved_context, pause_invalid
from .rules import InformationRules, RuleError, transaction
from .semantic_validation import eligible, validate_result, apply_current_privacy
from .limits import SEMANTIC_USER_DAILY_BATCHES

LEASE_SECONDS = 180
MAX_ATTEMPTS = 3


def expire_claims(conn, now):
    expired = conn.execute("""SELECT c.* FROM information_claims c WHERE c.status='claimed' AND (c.expires_at<=?
        OR EXISTS(SELECT 1 FROM information_runs r WHERE r.id=c.run_id AND r.status<>'judging')
        OR EXISTS(SELECT 1 FROM information_previews p WHERE p.id=c.preview_id AND p.status<>'judging'))""", (now.isoformat(),)).fetchall()
    for claim in expired:
        if claim['preview_id']:
            from .semantic_previews import expire_preview
            expire_preview(conn, claim, now, MAX_ATTEMPTS)
        run = conn.execute('SELECT * FROM information_runs WHERE id=?', (claim['run_id'],)).fetchone()
        if run and run['status'] == 'judging' and run['claim_hash'] == claim['token_hash']:
            state = 'pending' if run['attempts'] < MAX_ATTEMPTS else 'failed'
            conn.execute('UPDATE information_runs SET status=?,reason=?,claim_hash=NULL,lease_until=NULL,updated_at=? WHERE id=?',
                (state, 'semantic_lease_expired', now.isoformat(), run['id']))
        conn.execute("UPDATE information_claims SET status='expired',completed_at=? WHERE id=?", (now.isoformat(), claim['id']))


def claim_work(store, targets, machine_token, *, now=None, daily_limit=SEMANTIC_USER_DAILY_BATCHES):
    now = now or datetime.now(timezone.utc)
    with transaction(store) as conn:
        machine = authenticate(store, machine_token)
        conn.execute('UPDATE information_connectors SET last_seen=?,verified_at=COALESCE(verified_at,?) WHERE binding_id=?',
            (now.isoformat(), now.isoformat(), machine['binding_id']))
        expire_claims(conn, now)
        running = conn.execute("SELECT 1 FROM information_claims WHERE user_id=? AND status='claimed'", (machine['user_id'],)).fetchone()
        if running:
            return {'task': None, 'reason': 'user_concurrency', 'retry_after': 15}
        start = now.astimezone(ZoneInfo('Asia/Shanghai')).replace(hour=0, minute=0, second=0, microsecond=0)
        count = conn.execute('SELECT count(*) FROM information_claims WHERE user_id=? AND created_at>=?',
            (machine['user_id'], start.astimezone(timezone.utc).isoformat())).fetchone()[0]
        from .semantic_previews import claim_preview
        preview = claim_preview(store, machine, now, count, daily_limit, start)
        if preview is not None:
            return preview
        rows = conn.execute('''SELECT r.* FROM information_runs r JOIN information_rules q ON r.rule_id=q.id
            WHERE q.user_id=? AND r.status IN ('pending','quota_wait') AND r.ready_at<=?
            ORDER BY r.created_at,r.id LIMIT 50''', (machine['user_id'], now.isoformat())).fetchall()
        rules = InformationRules(store, targets)
        for row in rows:
            run = dict(row)
            rule = dict(conn.execute('SELECT * FROM information_rules WHERE id=?', (run['rule_id'],)).fetchone())
            try:
                _, config, _ = approved_context(rules, rule)
            except RuleError as error:
                pause_invalid(conn, rule, error.code, now.isoformat())
                continue
            if run['version'] != rule['version'] or run['confirmation_id'] != rule['confirmation_id']:
                conn.execute("UPDATE information_runs SET status='cancelled',reason='rule_changed' WHERE id=?", (run['id'],))
                continue
            if config.mode != 'semantic':
                continue
            if count >= daily_limit:
                tomorrow = (start + timedelta(days=1)).astimezone(timezone.utc).isoformat()
                conn.execute("UPDATE information_runs SET status='quota_wait',reason='daily_semantic_limit',ready_at=? WHERE id=?", (tomorrow, run['id']))
                return {'task': None, 'reason': 'daily_semantic_limit', 'retry_after': 60}
            inputs = apply_current_privacy(store, machine['user_id'], json.loads(run['input_json']))
            conn.execute('UPDATE information_runs SET input_json=? WHERE id=?', (json.dumps(inputs, ensure_ascii=False), run['id']))
            usable = [item for item in inputs if eligible(item)]
            if not usable:
                evidence = [{'article_id': item['article_id'], 'title': item['title'], 'status': 'insufficient',
                             'reason': 'personal_only' if item.get('analysis_mode') == 'personal_only' else 'input_incomplete'} for item in inputs]
                conn.execute("UPDATE information_runs SET status='insufficient',reason='input_incomplete',evidence_json=?,updated_at=? WHERE id=?",
                    (json.dumps(evidence), now.isoformat(), run['id']))
                continue
            claim_id, lease = 'icclaim_' + uuid.uuid4().hex, secrets.token_urlsafe(32)
            expires = (now + timedelta(seconds=LEASE_SECONDS)).isoformat()
            conn.execute('INSERT INTO information_claims (id,run_id,user_id,binding_id,connector_generation,token_hash,status,result_hash,created_at,expires_at,completed_at) VALUES(?,?,?,?,?,?,\'claimed\',NULL,?,?,NULL)',
                (claim_id, run['id'], machine['user_id'], machine['binding_id'], machine['generation'], token_digest(lease), now.isoformat(), expires))
            conn.execute("UPDATE information_runs SET status='judging',reason=NULL,claim_hash=?,lease_until=?,attempts=attempts+1,updated_at=? WHERE id=?",
                (token_digest(lease), expires, now.isoformat(), run['id']))
            return {'task': {'claim_id': claim_id, 'claim_token': lease, 'run_id': run['id'], 'agent_id': machine['agent_id'],
                            'requirement': config.requirement, 'articles': [{'article_id': item['article_id'], 'title': item['title'], 'text': item['text']} for item in usable],
                            'expires_at': expires}, 'retry_after': 0}
        return {'task': None, 'reason': 'empty', 'retry_after': 15}


def submit_result(store, targets, machine_token, claim_id, claim_token, result, *, now=None):
    now = now or datetime.now(timezone.utc)
    digest = token_digest(json.dumps(result, sort_keys=True, separators=(',', ':'), ensure_ascii=True))
    with transaction(store) as conn:
        machine = authenticate(store, machine_token)
        claim = conn.execute('SELECT * FROM information_claims WHERE id=? AND user_id=?', (claim_id, machine['user_id'])).fetchone()
        if not claim or claim['token_hash'] != token_digest(claim_token) or claim['binding_id'] != machine['binding_id'] or claim['connector_generation'] != machine['generation']:
            raise RuleError('claim_unauthorized', '任务领取凭据无效。', 403)
        if claim['status'] == 'completed':
            if claim['result_hash'] != digest:
                raise RuleError('result_conflict', '结果已提交，不可覆盖。')
            return {'accepted': True, 'duplicate': True}
        if claim['status'] != 'claimed' or claim['expires_at'] <= now.isoformat():
            raise RuleError('claim_expired', '任务领取已过期。')
        if claim['preview_id']:
            from .semantic_previews import finish_preview
            return finish_preview(store, claim, machine, result, digest, now)
        run = dict(conn.execute('SELECT * FROM information_runs WHERE id=?', (claim['run_id'],)).fetchone())
        rule = dict(conn.execute('SELECT * FROM information_rules WHERE id=?', (run['rule_id'],)).fetchone())
        rules = InformationRules(store, targets)
        if run['status'] != 'judging' or run['claim_hash'] != claim['token_hash'] or run['version'] != rule['version'] or run['confirmation_id'] != rule['confirmation_id']:
            raise RuleError('claim_superseded', '规则或任务已变化。')
        try:
            approved_context(rules, rule)
        except RuleError as error:
            pause_invalid(conn, rule, error.code, now.isoformat())
            conn.execute("UPDATE information_claims SET status='rejected',completed_at=? WHERE id=?", (now.isoformat(), claim_id))
            return {'accepted': False, 'reason': error.code}
        try:
            status, evidence = validate_result(result, apply_current_privacy(store, machine['user_id'], json.loads(run['input_json'])))
            reason = None
        except (ValueError, TypeError):
            status, evidence, reason = 'failed', [], ('semantic_model_unavailable' if result == {'error': 'isolated_completion_failed'} else 'invalid_model_output')
        conn.execute('''UPDATE information_runs SET status=?,notification_status=?,evidence_json=?,reason=?,result_hash=?,updated_at=? WHERE id=?''',
            (status, 'pending' if status == 'matched' else 'not_required', json.dumps(evidence, ensure_ascii=False), reason, digest, now.isoformat(), run['id']))
        conn.execute("UPDATE information_claims SET status='completed',result_hash=?,completed_at=? WHERE id=?", (digest, now.isoformat(), claim_id))
        return {'accepted': True, 'status': status, 'duplicate': False}


def maintain_semantic_leases(store):
    from ...storage.information_connector_schema import ready
    if ready(store.connect()):
        with transaction(store) as conn:
            expire_claims(conn, datetime.now(timezone.utc))
