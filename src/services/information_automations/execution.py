"""Worker-owned batching and keyword judgments; no network calls in this module."""
import json
import uuid
from datetime import datetime, timedelta, timezone

from ..user_content_store import UserContentStore
from .content import evidence_input
from .matching import keyword_match
from .rules import InformationRules, RuleConfig, RuleError, cancel_unsent, transaction, transport_generation
from .limits import BATCH_ITEMS, BATCH_INPUT_CHARACTERS, BATCH_WINDOW_SECONDS


def approved_context(rules, row):
    user = rules.actor(row['user_id'], write=True)
    config = RuleConfig.model_validate_json(row['config_json'])
    if row['state'] != 'active':
        raise RuleError('rule_inactive', '提醒已暂停。')
    binding = rules.binding(user)
    if binding['binding_id'] != row['binding_id']:
        raise RuleError('agent_binding_changed', '个人接入已变化，请重新确认。')
    rules.validate_sources(user, config)
    target = rules.target(user, config, require_ready=True)
    if not target or (target['config_generation'], target['activation_generation']) != (
            row['target_generation'], row['target_activation']):
        raise RuleError('notification_target_changed', '通知服务已变化，请重新确认。')
    if transport_generation(rules.store, user, target) != row['transport_generation']:
        raise RuleError('notification_transport_changed', '通知发送服务已变化，请重新确认。')
    return user, config, target


def pause_invalid(conn, row, reason, now):
    conn.execute("UPDATE information_rules SET state='paused',issue=?,updated_at=? WHERE id=?", (reason, now, row['id']))
    cancel_unsent(conn, row['id'], reason)


def collect_batch(store, row, config, events):
    inputs, ids, remaining, cursor = [], [], BATCH_INPUT_CHARACTERS - len(config.requirement) - 1024, row['cursor']
    for event in events:
        if len(inputs) >= BATCH_ITEMS or remaining <= 0:
            break
        cursor = event['id']
        if not set(config.source_ids) & set(json.loads(event['source_ids_json'])):
            continue
        stored = UserContentStore(store).get_item(workspace_id=row['workspace_id'], user_id=row['user_id'],
                                                  article_id=event['article_id'])
        evidence = evidence_input(stored, remaining) if stored else {
            'article_id': event['article_id'], 'title': '', 'text': '', 'truncated': True,
            'analysis_mode': 'full', 'source_ids': json.loads(event['source_ids_json'])}
        overhead = len(json.dumps(evidence, ensure_ascii=False)) - len(evidence['text']) + 2
        if overhead >= remaining and inputs:
            cursor = ids[-1]
            break
        if overhead >= remaining:
            raise RuleError('input_too_large', '单篇文章标识超过判断输入上限。')
        if len(evidence['text']) + overhead > remaining:
            evidence['text'] = evidence['text'][:remaining - overhead]
            evidence['truncated'] = True
        remaining -= len(json.dumps(evidence, ensure_ascii=False)) + 2
        inputs.append(evidence)
        ids.append(event['id'])
    return inputs, ids, cursor


def judge_keywords(inputs, config):
    evidence = []
    for item in inputs:
        matched = keyword_match(item['text'], config.conditions.model_dump())
        outcome = 'insufficient' if item['truncated'] else 'matched' if matched else 'not_matched'
        evidence.append({'article_id': item['article_id'], 'title': item.get('title', ''), 'status': outcome,
                         'reason': 'input_incomplete' if item['truncated'] else 'literal_keywords'})
    statuses = {item['status'] for item in evidence}
    status = 'matched' if 'matched' in statuses else 'insufficient' if 'insufficient' in statuses else 'not_matched'
    return status, evidence


def enqueue_rule(rules, row, now, *, window_seconds=BATCH_WINDOW_SECONDS):
    conn = rules.store.connect()
    try:
        _, config, _ = approved_context(rules, row)
    except RuleError as error:
        pause_invalid(conn, row, error.code, now.isoformat())
        return None
    events = conn.execute('''SELECT * FROM information_events WHERE user_id=? AND id>?
        ORDER BY id LIMIT 200''', (row['user_id'], row['cursor'])).fetchall()
    if not events or datetime.fromisoformat(events[0]['created_at']) + timedelta(seconds=window_seconds) > now:
        return None
    inputs, ids, cursor = collect_batch(rules.store, row, config, events)
    conn.execute('UPDATE information_rules SET cursor=? WHERE id=?', (cursor, row['id']))
    if not inputs:
        return None
    run_id = 'iarun_' + uuid.uuid4().hex
    status, evidence = judge_keywords(inputs, config) if config.mode == 'keyword' else ('pending', [])
    notification = 'pending' if status == 'matched' else 'not_required'
    stamp = now.isoformat()
    conn.execute('''INSERT INTO information_runs
        (id,rule_id,version,confirmation_id,status,notification_status,input_json,evidence_json,event_ids_json,ready_at,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''', (run_id, row['id'], row['version'], row['confirmation_id'], status, notification,
                                          json.dumps(inputs, ensure_ascii=False), json.dumps(evidence),
                                          json.dumps(ids), stamp, stamp, stamp))
    return run_id


def evaluate_pending(store, targets, *, now=None, limit=50, window_seconds=BATCH_WINDOW_SECONDS):
    now = now or datetime.now(timezone.utc)
    rules = InformationRules(store, targets)
    result = []
    # Round-robin validation also pauses revoked rules with empty queues.
    # Cursor and run publication commit together across competing Workers.
    with transaction(store) as conn:
        rows = conn.execute('''SELECT * FROM information_rules WHERE state='active'
            ORDER BY COALESCE(checked_at,''),id LIMIT ?''', (limit,)).fetchall()
        for row in rows:
            run_id = enqueue_rule(rules, dict(row), now, window_seconds=window_seconds)
            conn.execute('UPDATE information_rules SET checked_at=? WHERE id=?', (now.isoformat(), row['id']))
            if run_id:
                result.append(run_id)
    return result
