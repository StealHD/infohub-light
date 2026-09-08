"""Gateway-host pull connector. Empty queues never call a model."""
import json
import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from .batches import SYSTEM, output_schema
from .completion_errors import completion_error
import time


class InformationConnector:
    def __init__(self, *, service_url, service_token, gateway_url, gateway_token, agent_id, journal, client=None, discover_models=None):
        for value in (service_url, gateway_url):
            url = urlsplit(value)
            if not url.hostname or url.username or url.password or url.query or url.fragment or not (
                url.scheme == 'https' or url.scheme == 'http' and url.hostname in {'127.0.0.1', 'localhost', '::1'}):
                raise ValueError('HTTPS or loopback endpoint required')
        self.service_url, self.gateway_url = service_url.rstrip('/'), gateway_url.rstrip('/')
        self.service_token, self.gateway_token = service_token, gateway_token
        self.agent_id, self.journal = agent_id, Path(journal)
        if self.journal.is_symlink() or self.journal.parent.resolve() != self.journal.parent:
            raise ValueError('Regular private journal path required')
        self.discover_models, self.catalog_at = discover_models, 0
        self.client = client or httpx.Client(timeout=75, follow_redirects=False)

    def close(self):
        self.client.close()

    def service(self, path, data):
        response = self.client.post(self.service_url + '/api/connector/information-automations/' + path,
            headers={'Authorization': 'Bearer ' + self.service_token}, json=data)
        response.raise_for_status()
        return response.json()['data']

    def persist(self, value):
        self.journal.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        temporary = self.journal.with_name('.' + self.journal.name + '.' + uuid.uuid4().hex)
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(fd, 'w') as handle:
                json.dump(value, handle, ensure_ascii=False); handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, self.journal)
        finally:
            temporary.unlink(missing_ok=True)

    def flush(self):
        if not self.journal.exists():
            return None
        if self.journal.stat().st_mode & 0o077:
            raise ValueError('Result journal must remain private')
        saved = json.loads(self.journal.read_text())
        try:
            result = self.service('claims/' + saved['claim_id'] + '/result', saved['body'])
        except httpx.HTTPStatusError as error:
            if error.response.status_code not in {403, 404, 409, 422}:
                raise
            self.journal.unlink()
            return {'status': 'result_rejected', 'retry_after': 15}
        self.journal.unlink()
        return {'status': 'result_recorded', 'accepted': result.get('accepted', False), 'retry_after': 0}

    def run_once(self):
        pending = self.flush()
        if pending is not None:
            return pending
        if self.discover_models and time.monotonic() - self.catalog_at >= 30:
            models = self.discover_models()
            self.service('capabilities', {'protocol_version': 2, 'models': models})
            self.catalog_at = time.monotonic()
        claim = self.service('claim', {'isolated_completion': True, 'protocol_version': 2})
        task = claim.get('task')
        if not task:
            return {'status': claim.get('reason', 'empty'), 'retry_after': claim.get('retry_after', 15)}
        try:
            if self.agent_id != 'ic-' + task['agent_id'].removeprefix('ih-'):
                raise ValueError('Connector Agent binding mismatch')
            response = self.client.post(self.gateway_url + '/tools/invoke',
                headers={'Authorization': 'Bearer ' + self.gateway_token}, json={
                    'tool': 'llm-task', 'action': 'json', 'agentId': self.agent_id, 'sessionKey': 'agent:' + self.agent_id + ':information-analysis',
                    'idempotencyKey': task['claim_id'], 'args': {'prompt': SYSTEM + '\nOUTPUT_SCHEMA:\n' + json.dumps(output_schema(task['requirement'], task['stage']), separators=(',', ':')), 'model': task['model']['id'],
                    **({'thinking': task['model']['thinking']} if task['model'].get('thinking') else {}),
                    'input': {'requirement': task['requirement'], 'stage': task['stage'], 'units': task['input']},
                    'schema': output_schema(task['requirement'], task['stage']), 'maxTokens': 4096, 'timeoutMs': 60000}})
            response.raise_for_status()
            raw = response.json()
            details = raw['result']['details']
            actual = details.get('model', '')
            actual = actual if actual.startswith(details.get('provider', '') + '/') else details.get('provider', '') + '/' + actual
            result = {'output': details['json'], 'model': actual}
            if not raw.get('ok') or not isinstance(result, dict):
                raise ValueError('Invalid isolated completion')
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            result = {'error': completion_error(error)}
        self.persist({'claim_id': task['claim_id'], 'body': {'claim_token': task['claim_token'], 'result': result}})
        return self.flush()
