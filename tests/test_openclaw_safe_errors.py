import pytest
from src.services.openclaw_relay.errors import safe_error, safe_chat_failure


@pytest.mark.parametrize(('message', 'code'), [
    ('Thinking level "medium" is not supported for google/pro', 'MODEL_PARAMETER_UNSUPPORTED'),
    ('No callable tools remain after resolving explicit tool allowlist', 'PERSONAL_TOOLS_UNAVAILABLE'),
    ('MCP initialize timed out', 'PERSONAL_TOOLS_UNAVAILABLE'),
    ('No API key found for provider', 'MODEL_AUTH_FAILED'),
    ('rate_limit exceeded', 'MODEL_QUOTA_LIMITED'),
    ('request timed out', 'MODEL_CALL_TIMEOUT'),
    ('unknown /private/file token=SECRET', 'RELAY_REQUEST_FAILED'),
])
def test_classification_never_returns_upstream_text(message, code):
    result = safe_error({'message': message, 'details': {'token': 'SECRET'}})
    assert result['code'] == code
    assert 'SECRET' not in str(result) and '/private' not in str(result)
    assert set(result) == {'code', 'message'}


def test_chat_failure_removes_raw_message_and_details():
    result = safe_chat_failure({'type': 'event', 'event': 'chat', 'payload': {
        'state': 'error', 'sessionKey': 'agent:ih-test:main', 'runId': 'run-1',
        'errorMessage': 'No callable tools remain SECRET', 'message': 'SECRET', 'details': '/private',
    }})
    assert result['payload']['errorCode'] == 'PERSONAL_TOOLS_UNAVAILABLE'
    assert result['payload']['runId'] == 'run-1'
    assert 'SECRET' not in str(result) and '/private' not in str(result)
