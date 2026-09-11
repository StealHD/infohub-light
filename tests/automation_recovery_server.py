"""Loopback-only browser acceptance harness; all runtime data lives in a temporary directory."""
import asyncio
import json
import socket
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
import uvicorn
from fastapi import FastAPI, Request
from test_information_automation_rules import context
from test_information_automation_execution import acquire
from test_information_semantic_claims import answer
from src.api.information_automation_routes import register_information_automation_routes
from src.api.system_auth import api_context, current_user
from src.api.responses import ApiError, error_response
from src.services.information_automations.connector_runner import InformationConnector
from src.services.information_automations.connector_auth import authenticate
from src.services.information_automations.model_catalog import Capabilities, sync_catalog


def serve(root):
    patch=pytest.MonkeyPatch()
    fixture=context.__wrapped__(root,patch)
    ctx=next(fixture)
    store,rules,_,user,_,_,config,_=ctx
    acquire(ctx,['article'],datetime.now(timezone.utc))
    rule=rules.save(user['id'],config.model_copy(update={'name':'恢复链路验收'}))
    machine=authenticate(store,store.test_machine_token)
    models=[{'id':'test/model','name':'Test','thinking_levels':[]}]
    sync_catalog(store,machine,Capabilities(protocol_version=2,execution_mode='previews_only',models=models))
    app=FastAPI()
    app.add_exception_handler(ApiError,lambda _,exc:error_response(exc))
    app.dependency_overrides[api_context]=lambda:SimpleNamespace(store=store,notification_targets=rules.targets)
    app.dependency_overrides[current_user]=lambda:user
    register_information_automation_routes(app)
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(128)
    url='http://127.0.0.1:'+str(sock.getsockname()[1])
    calls=[]
    connector=InformationConnector(service_url=url,gateway_url=url,service_token=store.test_machine_token,gateway_token='controlled',
        agent_id='ic-'+machine['binding_id'],journal=root/'result.json',discover_models=lambda:models)

    @app.get('/__fixture')
    async def info():
        return {'rule':rule,'source':config.source_ids[0],'calls':len(calls)}

    @app.post('/__cycle')
    async def cycle():
        connector.catalog_at=0
        return await asyncio.to_thread(connector.run_once)

    @app.post('/__add-model')
    async def add_model():
        models.append({'id':'test/new','name':'New model','thinking_levels':[]})
        return {'added':True}

    @app.post('/tools/invoke')
    async def gateway(request: Request):
        payload=await request.json();calls.append(payload['idempotencyKey'])
        args=payload['args']
        result=answer({'input':args['input']['units'],'model':{'id':args['model']}})
        return {'ok':True,'result':{'details':{'provider':'test','model':'model','json':result['output']}}}

    print(json.dumps({'url':url}),flush=True)
    try:
        uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False)).run(sockets=[sock])
    finally:
        connector.close();fixture.close();patch.undo();sock.close()


if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='automation-browser-') as directory:
        serve(Path(directory).resolve())
