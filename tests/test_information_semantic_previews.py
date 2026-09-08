"""Semantic previews have no production watermark, approval or notification effects."""
import pytest
from test_information_automation_rules import context  # noqa: F401
from test_information_semantic_claims import setup, answer
from src.services.information_automations.semantic_claims import claim_work, submit_result
from src.services.information_automations.semantic_previews import get_preview
from src.services.information_automations.rules import RuleError


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


def test_preview_old_version_cannot_publish_result(context):
    store, rules, token, now, draft, alice = setup(context)
    preview = rules.test(alice['id'], draft['id'], 1, ['new'])
    task = claim_work(store, rules.targets, token, now=now)['task']
    config = context[6].model_copy(update={'requirement': 'changed'})
    rules.save(alice['id'], config, rule_id=draft['id'], expected_version=1)
    submit_result(store, rules.targets, token, task['claim_id'], task['claim_token'], answer(task), now=now)
    assert get_preview(rules, alice['id'], draft['id'], preview['preview_id'])['status'] == 'failed'
