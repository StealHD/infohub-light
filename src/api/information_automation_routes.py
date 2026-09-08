"""Personal information reminders. Only authenticated HTTP confirmation can enable."""
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Query, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from .context import ApiContext
from .responses import ApiError, ok
from .system_auth import api_context, current_user
from ..services.information_automations.rules import InformationRules, RuleConfig, RuleError


class UpdateRule(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: StrictInt = Field(ge=1)
    config: RuleConfig


class TransitionRule(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: StrictInt = Field(ge=1)
    action: Literal['enable', 'pause', 'archive']


class TestRule(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: StrictInt = Field(ge=1)
    article_ids: list[str] = Field(min_length=1, max_length=1000)


def service(response: Response, context: ApiContext):
    response.headers['Cache-Control'] = 'no-store'
    return InformationRules(context.store, context.notification_targets)


def invoke(call, *args, **kwargs):
    try:
        return ok(call(*args, **kwargs))
    except RuleError as error:
        raise ApiError(error.code, str(error), status_code=error.status,
                       action='刷新当前页面并检查个人接入、订阅和通知服务。') from None


async def list_rules(response: Response, limit: Annotated[int, Query(ge=1, le=100)] = 50,
                     offset: Annotated[int, Query(ge=0)] = 0, user=Depends(current_user),
                     context: ApiContext = Depends(api_context)):
    return invoke(service(response, context).list, user['id'], limit=limit, offset=offset)


async def create_rule(body: RuleConfig, response: Response, user=Depends(current_user),
                      context: ApiContext = Depends(api_context)):
    return invoke(service(response, context).save, user['id'], body)


async def get_rule(rule_id: str, response: Response, user=Depends(current_user),
                   context: ApiContext = Depends(api_context)):
    return invoke(service(response, context).get, user['id'], rule_id)


async def update_rule(rule_id: str, body: UpdateRule, response: Response, user=Depends(current_user),
                      context: ApiContext = Depends(api_context)):
    return invoke(service(response, context).save, user['id'], body.config,
                  rule_id=rule_id, expected_version=body.version)


async def transition_rule(rule_id: str, body: TransitionRule, response: Response, user=Depends(current_user),
                          context: ApiContext = Depends(api_context)):
    return invoke(service(response, context).transition, user['id'], rule_id, body.version, body.action)


async def test_rule(rule_id: str, body: TestRule, response: Response, user=Depends(current_user),
                    context: ApiContext = Depends(api_context)):
    return invoke(service(response, context).test, user['id'], rule_id, body.version, body.article_ids)


async def list_runs(rule_id: str, response: Response, limit: Annotated[int, Query(ge=1, le=100)] = 50,
                    offset: Annotated[int, Query(ge=0)] = 0, user=Depends(current_user),
                    context: ApiContext = Depends(api_context)):
    return invoke(service(response, context).runs, user['id'], rule_id, limit=limit, offset=offset)


async def get_test(rule_id: str, preview_id: str, response: Response, user=Depends(current_user), context: ApiContext = Depends(api_context)):
    from ..services.information_automations.semantic_previews import get_preview
    return invoke(get_preview, service(response, context), user['id'], rule_id, preview_id)


def register_information_automation_routes(app: FastAPI):
    from .information_connector_routes import register_information_connector_routes
    register_information_connector_routes(app)
    from .information_model_routes import register
    register(app)
    base = '/api/me/information-automations'
    for path, endpoint, method in [('', list_rules, 'GET'), ('', create_rule, 'POST'),
                                   ('/{rule_id}', get_rule, 'GET'), ('/{rule_id}', update_rule, 'PUT'),
                                   ('/{rule_id}/transition', transition_rule, 'POST'),
                                   ('/{rule_id}/test', test_rule, 'POST'), ('/{rule_id}/test/{preview_id}', get_test, 'GET'), ('/{rule_id}/runs', list_runs, 'GET')]:
        app.add_api_route(base + path, endpoint, methods=[method])
