"""Controlled semantic judgments; neither a model nor real notifications run."""
from datetime import datetime, timedelta, timezone
import pytest
from test_information_automation_rules import context  # noqa: F401
from test_information_automation_execution import acquire
from src.storage.information_connector_schema import apply_migration
from src.services.secret_store import SecretStore
from src.services.information_automations.connector_auth import provision, authenticate
from src.services.information_automations.semantic_claims import claim_work, submit_result
from src.services.information_automations.execution import evaluate_pending
from src.services.information_automations.rules import RuleError


def setup(ctx):
    store, rules, _, alice, _, _, config, _ = ctx
    apply_migration(store.connect())
    _, token = provision(store, SecretStore(store.data_dir), alice['id'])
    assert claim_work(store, rules.targets, token)['task'] is None
    now = datetime.now(timezone.utc)
    acquire(ctx, ['old'], now)
    semantic = config.model_copy(update={'requirement': 'Find new AI research backed by evidence.'})
    draft = rules.save(alice['id'], semantic)
    rules.transition(alice['id'], draft['id'], 1, 'enable')
    acquire(ctx, ['new'], now)
    evaluate_pending(store, rules.targets, now=now + timedelta(seconds=61))
    return store, rules, token, now + timedelta(seconds=62), draft, alice


def answer(task, status='matched', quote='AI research'):
    first = task['input'][0]
    identity = first.get('article_id') or first['evidence'][0]['article_id']
    return {'model':task['model']['id'],'output':{'status':status,'reason':'Controlled evidence','summary':'Combined conclusion',
            'covered_ids':[item['unit_id'] for item in task['input']],
            'evidence':[{'article_id':identity,'quote':quote,'note':'Evidence'}]}}


@pytest.mark.parametrize('status', ['matched', 'not_matched', 'insufficient'])
def test_result_is_fenced_idempotent_and_has_separate_notification_state(context, status):
    store, rules, token, now, draft, alice = setup(context)
    task = claim_work(store, rules.targets, token, now=now)['task']
    assert task and 'target_id' not in task and 'user_id' not in task
    assert claim_work(store, rules.targets, token, now=now)['reason'] == 'user_concurrency'
    result = answer(task, status)
    complete = submit_result(store, rules.targets, token, task['claim_id'], task['claim_token'], result, now=now)
    assert complete['status'] == status
    assert submit_result(store, rules.targets, token, task['claim_id'], task['claim_token'], result, now=now)['duplicate']
    with pytest.raises(RuleError):
        submit_result(store, rules.targets, token, task['claim_id'], task['claim_token'], {'changed': True}, now=now)
    run = rules.runs(alice['id'], draft['id'])['items'][0]
    assert run['notification_status'] == ('pending' if status == 'matched' else 'not_required')
    assert run['receipt'] is None


@pytest.mark.parametrize('kind', ['foreign_id', 'duplicate', 'quote', 'tools', 'missing'])
def test_malformed_model_outputs_cannot_authorize_a_notification(context, kind):
    store, rules, token, now, draft, alice = setup(context)
    task = claim_work(store, rules.targets, token, now=now)['task']
    result = answer(task)
    if kind == 'foreign_id': result['output']['evidence'][0]['article_id'] = 'foreign'
    elif kind == 'duplicate': result['output']['covered_ids'] *= 2
    elif kind == 'quote': result['output']['evidence'][0]['quote'] = 'invented evidence'
    elif kind == 'tools': result['tools'] = ['send_message']
    else: result['output']['covered_ids'] = []
    assert submit_result(store, rules.targets, token, task['claim_id'], task['claim_token'], result, now=now)['status'] == 'failed'
    assert rules.runs(alice['id'], draft['id'])['items'][0]['notification_status'] == 'not_required'


def test_restart_lease_recovery_rejects_late_result_and_counts_daily_quota(context):
    store, rules, token, now, _, _ = setup(context)
    old = claim_work(store, rules.targets, token, now=now)['task']
    store.close()
    retry = claim_work(store, rules.targets, token, now=now + timedelta(seconds=181), daily_limit=1)
    assert retry['reason'] == 'daily_semantic_limit' and retry['task'] is None
    with pytest.raises(RuleError):
        submit_result(store, rules.targets, token, old['claim_id'], old['claim_token'], answer(old), now=now + timedelta(seconds=182))
    assert store.connect().execute('SELECT status FROM information_runs').fetchone()[0] == 'quota_wait'


def test_pause_and_cross_user_credentials_reject_result(context):
    store, rules, token, now, draft, alice = setup(context)
    task = claim_work(store, rules.targets, token, now=now)['task']
    _, other = provision(store, SecretStore(store.data_dir), context[4]['id'])
    with pytest.raises(RuleError):
        submit_result(store, rules.targets, other, task['claim_id'], task['claim_token'], answer(task), now=now)
    rules.transition(alice['id'], draft['id'], 1, 'pause')
    assert submit_result(store, rules.targets, token, task['claim_id'], task['claim_token'], answer(task), now=now)['accepted'] is False
    context[2].revoke(alice['id'])
    with pytest.raises(RuleError): authenticate(store, token)


def test_personal_only_never_reaches_connector(context):
    import json
    store, rules, token, now, _, _ = setup(context)
    conn = store.connect()
    row = conn.execute('SELECT id,input_json FROM information_runs').fetchone()
    inputs = json.loads(row['input_json']); inputs[0]['analysis_mode'] = 'personal_only'
    conn.execute('UPDATE information_runs SET input_json=? WHERE id=?', (json.dumps(inputs), row['id'])); conn.commit()
    assert claim_work(store, rules.targets, token, now=now)['task'] is None
    assert conn.execute('SELECT status FROM information_runs').fetchone()[0] == 'insufficient'


def test_current_personal_only_subscription_blocks_previously_captured_input(context):
    store, rules, token, now, _, alice = setup(context)
    store.connect().execute("UPDATE user_subscriptions SET analysis_mode='personal_only' WHERE user_id=?", (alice['id'],))
    store.connect().commit()
    assert claim_work(store, rules.targets, token, now=now)['task'] is None
    assert store.connect().execute('SELECT count(*) FROM information_claims').fetchone()[0] == 0


def test_connector_revocation_pauses_confirmed_semantic_rules(context):
    from src.services.information_automations.connector_auth import revoke
    store, rules, token, _, draft, alice = setup(context)
    revoke(store, alice['id'])
    assert rules.get(alice['id'], draft['id'])['state'] == 'paused'
    assert rules.runs(alice['id'], draft['id'])['items'][0]['status'] == 'cancelled'
    with pytest.raises(RuleError): authenticate(store, token)
