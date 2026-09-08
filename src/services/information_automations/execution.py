"""Worker-owned trigger scheduling and durable batches; no network calls in this module."""
import json
import uuid
from datetime import datetime, timedelta, timezone

from ..user_content_store import UserContentStore
from .content import evidence_input
from .rules import InformationRules, RuleConfig, RuleError, cancel_unsent, transaction, transport_generation


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


def matching_events(conn, row, config, now):
    if not config.source_ids:
        return []
    marks = ','.join('?' for _ in config.source_ids)
    return conn.execute(f"""SELECT * FROM information_events WHERE user_id=? AND
        (id>? OR EXISTS(SELECT 1 FROM information_event_carry c WHERE c.rule_id=? AND c.event_id=information_events.id))
        AND created_at<=?
        AND EXISTS(SELECT 1 FROM json_each(source_ids_json) WHERE value IN ({marks})) ORDER BY id""",
        (row['user_id'], row['cursor'], row['id'], now.isoformat(), *config.source_ids)).fetchall()


def enqueue_rule(rules, row, now, **_):
    from .scheduling import advance_due, batch_cutoff, due_count
    from .batches import create_batch
    conn = rules.store.connect()
    try:
        _, config, _ = approved_context(rules, row)
    except RuleError as error:
        pause_invalid(conn, row, error.code, now.isoformat())
        return None
    clock = conn.execute('SELECT next_due FROM information_trigger_state WHERE rule_id=?', (row['id'],)).fetchone()
    scheduled = clock['next_due'] if clock else None
    events = matching_events(conn, row, config, batch_cutoff(config.trigger, scheduled, now))
    count = due_count(config.trigger, events, scheduled, now)
    if scheduled and datetime.fromisoformat(scheduled) <= now:
        due = advance_due(config.trigger, scheduled, now)
        conn.execute('UPDATE information_trigger_state SET next_due=? WHERE rule_id=?', (due.isoformat(), row['id']))
    if not count:
        return None
    selected, inputs = events[:count], []
    for event in selected:
        stored = UserContentStore(rules.store).get_item(workspace_id=row['workspace_id'], user_id=row['user_id'], article_id=event['article_id'])
        inputs.append(evidence_input(stored, 1000000) if stored else {
            'article_id': event['article_id'], 'title': '', 'text': '', 'truncated': True,
            'analysis_mode': 'full', 'source_ids': json.loads(event['source_ids_json'])})
    run_id, stamp = 'iarun_' + uuid.uuid4().hex, now.isoformat()
    conn.execute("""INSERT INTO information_runs
        (id,rule_id,version,confirmation_id,status,notification_status,input_json,event_ids_json,ready_at,created_at,updated_at)
        VALUES(?,?,?,?,'pending','not_required',?,?,?,?,?)""",
        (run_id,row['id'],row['version'],row['confirmation_id'],json.dumps(inputs,ensure_ascii=False),
         json.dumps([event['id'] for event in selected]),stamp,stamp,stamp))
    create_batch(conn, config, inputs, stamp, run_id=run_id)
    conn.execute('UPDATE information_rules SET cursor=MAX(cursor,?) WHERE id=?', (selected[-1]['id'], row['id']))
    conn.executemany('DELETE FROM information_event_carry WHERE rule_id=? AND event_id=?',[(row['id'],event['id']) for event in selected])
    return run_id


def evaluate_pending(store, targets, *, now=None, limit=50, **_):
    now = now or datetime.now(timezone.utc)
    rules = InformationRules(store, targets)
    result = []
    with transaction(store) as conn:
        rows = conn.execute("SELECT * FROM information_rules WHERE state='active' ORDER BY COALESCE(checked_at,''),id LIMIT ?", (limit,)).fetchall()
        for row in rows:
            run_id = enqueue_rule(rules, dict(row), now)
            conn.execute('UPDATE information_rules SET checked_at=? WHERE id=?', (now.isoformat(), row['id']))
            if run_id:
                result.append(run_id)
    return result
