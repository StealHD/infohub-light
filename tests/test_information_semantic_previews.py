"""Semantic previews have no production watermark, approval or notification effects."""
import pytest
from test_information_automation_rules import context  # noqa: F401
from test_information_semantic_claims import setup, answer
from src.services.information_automations.semantic_claims import claim_work, submit_result
from src.services.information_automations.semantic_previews import get_preview
from src.services.information_automations.rules import RuleError
from src.services.information_automations.preview_delivery import dispatch_preview_notifications

ACK = {'channel': 'webhook', 'verification': 'http_accepted', 'provider': 'generic_event'}


def test_preview_claim_result_and_cross_account_read(context):
    store, rules, token, now, draft, alice = setup(context)
    before = dict(rules.row(alice, draft['id']))
    counts = tuple(store.connect().execute('SELECT (SELECT count(*) FROM information_runs),(SELECT count(*) FROM information_rule_approvals)').fetchone())
    preview = rules.test(alice['id'], draft['id'], 1, ['new'])
    assert preview['status'] == 'pending'
    task = claim_work(store, rules.targets, token, now=now)['task']
    assert task['preview_id'] == preview['preview_id']
    result = submit_result(store, rules.targets, token, task['claim_id'], task['claim_token'], answer(task), now=now)
    assert result['status'] == 'matched'
    retrieved = get_preview(rules, alice['id'], draft['id'], preview['preview_id'])
    assert retrieved['results'][0]['status'] == 'matched'
    assert retrieved['sends_notification'] is False and retrieved['advances_cursor'] is False
    assert dict(rules.row(alice, draft['id'])) == before
    assert tuple(store.connect().execute('SELECT (SELECT count(*) FROM information_runs),(SELECT count(*) FROM information_rule_approvals)').fetchone()) == counts
    with pytest.raises(RuleError):
        get_preview(rules, context[4]['id'], draft['id'], preview['preview_id'])


def test_preview_accepts_custom_text_without_reading_a_feed_article(context):
    store, rules, token, now, draft, alice = setup(context)
    preview = rules.test(alice['id'], draft['id'], 1, [], 'custom-text', custom_text={
        'text': 'NVIDIA announced a reset window for the research program.'})
    assert len(preview['selection']) == 1
    assert preview['selection'][0]['title'] == '自定义测试文本'
    assert preview['selection'][0]['id'].startswith('custom-test:')
    assert rules.test(alice['id'], draft['id'], 1, [], 'custom-text', custom_text={
        'text': 'NVIDIA announced a reset window for the research program.'})['preview_id'] == preview['preview_id']
    with pytest.raises(RuleError) as conflict:
        rules.test(alice['id'], draft['id'], 1, [], 'custom-text', custom_text={'text': 'different text'})
    assert conflict.value.code == 'preview_request_conflict'


def test_custom_text_preview_can_send_a_test_notification_without_a_source_link(context):
    store, rules, token, now, draft, alice = setup(context)
    preview = rules.test(alice['id'], draft['id'], 1, [], 'custom-notification', True, custom_text={
        'text': 'NVIDIA announced a reset window for the research program.'})
    task = claim_work(store, rules.targets, token, now=now)['task']
    submit_result(store, rules.targets, token, task['claim_id'], task['claim_token'], answer(task, quote='reset window'), now=now)
    calls = []
    assert dispatch_preview_notifications(store, rules.targets, lambda *args: calls.append(args) or ACK, now=now) == ['sent']
    payload = calls[0][2]
    assert payload['items'][0]['url'] == ''
    assert payload['rule_name'].startswith('【测试通知】')
    from src.services.information_automations.delivery import notification_text
    assert '自定义测试文本' in notification_text(payload)
    assert get_preview(rules, alice['id'], draft['id'], preview['preview_id'])['notification_status'] == 'sent'


def test_preview_old_version_cannot_publish_result(context):
    store, rules, token, now, draft, alice = setup(context)
    preview = rules.test(alice['id'], draft['id'], 1, ['new'])
    task = claim_work(store, rules.targets, token, now=now)['task']
    config = context[6].model_copy(update={'requirement': 'changed'})
    rules.save(alice['id'], config, rule_id=draft['id'], expected_version=1)
    submit_result(store, rules.targets, token, task['claim_id'], task['claim_token'], answer(task), now=now)
    assert get_preview(rules, alice['id'], draft['id'], preview['preview_id'])['status'] == 'failed'


def test_opt_in_preview_sends_only_after_match_and_only_once(context):
    store, rules, token, now, draft, alice = setup(context)
    preview = rules.test(alice['id'], draft['id'], 1, ['new'], 'request-one', True)
    assert preview['notification_status'] == 'waiting_analysis'
    assert rules.test(alice['id'], draft['id'], 1, ['new'], 'request-one', True)['preview_id'] == preview['preview_id']
    with pytest.raises(RuleError) as mismatch:
        rules.test(alice['id'], draft['id'], 1, ['new'], 'request-one', False)
    assert mismatch.value.code == 'preview_request_conflict'
    task = claim_work(store, rules.targets, token, now=now)['task']
    submit_result(store, rules.targets, token, task['claim_id'], task['claim_token'], answer(task), now=now)
    calls = []
    def sender(user, target, payload):
        calls.append(payload)
        assert payload['rule_name'].startswith('【测试通知】')
        return ACK
    assert dispatch_preview_notifications(store, rules.targets, sender, now=now) == ['sent']
    assert dispatch_preview_notifications(store, rules.targets, sender, now=now) == []
    result = get_preview(rules, alice['id'], draft['id'], preview['preview_id'])
    assert len(calls) == 1 and result['notification_status'] == 'sent'
    assert result['advances_cursor'] is False


def test_unmatched_preview_and_changed_target_never_send(context):
    store, rules, token, now, draft, alice = setup(context)
    preview = rules.test(alice['id'], draft['id'], 1, ['new'], send_notification=True)
    second = rules.test(alice['id'], draft['id'], 1, ['old'], send_notification=True)
    task = claim_work(store, rules.targets, token, now=now)['task']
    submit_result(store, rules.targets, token, task['claim_id'], task['claim_token'], answer(task, 'not_matched'), now=now)
    assert dispatch_preview_notifications(store, rules.targets, lambda *_: pytest.fail('unexpected send'), now=now) == []
    assert get_preview(rules, alice['id'], draft['id'], preview['preview_id'])['notification_status'] == 'not_required'
    task = claim_work(store, rules.targets, token, now=now)['task']
    submit_result(store, rules.targets, token, task['claim_id'], task['claim_token'], answer(task), now=now)
    context[7]['config_generation'] += 1
    assert dispatch_preview_notifications(store, rules.targets, lambda *_: pytest.fail('unexpected send'), now=now) == []
    assert get_preview(rules, alice['id'], draft['id'], second['preview_id'])['notification_status'] == 'cancelled'
