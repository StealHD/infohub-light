"""Public model metadata and machine-only capability synchronization."""
from pydantic import BaseModel, Field
from typing import Annotated
from fastapi import Depends, Header, Response, Request
from .context import ApiContext
from .system_auth import api_context, current_user
from .information_automation_routes import service, invoke
from .information_connector_routes import bearer
from ..services.information_automations.connector_auth import authenticate
from ..services.information_automations.model_catalog import Capabilities, catalog, sync_catalog


async def list_models(response: Response,user=Depends(current_user),context: ApiContext=Depends(api_context)):
    def operation():
        rules=service(response,context)
        binding=rules.binding(rules.actor(user['id']))
        return catalog(context.store,binding['binding_id'])
    return invoke(operation)


async def refresh_models(response: Response,user=Depends(current_user),context: ApiContext=Depends(api_context)):
    def operation():
        rules=service(response,context)
        binding=rules.binding(rules.actor(user['id'],write=True))
        from ..services.information_automations.model_refresh import request_refresh
        requested = request_refresh(context.store,binding['binding_id'])
        return {**catalog(context.store,binding['binding_id']), **requested}
    return invoke(operation)


async def capabilities(body: Capabilities,response: Response,request: Request,authorization: Annotated[str|None,Header()]=None,context: ApiContext=Depends(api_context)):
    response.headers['Cache-Control']='no-store'
    def operation():
        from ..storage.information_unified_schema import ready
        from ..services.information_automations.rules import RuleError
        if not ready(context.store.connect()):
            raise RuleError('information_migration_required','请先完成 global 40 迁移。',503)
        from .information_operation_routes import machine_audit
        token=bearer(authorization)
        machine_audit(request,context.store,token)
        machine=authenticate(context.store,token)
        result=sync_catalog(context.store,machine,body)
        if not result['changed']:
            request.state.operation_logged=True
        return result
    return invoke(operation)


async def connector_control(response: Response, request: Request, authorization: Annotated[str|None,Header()]=None, context: ApiContext=Depends(api_context)):
    response.headers['Cache-Control']='no-store'
    request.state.operation_logged=True
    from ..services.information_automations.model_refresh import control
    return invoke(lambda: control(context.store,authenticate(context.store,bearer(authorization))))


class RefreshFailure(BaseModel):
    request_id: str = Field(min_length=1,max_length=256)


async def refresh_failure(body: RefreshFailure,response: Response,request: Request,authorization: Annotated[str|None,Header()]=None,context: ApiContext=Depends(api_context)):
    response.headers['Cache-Control']='no-store'
    from ..services.information_automations.model_refresh import fail_refresh
    def operation():
        from .information_operation_routes import machine_audit
        token=bearer(authorization)
        machine_audit(request,context.store,token)
        return fail_refresh(context.store,authenticate(context.store,token),body.request_id)
    return invoke(operation)


def register(app):
    base='/api/me/information-automations/models'
    app.add_api_route(base,list_models,methods=['GET'])
    app.add_api_route(base+'/refresh',refresh_models,methods=['POST'])
    app.add_api_route('/api/connector/information-automations/capabilities',capabilities,methods=['POST'])
    app.add_api_route('/api/connector/information-automations/control',connector_control,methods=['POST'])
    app.add_api_route('/api/connector/information-automations/refresh-failure',refresh_failure,methods=['POST'])
