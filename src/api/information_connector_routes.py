"""Machine-only endpoints; browser cookies cannot authorize task claims."""
from typing import Annotated, Any
from fastapi import Depends, FastAPI, Header, Response, Request
from pydantic import BaseModel, ConfigDict, Field
from .context import ApiContext
from .system_auth import api_context
from .information_automation_routes import invoke
from ..services.information_automations.rules import RuleError
from ..services.information_automations.semantic_claims import claim_work, submit_result


class ClaimRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    isolated_completion: bool
    protocol_version: int = 1


class ResultRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    claim_token: str = Field(min_length=43, max_length=43)
    result: dict[str, Any]


def bearer(value):
    if not value or not value.startswith('Bearer ') or len(value) > 256:
        raise RuleError('connector_unauthorized', '需要独立机器凭据。', 401)
    return value[7:]


async def claim(body: ClaimRequest, response: Response, request: Request, authorization: Annotated[str | None, Header()] = None,
                context: ApiContext = Depends(api_context)):
    response.headers['Cache-Control'] = 'no-store'
    def operation():
        token = bearer(authorization)
        if body.isolated_completion is not True:
            raise RuleError('isolated_completion_required', '必须使用无工具独立推理。', 400)
        from .information_operation_routes import machine_audit
        machine_audit(request, context.store, token)
        result = claim_work(context.store, context.notification_targets, token, protocol_version=body.protocol_version)
        if not result.get('task'):
            request.state.operation_logged = True
        return result
    return invoke(operation)


async def complete(claim_id: str, body: ResultRequest, response: Response, request: Request,
                   authorization: Annotated[str | None, Header()] = None, context: ApiContext = Depends(api_context)):
    response.headers['Cache-Control'] = 'no-store'
    def operation():
        from .information_operation_routes import machine_audit
        token = bearer(authorization)
        machine_audit(request, context.store, token)
        return submit_result(context.store, context.notification_targets, token, claim_id, body.claim_token, body.result)
    return invoke(operation)


async def configuration(response: Response, authorization: Annotated[str | None, Header()] = None, context: ApiContext = Depends(api_context)):
    from ..services.information_automations.connector_auth import authenticate
    response.headers['Cache-Control'] = 'no-store'
    def operation():
        machine = authenticate(context.store, bearer(authorization))
        return {'binding_id': machine['binding_id'], 'agent_id': machine['agent_id'],
                'completion_agent_id': 'ic-' + machine['binding_id'], 'isolated_completion_required': True, 'protocol_version': 2}
    return invoke(operation)


def register_information_connector_routes(app: FastAPI):
    from .information_connector_body import ConnectorBodyLimit
    app.add_middleware(ConnectorBodyLimit)
    app.add_api_route('/api/connector/information-automations/configuration', configuration, methods=['GET'])
    app.add_api_route('/api/connector/information-automations/claim', claim, methods=['POST'])
    app.add_api_route('/api/connector/information-automations/claims/{claim_id}/result', complete, methods=['POST'])
