"""An empty queue or an unknown submission never repeats model inference."""
import httpx
from src.services.information_automations.connector_runner import InformationConnector
from src.services.information_automations import completion_guard


def test_empty_queue_never_calls_gateway(tmp_path):
    calls = []
    def request(req):
        calls.append(req.url.path)
        if req.url.path.endswith('/control'):
            return httpx.Response(200, json={'data': {'refresh_request_id': None, 'catalog_refresh_required': False}})
        return httpx.Response(200, json={'data': {'task': None, 'reason': 'empty', 'retry_after': 15}})
    connector = InformationConnector(service_url='http://localhost:8080', gateway_url='http://localhost:18789',
        service_token='controlled', gateway_token='controlled', agent_id='ic-test', journal=tmp_path / 'result.json',
        client=httpx.Client(transport=httpx.MockTransport(request)))
    try:
        assert connector.run_once()['status'] == 'empty'
        assert calls == ['/api/connector/information-automations/control', '/api/connector/information-automations/claim']
    finally: connector.close()


def test_catalog_only_neither_claims_nor_flushes_old_results(tmp_path):
    calls = []
    def request(req):
        calls.append(req.url.path)
        if req.url.path.endswith('/control'):
            return httpx.Response(200, json={'data': {'refresh_request_id': None, 'catalog_refresh_required': True}})
        return httpx.Response(200, json={'data': {'accepted': True}})
    connector = InformationConnector(service_url='http://localhost:8080', gateway_url='http://localhost:18789',
        service_token='controlled', gateway_token='controlled', agent_id='ic-test', journal=tmp_path / 'result.json',
        client=httpx.Client(transport=httpx.MockTransport(request)), discover_models=lambda: [])
    try:
        connector.persist({'claim_id': 'old', 'body': {}})
        assert connector.run_once(catalog_only=True)['status'] == 'catalog_synced'
        assert connector.journal.exists()
        assert calls == ['/api/connector/information-automations/control', '/api/connector/information-automations/capabilities']
    finally:
        connector.close()


def test_submission_timeout_persists_and_retries_same_result_without_model(tmp_path):
    calls, attempts = [], []
    def request(req):
        calls.append(req.url.path)
        if req.url.path.endswith('/control'):
            return httpx.Response(200, json={'data': {'refresh_request_id': None, 'catalog_refresh_required': False}})
        if req.url.path.endswith('/claim'):
            return httpx.Response(200, json={'data': {'task': {'claim_id': 'claim', 'claim_token': 'token', 'agent_id': 'ih-test', 'requirement': 'test', 'stage':'final','input':[],'model':{'id':'test/model'}}}})
        if req.url.path == '/tools/invoke':
            import json
            payload = json.loads(req.content)
            assert payload['tool'] == 'llm-task' and payload['agentId'] == 'ic-test'
            assert 'tools' not in payload['args']
            assert payload['sessionKey'] == 'agent:ic-test:information-analysis'
            assert 'OUTPUT_SCHEMA:' in payload['args']['prompt']
            assert '"status"' in payload['args']['prompt']
            return httpx.Response(200, json={'ok': True, 'result': {'details': {'json': {}, 'provider':'test','model':'model'}}})
        attempts.append(req.content)
        if len(attempts) == 1:
            raise httpx.ReadTimeout('controlled timeout')
        return httpx.Response(200, json={'data': {'accepted': True}})
    connector = InformationConnector(service_url='http://localhost:8080', gateway_url='http://localhost:18789',
        service_token='controlled', gateway_token='controlled', agent_id='ic-test', journal=tmp_path / 'result.json',
        client=httpx.Client(transport=httpx.MockTransport(request)))
    try:
        import pytest
        with pytest.raises(httpx.ReadTimeout): connector.run_once()
        assert connector.journal.stat().st_mode & 0o077 == 0
        assert connector.run_once()['status'] == 'result_recorded'
        assert attempts[0] == attempts[1] and calls.count('/tools/invoke') == 1
        assert not connector.journal.exists()
    finally: connector.close()

