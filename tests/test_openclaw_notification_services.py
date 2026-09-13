"""Gateway notification catalog and service tests never contact a real provider."""

import asyncio
from types import SimpleNamespace

import pytest

from src.services.openclaw_notification_services import OpenClawNotificationServices, OpenClawServiceError
from src.services.openclaw_notification_transport import OpenClawNotificationGateway, channel_accounts
from src.services.agent_skill_gateway import AgentSkillGatewayError
from src.storage.service_store import ServiceStore
from test_information_automation_rules import context  # noqa: F401


class FakeGateway:
    def __init__(self):
        self.calls = []
        self.accounts = [
            {'channel': 'telegram', 'account_id': 'primary', 'available': True},
            {'channel': 'telegram', 'account_id': 'secondary', 'available': True},
            {'channel': 'discord', 'account_id': 'default', 'available': False},
        ]

    def catalog(self):
        return self.accounts

    def send(self, **kwargs):
        self.calls.append(kwargs)
        return {'channel': 'openclaw', 'verification': 'provider_accepted', 'message_id': '123'}


def test_catalog_is_bounded_and_does_not_expose_credentials():
    rows = channel_accounts({'channelAccounts': {'telegram': [
        {'accountId': 'primary', 'configured': True, 'enabled': True, 'running': True,
         'lastError': None, 'token': 'never-public'},
        {'accountId': 'secondary', 'configured': True, 'enabled': False, 'running': True}]}})
    assert rows == [{'channel': 'telegram', 'channel_name': 'telegram', 'account_id': 'primary',
                     'account_name': 'primary', 'available': True},
                    {'channel': 'telegram', 'channel_name': 'telegram', 'account_id': 'secondary',
                     'account_name': 'secondary', 'available': False}]


def test_direct_send_requires_capability_and_receipt():
    gateway = OpenClawNotificationGateway.__new__(OpenClawNotificationGateway)
    calls = []
    async def session(operation):
        async def request(_, request_id, method, params):
            calls.append((method, params))
            return {'channel': 'telegram', 'messageId': '456'}
        gateway.gateway._request = request
        return await operation(None, {'features': {'methods': ['send', 'channels.status']}})
    gateway.gateway = SimpleNamespace(_session=session)
    receipt = gateway.send(channel='telegram', account_id='secondary', destination='-100123', message='hello',
                           message_thread_id=17, idempotency_key='preview-1')
    assert receipt['message_id'] == '456'
    assert calls == [('send', {'channel': 'telegram', 'accountId': 'secondary', 'to': '-100123',
                              'message': 'hello', 'idempotencyKey': 'preview-1', 'threadId': '17'})]
    async def denied(operation):
        return await operation(None, {'features': {'methods': ['channels.status']}})
    gateway.gateway._session = denied
    with pytest.raises(Exception, match='gateway_capability_unavailable'):
        gateway.send(channel='telegram', account_id='secondary', destination='-100123', message='hello',
                     idempotency_key='preview-2')

    async def uncertain(operation):
        async def request(*_):
            raise AgentSkillGatewayError('response unavailable')
        gateway.gateway._request = request
        return await operation(None, {'features': {'methods': ['send']}})
    gateway.gateway._session = uncertain
    with pytest.raises(Exception, match='gateway_outcome_unknown') as error:
        gateway.send(channel='telegram', account_id='secondary', destination='-100123', message='hello',
                     idempotency_key='preview-3')
    assert error.value.outcome_unknown is True


def test_service_topic_generation_and_write_only_destination(tmp_path, monkeypatch):
    monkeypatch.setenv('HORIZON_AUTH_USER', 'owner')
    monkeypatch.setenv('HORIZON_AUTH_PASSWORD', 'test-password')
    store = ServiceStore(tmp_path)
    store.initialize()
    gateway = FakeGateway()
    service = OpenClawNotificationServices(store, tmp_path, gateway)
    first = service.create('default', name='Research', channel='telegram', account='primary',
                           destination='-100123', topic=17)
    second = service.create('default', name='Research 2', channel='telegram', account='secondary',
                            destination='-100123', topic=18)
    public = service.list('default')
    assert len(public) == 2 and '-100123' not in str(public)
    assert first['message_thread_id'] == 17 and second['message_thread_id'] == 18
    tested = service.test_and_enable('default', first['id'])
    assert tested['sent'] is True and gateway.calls[0]['message_thread_id'] == 17
    current = service.row('default', first['id'])
    service.update('default', first['id'], name='Research updated')
    assert service.row('default', first['id'])['config_generation'] == current['config_generation']
    service.update('default', first['id'], topic=None)
    assert service.row('default', first['id'])['config_generation'] == current['config_generation'] + 1
    assert service.available(service.row('default', first['id'])) is False
    with pytest.raises(OpenClawServiceError):
        service.create('default', name='Unavailable', channel='discord', account='default', destination='#channel')
    store.close()


def test_automation_can_bind_openclaw_service_and_send_without_model(context, monkeypatch):
    from src.services.information_automations.delivery import ReminderTransport
    from src.services.secret_store import SecretStore
    store, rules, _, alice, _, _, config, _ = context
    fake = FakeGateway()
    service = OpenClawNotificationServices(store, store.data_dir, fake)
    target = service.create(alice['workspace_id'], name='OpenClaw automation', channel='telegram',
                            account='secondary', destination='-100123', topic=42)
    assert service.test_and_enable(alice['workspace_id'], target['id'])['sent']
    rules.targets.secret_store = SecretStore(store.data_dir)
    draft = rules.save(alice['id'], config.model_copy(update={'target_id': target['id']}))
    assert rules.transition(alice['id'], draft['id'], 1, 'enable')['state'] == 'active'
    monkeypatch.setattr(OpenClawNotificationGateway, 'catalog', lambda self: fake.catalog())
    monkeypatch.setattr(OpenClawNotificationGateway, 'send', lambda self, **kwargs: fake.send(**kwargs))
    sender = ReminderTransport(store, rules.targets, store.data_dir)
    receipt = sender(alice, {**service.row(alice['workspace_id'], target['id']), 'channel': 'openclaw'},
                     {'rule_name': 'Rule', 'summary': 'matched', 'reason': 'evidence', 'run_id': 'run-1',
                      'items': [{'title': 'Article', 'url': 'https://example.com/article'}]})
    assert receipt['message_id'] == '123'
    assert fake.calls[-1]['account_id'] == 'secondary' and fake.calls[-1]['message_thread_id'] == 42
