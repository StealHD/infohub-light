"""Controlled end-to-end keyword dispatch; no network or real notification target."""
from datetime import datetime, timedelta, timezone

import pytest

from test_information_automation_rules import context  # noqa: F401
from src.services.information_automations.events import record_events
from src.services.information_automations.execution import evaluate_pending
from src.services.information_automations.delivery import dispatch_pending
from src.services.user_content_store import UserContentStore

ACK = {'channel': 'webhook', 'verification': 'http_accepted', 'provider': 'generic_event'}


def acquire(ctx, ids, now):
    store, _, _, alice, _, _, config, _ = ctx
    conn = store.connect()
    conn.execute('BEGIN IMMEDIATE')
    items = [{'id': name, 'title': 'AI ' + name, 'source_id': config.source_ids[0], 'content': 'AI research'} for name in ids]
    UserContentStore(store).upsert_items(workspace_id=alice['workspace_id'], user_id=alice['id'], items=items, seen_at=now.isoformat())
    record_events(conn, workspace_id=alice['workspace_id'], user_id=alice['id'], items=items,
                  successful_sources=config.source_ids, now=now.isoformat())
    conn.commit()


def active(ctx):
    store, rules, _, alice, _, _, config, _ = ctx
    now = datetime.now(timezone.utc)
    acquire(ctx, ['old'], now)
    draft = rules.save(alice['id'], config)
    rules.transition(alice['id'], draft['id'], 1, 'enable')
    return store, rules, alice, draft, now


def test_keyword_pipeline_batch_replay_and_verified_receipt(context):
    store, rules, alice, draft, now = active(context)
    acquire(context, ['old', 'new'], now)
    assert evaluate_pending(store, rules.targets, now=now) == []
    runs = evaluate_pending(store, rules.targets, now=now + timedelta(seconds=61))
    assert len(runs) == 1
    assert evaluate_pending(store, rules.targets, now=now + timedelta(seconds=61)) == []
    calls = []
    def send(user, target, payload):
        calls.append(payload)
        assert [item['id'] for item in payload['items']] == ['new']
        return ACK
    assert dispatch_pending(store, rules.targets, send) == ['sent']
    assert dispatch_pending(store, rules.targets, send) == [] and len(calls) == 1
    result = rules.runs(alice['id'], draft['id'])['items'][0]
    assert result['notification_status'] == 'sent' and result['receipt'] == ACK
    assert 'input_json' not in result and 'claim_hash' not in result


@pytest.mark.parametrize('interruption', ['unknown', 'missing_receipt', 'crash'])
def test_unknown_or_interrupted_send_never_retries(context, interruption):
    store, rules, alice, draft, now = active(context)
    acquire(context, ['new'], now)
    evaluate_pending(store, rules.targets, now=now + timedelta(seconds=61))
    calls = []
    def send(*_):
        calls.append(1)
        if interruption == 'crash':
            raise SystemExit('controlled crash')
        if interruption == 'unknown':
            raise TimeoutError('controlled timeout')
        return None
    if interruption == 'crash':
        with pytest.raises(SystemExit):
            dispatch_pending(store, rules.targets, send, now=now)
    else:
        assert dispatch_pending(store, rules.targets, send, now=now) == ['unknown']
    assert dispatch_pending(store, rules.targets, send, now=now + timedelta(minutes=6)) == []
    assert calls == [1]
    assert rules.runs(alice['id'], draft['id'])['items'][0]['notification_status'] == 'unknown'


@pytest.mark.parametrize('change', ['pause', 'binding', 'target', 'revision'])
def test_authority_rechecked_before_delivery(context, change):
    store, rules, alice, draft, now = active(context)
    acquire(context, ['new'], now)
    evaluate_pending(store, rules.targets, now=now + timedelta(seconds=61))
    if change == 'pause':
        rules.transition(alice['id'], draft['id'], 1, 'pause')
    elif change == 'binding':
        context[2].revoke(alice['id'])
    elif change == 'target':
        context[7]['config_generation'] += 1
    else:
        rules.save(alice['id'], context[6], rule_id=draft['id'], expected_version=1)
    def forbidden(*_):
        pytest.fail('invalid authorization reached transport')
    assert dispatch_pending(store, rules.targets, forbidden) == []
    assert rules.runs(alice['id'], draft['id'])['items'][0]['notification_status'] == 'cancelled'


def test_batch_and_daily_notification_limit_keep_queue(context):
    store, rules, alice, draft, now = active(context)
    acquire(context, [str(index) for index in range(21)], now)
    when = now + timedelta(seconds=61)
    assert len(evaluate_pending(store, rules.targets, now=when)) == 1
    assert len(evaluate_pending(store, rules.targets, now=when)) == 1
    assert dispatch_pending(store, rules.targets, lambda *_: ACK, now=when, daily_limit=1) == ['sent']
    statuses = {run['notification_status'] for run in rules.runs(alice['id'], draft['id'])['items']}
    assert statuses == {'sent', 'quota_wait'}
    assert dispatch_pending(store, rules.targets, lambda *_: ACK, now=when + timedelta(days=1), daily_limit=1) == ['sent']


def test_feed_publication_hook_is_atomic_and_independent_of_notification_opt_in(context):
    from test_feed_production import _config, _item, _outcome, _result
    from src.services.feed_production import FeedProductionService
    store, _, _, alice, _, _, config, _ = context
    source = config.source_ids[0]
    subscription = store.get_user_subscription_for_source(alice['id'], source)['id']
    production = FeedProductionService(store, _config())
    for index, article in enumerate(('baseline', 'new')):
        result = _result('run-' + str(index), 'succeeded', (_item(article, source, subscription),), (_outcome(source, subscription),))
        production.save_run_result(workspace_id=alice['workspace_id'], user_id=alice['id'], job_id='job-' + str(index),
                                   job_type='user_feed_refresh', result=result, active_source_ids={source}, commit=False)
        if index == 0:
            store.connect().commit()
        else:
            assert store.connect().execute('SELECT count(*) FROM information_events').fetchone()[0] == 1
            store.connect().rollback()
    assert store.connect().execute('SELECT count(*) FROM information_events').fetchone()[0] == 0
    assert store.connect().execute("SELECT count(*) FROM information_seen_items WHERE article_id='new'").fetchone()[0] == 0
