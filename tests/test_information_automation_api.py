"""HTTP identity and request-shape boundaries without network transports."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_information_automation_rules import context  # noqa: F401
from src.api.information_automation_routes import register_information_automation_routes
from src.api.system_auth import api_context, current_user
from src.api.responses import ApiError, error_response


@pytest.fixture
def client(context):
    store, rules, _, alice, *_ = context
    app = FastAPI()
    app.add_exception_handler(ApiError, lambda _, exc: error_response(exc))
    app.dependency_overrides[api_context] = lambda: SimpleNamespace(store=store, notification_targets=rules.targets)
    app.dependency_overrides[current_user] = lambda: alice
    register_information_automation_routes(app)
    with TestClient(app) as value:
        yield value, app


def test_http_draft_confirmation_and_identity_injection(context, client):
    http, app = client
    config = context[6].model_dump()
    base = '/api/me/information-automations'
    assert http.post(base, json={**config, 'user_id': context[4]['id']}).status_code == 422
    created = http.post(base, json=config)
    assert created.status_code == 200 and created.headers['Cache-Control'] == 'no-store'
    draft = created.json()['data']
    assert draft['state'] == 'draft'
    route = base + '/' + draft['id']
    assert http.post(route + '/transition', json={'version': True, 'action': 'enable'}).status_code == 422
    assert http.post(route + '/transition', json={'version': 1, 'action': 'enable'}).json()['data']['state'] == 'active'
    app.dependency_overrides[current_user] = lambda: context[4]
    assert http.get(route).status_code == 404
    assert http.get(route + '/runs').status_code == 404
    assert http.get(base).json()['data']['items'] == []
