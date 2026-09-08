"""Connector installs a zero-tool-model entry without widening chat tools."""
from test_information_automation_rules import context  # noqa: F401
from src.services.agent_connections.gateway_config import configure as base_configure
from src.services.agent_connections.reminder_delegation import configure as reminder_configure, prepare
from src.services.agent_connections.connector_config import configure
from src.services.secret_store import SecretStore


def test_connector_and_reminder_reinstallation_preserve_namespace_policy(context, tmp_path):
    store, _, bindings, alice, _, _, _, _ = context
    base, _ = bindings.export(alice['id'])
    reminder, _ = prepare(store, SecretStore(store.data_dir), alice['id'])
    config = reminder_configure(base_configure({}, base, tmp_path), reminder, tmp_path)
    target, identity = configure(config, base, tmp_path)
    assert target['agents']['entries'][identity]['tools']['allow'] == ['llm-task']
    assert 'llm-task' in target['agents']['entries']['main']['tools']['deny']
    assert 'llm-task' in target['agents']['entries'][base['agent_id']]['tools']['deny']
    assert reminder_configure(target, reminder, tmp_path) == target
    assert configure(target, base, tmp_path)[0] == target
