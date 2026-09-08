"""Durable dispatch: uncertain attempts are terminal and never automatically resent."""
import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..notification_email_transport import WorkspaceEmailTransportService
from ..notification_webhook_transport import send_notification_webhook
from ..workspace_telegram_transport import WorkspaceTelegramTransportService
from .execution import approved_context, pause_invalid
from .rules import InformationRules, RuleError, transaction
from .limits import RULE_DAILY_NOTIFICATIONS


def notification_payload(run, config):
    matched = {row['article_id'] for row in json.loads(run['evidence_json']) if row['status'] == 'matched'}
    items = [{'id': item['article_id'], 'title': item['title'], 'summary': item['text'][:1000],
              'source_name': config.name} for item in json.loads(run['input_json']) if item['article_id'] in matched]
    return {'kind': 'information_reminder', 'rule_name': config.name, 'run_id': run['id'], 'items': items}


class ReminderTransport:
    def __init__(self, store, targets, data_dir):
        self.targets = targets
        self.email = WorkspaceEmailTransportService(store, data_dir=str(data_dir))
        self.telegram = WorkspaceTelegramTransportService(store, data_dir=str(data_dir))

    def __call__(self, user, target, payload):
        settings = self.targets.delivery_settings(target, user_id=user['id'])
        destination = settings['_resolved_destination']
        channel = target['channel']
        text = (payload['rule_name'] + '\n' + '\n\n'.join(
            item['title'] + '\n' + item['summary'] for item in payload['items']))[:4000]
        if channel == 'email':
            self.email.send_notification(workspace_id=user['workspace_id'], recipient_email=destination, payload=payload)
            return {'channel': channel, 'verification': 'smtp_accepted'}
        if channel == 'telegram':
            result = self.telegram.send_message(workspace_id=user['workspace_id'], chat_id=destination, text=text)
            return {'channel': channel, 'verification': result.verification, 'message_id': result.message_id}
        if channel != 'webhook':
            raise RuleError('notification_channel_unavailable', '通知渠道不可用。')
        result = asyncio.run(send_notification_webhook(provider=target['webhook_provider'], webhook_url=destination,
                            event='inteliscope.information_reminder', data=payload, text=text,
                            signing_secret=settings['_resolved_signing_secret']))
        return {'channel': channel, 'verification': result.verification, 'provider': result.provider}


def verified_receipt(value):
    if not isinstance(value, dict):
        return None
    channel, verification = value.get('channel'), value.get('verification')
    if (channel == 'email' and verification == 'smtp_accepted'):
        return {'channel': channel, 'verification': verification}
    if channel == 'telegram' and verification == 'provider_accepted' and type(value.get('message_id')) is int and value['message_id'] > 0:
        return {'channel': channel, 'verification': verification, 'message_id': value['message_id']}
    if channel == 'webhook' and verification in {'provider_accepted', 'http_accepted'}:
        provider = value.get('provider')
        if provider in {'generic_event', 'generic_text', 'feishu_lark_v2', 'wecom', 'dingtalk', 'slack', 'discord'}:
            return {'channel': channel, 'verification': verification, 'provider': provider}
    return None


def claim_delivery(rules, run_id, now, daily_limit):
    with transaction(rules.store) as conn:
        run_row = conn.execute('SELECT * FROM information_runs WHERE id=?', (run_id,)).fetchone()
        if not run_row or run_row['notification_status'] not in {'pending', 'quota_wait'}:
            return None
        run = dict(run_row)
        row = dict(conn.execute('SELECT * FROM information_rules WHERE id=?', (run['rule_id'],)).fetchone())
        if run['version'] != row['version'] or run['confirmation_id'] != row['confirmation_id'] or run['status'] != 'matched':
            conn.execute("UPDATE information_runs SET notification_status='cancelled',reason='rule_changed' WHERE id=?", (run_id,))
            return None
        try:
            user, config, target = approved_context(rules, row)
        except RuleError as error:
            pause_invalid(conn, row, error.code, now.isoformat())
            return None
        local_start = now.astimezone(ZoneInfo('Asia/Shanghai')).replace(hour=0, minute=0, second=0, microsecond=0)
        start = local_start.astimezone(timezone.utc).isoformat()
        count = conn.execute('SELECT count(*) FROM information_runs WHERE rule_id=? AND delivery_started_at>=?',
                             (row['id'], start)).fetchone()[0]
        if count >= daily_limit:
            tomorrow = (local_start + timedelta(days=1)).astimezone(timezone.utc).isoformat()
            conn.execute("UPDATE information_runs SET notification_status='quota_wait',reason='daily_notification_limit',ready_at=?,updated_at=? WHERE id=?",
                         (tomorrow, now.isoformat(), run_id))
            return None
        payload = notification_payload(run, config)
        if not payload['items']:
            conn.execute("UPDATE information_runs SET notification_status='failed',reason='missing_evidence' WHERE id=?", (run_id,))
            return None
        conn.execute("UPDATE information_runs SET notification_status='sending',reason=NULL,delivery_started_at=?,updated_at=? WHERE id=?",
                     (now.isoformat(), now.isoformat(), run_id))
        return user, target, payload


def settle_delivery(store, run_id, sender, claimed, now):
    receipt, reason = None, None
    try:
        receipt = verified_receipt(sender(*claimed))
        status = 'sent' if receipt else 'unknown'
        reason = None if receipt else 'unverified_receipt'
    except Exception as error:
        status = 'unknown' if getattr(error, 'outcome_unknown', True) else 'failed'
        code = getattr(error, 'code', '')
        reason = code if isinstance(code, str) and re.fullmatch('[a-z][a-z0-9_]{0,79}', code) else 'notification_failed'
    with transaction(store) as conn:
        conn.execute('''UPDATE information_runs SET notification_status=?,reason=?,receipt_json=?,updated_at=?
            WHERE id=? AND notification_status='sending' ''',
                     (status, reason, json.dumps(receipt) if receipt else None, now.isoformat(), run_id))
    return status


def dispatch_pending(store, targets, sender, *, now=None, limit=20, daily_limit=RULE_DAILY_NOTIFICATIONS):
    now = now or datetime.now(timezone.utc)
    rules = InformationRules(store, targets)
    with transaction(store) as conn:
        # A lost Worker/ACK cannot turn a started attempt back into pending.
        conn.execute("UPDATE information_runs SET notification_status='unknown',reason='delivery_interrupted',updated_at=? WHERE notification_status='sending' AND delivery_started_at<?",
                     (now.isoformat(), (now - timedelta(minutes=5)).isoformat()))
        pending = conn.execute("SELECT id FROM information_runs WHERE notification_status='pending' OR (notification_status='quota_wait' AND ready_at<=?) ORDER BY created_at,id LIMIT ?",
                               (now.isoformat(), limit)).fetchall()
    outcomes = []
    for row in pending:
        claimed = claim_delivery(rules, row['id'], now, daily_limit)
        if claimed:
            outcomes.append(settle_delivery(store, row['id'], sender, claimed, now))
    return outcomes