def test_completion_errors_do_not_misclassify_schema_or_timeout_as_missing_model():
    from src.services.information_automations.completion_errors import completion_error, confirmed_gateway_tool_failure
    request = httpx.Request('POST', 'http://localhost/tools/invoke')
    response = httpx.Response(500, request=request, text='LLM JSON did not match schema: private output')
    assert completion_error(httpx.HTTPStatusError('private', request=request, response=response)) == 'invalid_model_output'
    assert not confirmed_gateway_tool_failure(httpx.HTTPStatusError('private', request=request, response=response))
    assert completion_error(httpx.ReadTimeout('private')) == 'analysis_timeout'
    assert completion_error(KeyError('private')) == 'invalid_model_output'


def test_unknown_inference_timeout_does_not_claim_another_task(tmp_path):
    calls = []
    def request(req):
        calls.append(req.url.path)
        if req.url.path.endswith('/control'):
            return httpx.Response(200, json={'data': {'refresh_request_id': None, 'catalog_refresh_required': False}})
        if req.url.path.endswith('/claim'):
            return httpx.Response(200, json={'data': {'task': {'claim_id': 'claim', 'claim_token': 'token',
                'agent_id': 'ih-test', 'requirement': 'test', 'stage': 'final', 'input': [], 'model': {'id': 'test/model'}}}})
        if req.url.path == '/tools/invoke':
            raise httpx.ReadTimeout('unknown result')
        return httpx.Response(200, json={'data': {'accepted': True}})
    connector = InformationConnector(service_url='http://localhost:8080', gateway_url='http://localhost:18789',
        service_token='controlled', gateway_token='controlled', agent_id='ic-test', journal=tmp_path / 'result.json',
        client=httpx.Client(transport=httpx.MockTransport(request)))
    try:
        assert connector.run_once()['status'] == 'result_recorded'
        assert connector.run_once()['status'] == 'inference_unconfirmed'
        assert calls.count('/tools/invoke') == 1
        assert calls.count('/api/connector/information-automations/claim') == 1
    finally:
        connector.close()


def test_gateway_tool_error_finishes_inference_and_records_definite_failure(tmp_path):
    calls, claims = [], 0
    def request(req):
        nonlocal claims
        calls.append(req.url.path)
        if req.url.path.endswith('/control'):
            return httpx.Response(200, json={'data': {'refresh_request_id': None, 'catalog_refresh_required': False}})
        if req.url.path.endswith('/claim'):
            claims += 1
            if claims > 1:
                return httpx.Response(200, json={'data': {'task': None, 'reason': 'empty', 'retry_after': 15}})
            return httpx.Response(200, json={'data': {'task': {'claim_id': 'claim', 'claim_token': 'token',
                'agent_id': 'ih-test', 'requirement': 'test', 'stage': 'final', 'input': [], 'model': {'id': 'test/model'}}}})
        if req.url.path == '/tools/invoke':
            return httpx.Response(500, request=req, json={'ok': False, 'error': {'code': 'TOOL_EXECUTION_FAILED'}})
        assert req.url.path.endswith('/result')
        import json
        assert json.loads(req.content)['result'] == {'error': 'analysis_call_failed'}
        return httpx.Response(200, json={'data': {'accepted': True}})
    connector = InformationConnector(service_url='http://localhost:8080', gateway_url='http://localhost:18789',
        service_token='controlled', gateway_token='controlled', agent_id='ic-test', journal=tmp_path / 'result.json',
        client=httpx.Client(transport=httpx.MockTransport(request)))
    try:
        assert connector.run_once()['status'] == 'result_recorded'
        assert completion_guard.path(connector.journal).exists()
        assert not connector.journal.exists()
        assert not completion_guard.uncertain(connector.journal)
        assert connector.run_once()['status'] == 'empty'
        assert calls == ['/api/connector/information-automations/control',
                         '/api/connector/information-automations/claim', '/tools/invoke',
                         '/api/connector/information-automations/claims/claim/result',
                         '/api/connector/information-automations/control',
                         '/api/connector/information-automations/claim']
    finally:
        connector.close()
