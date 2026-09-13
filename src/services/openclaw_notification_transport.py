"""Direct Gateway channel delivery without an Agent/model invocation."""

import asyncio
import uuid
from pathlib import Path

from .agent_skill_gateway import AgentSkillGateway, AgentSkillGatewayError


class OpenClawDeliveryError(RuntimeError):
    def __init__(self, code: str, *, outcome_unknown: bool = False):
        super().__init__(code)
        self.code = code
        self.outcome_unknown = outcome_unknown


def channel_accounts(payload):
    """Return a bounded, credential-free account catalog from channels.status."""
    accounts = payload.get('channelAccounts') if isinstance(payload, dict) else None
    if not isinstance(accounts, dict):
        return []
    result = []
    for channel, entries in accounts.items():
        if not isinstance(channel, str) or not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            account = entry.get('accountId')
            if not isinstance(account, str) or not account:
                continue
            account_name = entry.get('name') or entry.get('label') or account
            if not isinstance(account_name, str) or len(account_name) > 80:
                account_name = account
            result.append({'channel': channel, 'channel_name': channel,
                           'account_id': account, 'account_name': account_name,
                           'available': entry.get('configured') is True and entry.get('enabled') is not False
                           and entry.get('running') is True and entry.get('lastError') in (None, '')})
    return result[:200]


class OpenClawNotificationGateway:
    def __init__(self, secret_store, data_dir):
        self.gateway = AgentSkillGateway(secret_store, Path(data_dir))

    async def _request(self, method, params, required):
        async def operation(socket, hello):
            methods = hello.get('features', {}).get('methods', [])
            if not isinstance(methods, list) or required not in methods:
                raise OpenClawDeliveryError('gateway_capability_unavailable')
            try:
                return await self.gateway._request(socket, uuid.uuid4().hex, method, params)
            except AgentSkillGatewayError as error:
                if method == 'send':
                    raise OpenClawDeliveryError('gateway_outcome_unknown', outcome_unknown=True) from error
                raise
        try:
            return await asyncio.wait_for(self.gateway._session(operation), 50)
        except OpenClawDeliveryError:
            raise
        except AgentSkillGatewayError as error:
            raise OpenClawDeliveryError('gateway_rejected') from error
        except Exception as error:
            raise OpenClawDeliveryError('gateway_outcome_unknown' if method == 'send' else 'gateway_unavailable',
                                         outcome_unknown=method == 'send') from error

    def catalog(self):
        return channel_accounts(asyncio.run(self._request('channels.status', {}, 'channels.status')))

    def send(self, *, channel, account_id, destination, message, message_thread_id=None, idempotency_key):
        params = {'channel': channel, 'accountId': account_id, 'to': destination,
                  'message': message, 'idempotencyKey': idempotency_key}
        if message_thread_id is not None:
            params['threadId'] = str(message_thread_id)
        payload = asyncio.run(self._request('send', params, 'send'))
        message_id = payload.get('messageId') if isinstance(payload, dict) else None
        if not isinstance(message_id, (str, int)) or not str(message_id).strip() or payload.get('channel') != channel:
            raise OpenClawDeliveryError('unverified_receipt', outcome_unknown=True)
        return {'channel': 'openclaw', 'verification': 'provider_accepted', 'message_id': str(message_id)}
