"""Explicit reminder credentials preserve the original personal read binding."""
import pytest
from src.services.agent_connections.reminder_delegation import prepare, configure, TOOLS
from src.services.agent_connections.gateway_config import configure as base_configure
from src.services.secret_store import SecretStore
from tests.test_information_automation_rules import context  # noqa: F401


def test_separate_grant_is_idempotent_and_gateway_tools_remain_personal(context, tmp_path):
    store, _, bindings, alice, _, _, _, _ = context
    before = bindings.live(alice)
    manifest, token = prepare(store, SecretStore(store.data_dir), alice['id'])
    again, same_token = prepare(store, SecretStore(store.data_dir), alice['id'])
    assert again == manifest and same_token == token
    assert manifest['delegation_id'] != before['delegation_id']
    assert bindings.live(alice) == before
    config = base_configure({}, manifest['base'], tmp_path)
    target = configure(config, manifest, tmp_path)
    assert configure(target, manifest, tmp_path) == target
    personal = target['agents']['entries'][manifest['base']['agent_id']]
    assert all(manifest['mcp_server'] + '__' + tool in personal['tools']['allow'] for tool in TOOLS)
    assert manifest['mcp_server'] + '__*' in target['agents']['entries']['main']['tools']['deny']
    assert 'cron' in personal['tools']['deny']
    with pytest.raises(ValueError):
        configure(target, {**manifest, 'tools': [*TOOLS, 'send_notification']}, tmp_path)
