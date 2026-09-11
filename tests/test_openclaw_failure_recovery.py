"""Production-shaped failures must retain their safe classification."""
import pytest
from src.services.openclaw_relay.errors import safe_chat_failure, safe_error


@pytest.mark.parametrize('payload', [
    {'message': 'Google Generative AI API error (429): You exceeded your current quota [code=RESOURCE_EXHAUSTED]'},
    {'errorKind': 'rate_limit', 'message': 'The agent run failed before producing a reply.'},
])
def test_google_quota_is_not_generic(payload):
    assert safe_error(payload)['code'] == 'MODEL_QUOTA_LIMITED'


def test_structured_error_sequence_survives_relay():
    result = safe_chat_failure({'type': 'event', 'event': 'chat', 'payload': {
        'state': 'error', 'sessionKey': 'agent:ih-test:child', 'runId': 'run-1', 'seq': 12,
        'errorKind': 'rate_limit', 'errorMessage': 'untrusted SECRET',
    }})
    assert result['payload']['errorCode'] == 'MODEL_QUOTA_LIMITED'
    assert result['payload']['seq'] == 12
    assert 'SECRET' not in str(result)


@pytest.mark.parametrize(('message', 'code'), [
    ('HTTP 503', 'MODEL_UPSTREAM_UNAVAILABLE'), ('HTTP 401', 'MODEL_AUTH_FAILED'),
    ('request timed out', 'MODEL_CALL_TIMEOUT'), ('unspecified', 'RELAY_REQUEST_FAILED'),
])
def test_failure_categories(message, code):
    assert safe_error({'message': message})['code'] == code


def test_gateway_fixture_encodes_default_override_removal_and_parent_execution():
    from openclaw_recovery_gateway import RecoveryGateway, DEFAULT, OTHER
    gateway = RecoveryGateway('personal')
    key = gateway.respond('sessions.create', {'parentSessionKey': gateway.parent, 'model': DEFAULT})['key']
    assert gateway.describe(key)['modelProvider'] == 'deepseek'
    assert gateway.execution_model(key) == OTHER
    root = gateway.respond('sessions.create', {'model': DEFAULT})['key']
    assert gateway.execution_model(root) == DEFAULT
    assert 'parentSessionKey' not in gateway.describe(root)


def test_history_retains_reply_but_discards_raw_diagnostics():
    from src.services.openclaw_relay.errors import safe_history_failures
    result = safe_history_failures({'messages': [{'role': 'assistant', 'stopReason': 'error',
        'text': 'partial reply', 'errorMessage': 'RESOURCE_EXHAUSTED SECRET', 'errorDetail': {'key': 'SECRET'}}]})
    assert result['messages'][0]['errorCode'] == 'MODEL_QUOTA_LIMITED'
    assert result['messages'][0]['text'] == 'partial reply'
    assert 'SECRET' not in str(result)
