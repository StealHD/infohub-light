"""Worker-only, at-most-once delivery of explicitly requested preview notices."""

import json
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ...storage.notification_extension_schema import ready
from .batches import progress
from .config import RuleConfig
from .content import original_url
from .delivery import notification_text, verified_receipt
from .limits import RULE_DAILY_NOTIFICATIONS
from .rules import InformationRules, RuleError, transaction
from .semantic_validation import apply_current_privacy, eligible


def _payload(conn, preview, config):
    result = progress(conn, preview_id=preview['id']).get('result')
    if not result or result['status'] != 'matched':
        return None
    source = {item['article_id']: item for item in json.loads(preview['input_json'])}
    items = []
    for identity in dict.fromkeys(item['article_id'] for item in result['evidence']):
        item = source.get(identity)
        if not item:
            return None
        url = original_url(item.get('url'))
        quotes = [entry['quote'] for entry in result['evidence'] if entry['article_id'] == identity]
        items.append({'id': identity, 'title': item['title'], 'summary': '；'.join(quotes),
                      'source_name': item.get('source_name') or config.name, 'url': url})
    if not items:
        return None
    return {'kind': 'information_reminder_test', 'rule_name': '【测试通知】' + config.name,
            'run_id': 'test:' + preview['id'], 'summary': result['summary'], 'reason': result['reason'],
            'items': items}


def _claim(rules, preview_id, now, daily_limit):
    with transaction(rules.store) as conn:
        record = conn.execute('SELECT * FROM information_preview_notifications WHERE preview_id=?', (preview_id,)).fetchone()
        if not record or record['status'] not in {'pending', 'quota_wait'}:
            return None
        preview = conn.execute('SELECT * FROM information_previews WHERE id=?', (preview_id,)).fetchone()
        rule = conn.execute('SELECT * FROM information_rules WHERE id=?', (preview['rule_id'],)).fetchone() if preview else None
        confirmation = conn.execute('SELECT superseded_by FROM information_preview_confirmations WHERE preview_id=?',
                                    (preview_id,)).fetchone()
        if not rule or not confirmation or confirmation['superseded_by'] or preview['status'] != 'completed' or rule['version'] != preview['version']:
            conn.execute("UPDATE information_preview_notifications SET status='cancelled',reason='preview_changed',updated_at=? WHERE preview_id=?",
                         (now.isoformat(), preview_id))
            return None
        try:
            user = rules.actor(preview['user_id'], write=True)
            binding = rules.binding(user)
            if binding['binding_id'] != preview['binding_id']:
                raise RuleError('agent_binding_changed', '个人接入已变化。')
            config = RuleConfig.model_validate_json(rule['config_json'])
            rules.validate_sources(user, config)
            target = rules.target(user, config.model_copy(update={'target_id': record['target_id']}), require_ready=True)
            if not target or (target['config_generation'], target['activation_generation']) != (
                    record['target_generation'], record['target_activation']):
                raise RuleError('notification_target_changed', '通知服务已变化。')
            if any(not eligible(item) for item in apply_current_privacy(rules.store, user['id'], json.loads(preview['input_json']))):
                raise RuleError('input_incomplete', '文章已不可用于通知。')
        except RuleError as error:
            conn.execute("UPDATE information_preview_notifications SET status='cancelled',reason=?,updated_at=? WHERE preview_id=?",
                         (error.code, now.isoformat(), preview_id))
            return None
        local_start = now.astimezone(ZoneInfo('Asia/Shanghai')).replace(hour=0, minute=0, second=0, microsecond=0)
        start = local_start.astimezone(timezone.utc).isoformat()
        count = conn.execute('SELECT count(*) FROM information_runs WHERE rule_id=? AND delivery_started_at>=?',
                             (rule['id'], start)).fetchone()[0]
        count += conn.execute('''SELECT count(*) FROM information_preview_notifications n
            JOIN information_previews p ON p.id=n.preview_id WHERE p.rule_id=? AND n.delivery_started_at>=?''',
            (rule['id'], start)).fetchone()[0]
        if count >= daily_limit:
            ready_at = (local_start + timedelta(days=1)).astimezone(timezone.utc).isoformat()
            conn.execute("UPDATE information_preview_notifications SET status='quota_wait',ready_at=?,reason='daily_notification_limit',updated_at=? WHERE preview_id=?",
                         (ready_at, now.isoformat(), preview_id))
            return None
        payload = _payload(conn, preview, config)
        if not payload:
            conn.execute("UPDATE information_preview_notifications SET status='failed',reason='missing_evidence',updated_at=? WHERE preview_id=?",
                         (now.isoformat(), preview_id))
            return None
        conn.execute("UPDATE information_preview_notifications SET status='sending',reason=NULL,delivery_started_at=?,updated_at=? WHERE preview_id=?",
                     (now.isoformat(), now.isoformat(), preview_id))
        return user, target, payload


def dispatch_preview_notifications(store, targets, sender, *, now=None, limit=20, daily_limit=RULE_DAILY_NOTIFICATIONS):
    if not ready(store.connect()):
        return []
    now = now or datetime.now(timezone.utc)
    with transaction(store) as conn:
        conn.execute("""UPDATE information_preview_notifications SET status='unknown',reason='delivery_interrupted',updated_at=?
            WHERE status='sending' AND delivery_started_at<?""",
            (now.isoformat(), (now - timedelta(minutes=5)).isoformat()))
        conn.execute("""UPDATE information_preview_notifications SET status='cancelled',reason='analysis_failed',updated_at=?
            WHERE status='waiting_analysis' AND preview_id IN
            (SELECT id FROM information_previews WHERE status IN ('failed','cancelled'))""", (now.isoformat(),))
        pending = conn.execute("""SELECT preview_id FROM information_preview_notifications
            WHERE status='pending' OR (status='quota_wait' AND ready_at<=?)
            ORDER BY created_at,preview_id LIMIT ?""", (now.isoformat(), limit)).fetchall()
    rules = InformationRules(store, targets)
    outcomes = []
    for item in pending:
        claimed = _claim(rules, item['preview_id'], now, daily_limit)
        if not claimed:
            continue
        try:
            receipt = verified_receipt(sender(*claimed))
            status = 'sent' if receipt else 'unknown'
            reason = None if receipt else 'unverified_receipt'
        except Exception as error:
            receipt = None
            status = 'unknown' if getattr(error, 'outcome_unknown', True) else 'failed'
            code = getattr(error, 'code', '')
            reason = code if isinstance(code, str) and re.fullmatch('[a-z][a-z0-9_]{0,79}', code) else 'notification_failed'
        with transaction(store) as conn:
            conn.execute("""UPDATE information_preview_notifications SET status=?,reason=?,receipt_json=?,updated_at=?
                WHERE preview_id=? AND status='sending'""",
                (status, reason, json.dumps(receipt) if receipt else None, now.isoformat(), item['preview_id']))
        outcomes.append(status)
    return outcomes
