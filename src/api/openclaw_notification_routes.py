"""Admin-only OpenClaw service configuration and channel catalog."""

from fastapi import Depends, FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from starlette.concurrency import run_in_threadpool

from .context import ApiContext
from .responses import ApiError, ok
from .system_auth import api_context, current_admin
from ..services.openclaw_notification_services import OpenClawNotificationServices, OpenClawServiceError


class CreateOpenClawService(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=80)
    openclaw_channel: str = Field(min_length=1, max_length=64)
    openclaw_account: str = Field(min_length=1, max_length=128)
    destination: str = Field(min_length=1, max_length=4096)
    telegram_message_thread_id: StrictInt | None = Field(default=None, ge=1)


class PatchOpenClawService(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str | None = Field(default=None, min_length=1, max_length=80)
    openclaw_channel: str | None = Field(default=None, min_length=1, max_length=64)
    openclaw_account: str | None = Field(default=None, min_length=1, max_length=128)
    destination: str | None = Field(default=None, min_length=1, max_length=4096)
    telegram_message_thread_id: StrictInt | None = Field(default=None, ge=1)
    enabled: StrictBool | None = None


def _service(context):
    return OpenClawNotificationServices(context.store, context.data_path)


def _invoke(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except OpenClawServiceError as error:
        raise ApiError(error.code, str(error), status_code=error.status) from None


async def catalog(response: Response, user=Depends(current_admin), context: ApiContext = Depends(api_context)):
    response.headers['Cache-Control'] = 'no-store'
    return ok({'channels': await run_in_threadpool(_invoke, _service(context).catalog)})


async def create(body: CreateOpenClawService, request: Request, response: Response,
                 user=Depends(current_admin), context: ApiContext = Depends(api_context)):
    service = _service(context)
    row = await run_in_threadpool(_invoke, service.create, user['workspace_id'], name=body.name,
        channel=body.openclaw_channel, account=body.openclaw_account, destination=body.destination,
        topic=body.telegram_message_thread_id)
    request.state.operation_changed_fields = sorted(body.model_fields_set)
    response.headers['Cache-Control'] = 'no-store'
    return ok(next(item for item in service.list(user['workspace_id']) if item['id'] == row['id']))


async def patch(service_id: str, body: PatchOpenClawService, request: Request, response: Response,
                user=Depends(current_admin), context: ApiContext = Depends(api_context)):
    if not body.model_fields_set:
        raise ApiError('invalid_notification_service', '请填写要修改的配置。', status_code=400)
    kwargs = {field: getattr(body, source) for field, source in [('name','name'),('channel','openclaw_channel'),
        ('account','openclaw_account'),('destination','destination'),('topic','telegram_message_thread_id'),
        ('enabled','enabled')] if source in body.model_fields_set}
    service = _service(context)
    await run_in_threadpool(_invoke, service.update, user['workspace_id'], service_id, **kwargs)
    request.state.operation_changed_fields = sorted(body.model_fields_set)
    response.headers['Cache-Control'] = 'no-store'
    return ok(next(item for item in service.list(user['workspace_id']) if item['id'] == service_id))


async def archive(service_id: str, request: Request, response: Response,
                  user=Depends(current_admin), context: ApiContext = Depends(api_context)):
    _invoke(_service(context).archive, user['workspace_id'], service_id)
    request.state.operation_changed_fields = ['archived']
    response.headers['Cache-Control'] = 'no-store'
    return ok({'service_id': service_id, 'archived': True})


async def test_and_enable(service_id: str, request: Request, response: Response,
                          user=Depends(current_admin), context: ApiContext = Depends(api_context)):
    result = await run_in_threadpool(_invoke, _service(context).test_and_enable, user['workspace_id'], service_id)
    request.state.operation_changed_fields = ['enabled', 'last_test_status']
    response.headers['Cache-Control'] = 'no-store'
    return ok(result)


def register(app: FastAPI):
    base = '/api/admin/openclaw-notification-services'
    app.add_api_route(base + '/channels', catalog, methods=['GET'])
    app.add_api_route(base, create, methods=['POST'])
    app.add_api_route(base + '/{service_id}', patch, methods=['PATCH'])
    app.add_api_route(base + '/{service_id}', archive, methods=['DELETE'])
    app.add_api_route(base + '/{service_id}/test-and-enable', test_and_enable, methods=['POST'])
