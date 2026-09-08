"""Reminder delegation is opt-in and never grants activation or delivery."""
import pytest
from src.mcp.remote_information_tools import RemoteInformationService
from src.services.agent_change_proposal import DelegatedActor, AgentProposalError
from tests.test_information_automation_rules import context  # noqa: F401


def actor_for(store, user, access):
    grant, _ = store.create_agent_delegation(workspace_id=user['workspace_id'], user_id=user['id'],
                                            name='Reminder test', access=access)
    return DelegatedActor(workspace_id=user['workspace_id'], user_id=user['id'], role=user['role'],
                          delegation_id=grant['id'], scopes=tuple(grant['scopes']))


def test_old_delegation_cannot_read_or_prepare_and_new_draft_stays_inactive(context):
    store, rules, _, alice, _, _, config, _ = context
    service = RemoteInformationService(store, rules)
    old = actor_for(store, alice, 'read')
    for operation in (lambda: service.list_rules(actor=old), lambda: service.prepare(actor=old, config=config)):
        with pytest.raises(AgentProposalError) as failure:
            operation()
        assert failure.value.code == 'reminder_scope_required'
    actor = actor_for(store, alice, 'information_automations_draft')
    result = service.prepare(actor=actor, config=config)
    assert result['confirmation_card'] == '[[information-automation:' + result['draft_ref'] + ']]'
    assert rules.get(alice['id'], result['draft_ref'])['state'] == 'draft'
    assert store.connect().execute('SELECT count(*) FROM information_rule_approvals').fetchone()[0] == 0
    assert store.connect().execute('SELECT count(*) FROM information_runs').fetchone()[0] == 0


def test_read_profile_cannot_prepare_and_viewer_cannot_receive_draft_grant(context):
    store, rules, _, alice, bob, viewer, config, _ = context
    service = RemoteInformationService(store, rules)
    rules.save(alice['id'], config)
    actor = actor_for(store, bob, 'information_automations_read')
    assert service.list_rules(actor=actor)['items'] == []
    with pytest.raises(AgentProposalError):
        service.prepare(actor=actor, config=config)
    with pytest.raises(PermissionError):
        actor_for(store, viewer, 'information_automations_draft')
