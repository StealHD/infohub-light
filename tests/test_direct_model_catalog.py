"""Configured OpenClaw model discovery never starts an analysis executor."""
from types import SimpleNamespace

import pytest

from tests.test_information_automation_rules import context  # noqa: F401
from src.services.secret_store import SecretStore
from src.services.information_automations.connector_auth import authenticate, provision
from src.services.information_automations.direct_model_catalog import refresh
from src.services.information_automations.model_catalog import Capabilities, catalog, sync_catalog
from src.services.information_automations.rules import RuleError


async def _models(*_args, **_kwargs):
    return {'models': [
        {'id': 'qwen3.5-plus', 'provider': 'alibaba', 'name': 'Qwen 3.5 Plus',
         'thinkingLevels': [{'id': 'low'}, {'id': 'high'}]},
        {'id': 'gpt-5.6-terra', 'provider': 'openai', 'name': 'GPT-5.6 Terra'},
        {'id': 'offline', 'provider': 'openai', 'available': False},
    ]}


def test_refresh_reads_personal_gateway_catalog_without_executor(context, monkeypatch, tmp_path):
    store, _, _, user, _, _, _, _ = context
    secrets = SecretStore(store.data_dir)
    secrets.set('HORIZON_OPENCLAW_SKILL_ADMIN_TOKEN', 'gateway-admin-token')
    captured = {}

    async def discover(url, token, agent_id, device_dir):
        captured.update(url=url, token=token, agent_id=agent_id, device_dir=device_dir)
        return await _models()

    from src.services.information_automations import direct_model_catalog
    monkeypatch.setattr(direct_model_catalog, 'rpc_models', discover)
    base, _ = provision(store, secrets, user['id'])
    binding_id = base['binding_id']
    prior_mode = catalog(store, binding_id)['execution_mode']
    result = refresh(store, secrets, SimpleNamespace(enabled=True, default_gateway_url='ws://127.0.0.1:13789'),
                     tmp_path, user['id'])

    assert [model['id'] for model in result['models']] == ['alibaba/qwen3.5-plus', 'openai/gpt-5.6-terra']
    assert result['models'][0]['thinking_levels'] == ['low', 'high']
    assert result['status'] == 'ready'
    assert result['execution_mode'] == prior_mode
    assert captured['url'] == 'ws://127.0.0.1:13789'
    assert captured['agent_id'].startswith('ih-')
    assert captured['token'] == 'gateway-admin-token'


def test_refresh_names_missing_gateway_authorization(context):
    store, _, _, user, _, _, _, _ = context
    with pytest.raises(RuleError) as failure:
        refresh(store, SecretStore(store.data_dir), SimpleNamespace(enabled=True, default_gateway_url='ws://127.0.0.1:13789'),
                store.data_dir, user['id'])
    assert failure.value.code == 'openclaw_gateway_credential_missing'


def test_refresh_does_not_change_existing_execution_capability(context, monkeypatch, tmp_path):
    store, _, _, user, _, _, _, _ = context
    secrets = SecretStore(store.data_dir)
    secrets.set('HORIZON_OPENCLAW_SKILL_ADMIN_TOKEN', 'gateway-admin-token')
    _, connector_token = provision(store, secrets, user['id'])
    machine = authenticate(store, connector_token)
    sync_catalog(store, machine, Capabilities(protocol_version=2, execution_mode='previews_only',
                                               models=[{'id': 'old/model', 'name': 'Old'}]))
    from src.services.information_automations import direct_model_catalog
    monkeypatch.setattr(direct_model_catalog, 'rpc_models', _models)

    result = refresh(store, secrets, SimpleNamespace(enabled=True, default_gateway_url='ws://127.0.0.1:13789'),
                     tmp_path, user['id'])

    assert result['execution_mode'] == 'previews_only'
    assert result['preview_executable'] is True
