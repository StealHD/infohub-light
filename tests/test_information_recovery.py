"""Real Service and SQLite with a controlled Gateway; no external model or push."""
import json
from datetime import datetime, timedelta, timezone
import httpx
import pytest
from test_information_automation_rules import context  # noqa: F401
from test_information_automation_api import client  # noqa: F401
from test_information_automation_execution import acquire
from test_information_semantic_claims import answer
from src.services.information_automations.connector_runner import InformationConnector
from src.services.information_automations.connector_auth import authenticate
from src.services.information_automations.model_catalog import Capabilities, sync_catalog, block_model, catalog
from src.services.information_automations.model_refresh import request_refresh, control
from src.services.information_automations.semantic_claims import claim_work, expire_claims
from src.services.information_automations.semantic_previews import get_preview
from src.services.information_automations.rules import RuleError


def prepare(context, mode='previews_only'):
    store,rules,_,user,_,_,config,_ = context
    machine=authenticate(store,store.test_machine_token)
    sync_catalog(store,machine,Capabilities(protocol_version=2,execution_mode=mode,models=[{'id':'test/model','name':'Test'}]))
    acquire(context,['article'],datetime.now(timezone.utc))
    rule=rules.save(user['id'],config)
    return store,rules,user,rule,machine


def test_service_connector_gateway_roundtrip_and_restart_idempotency(context,client,tmp_path):
    store,rules,user,rule,machine=prepare(context)
    http,_=client
    route='/api/me/information-automations/'+rule['id']+'/test'
    payload={'version':1,'article_ids':['article'],'request_id':'gesture-one'}
    preview=http.post(route,json=payload).json()['data']
    assert http.post(route,json=payload).json()['data']['preview_id']==preview['preview_id']
    assert http.post(route,json={**payload,'request_id':'other-tab'}).json()['data']['preview_id']==preview['preview_id']
    calls=[]
    def dispatch(req):
        if req.url.path=='/tools/invoke':
            calls.append(json.loads(req.content))
            args=calls[-1]['args']
            result=answer({'input':args['input']['units'],'model':{'id':args['model']}})
            return httpx.Response(200,json={'ok':True,'result':{'details':{'json':result['output'],'provider':'test','model':'model'}}})
        response=http.post(req.url.path,content=req.content,headers={'Authorization':req.headers['Authorization'],'Content-Type':'application/json'})
        return httpx.Response(response.status_code,json=response.json())
    def connector():
        return InformationConnector(service_url='http://localhost',gateway_url='http://localhost:18789',
            service_token=store.test_machine_token,gateway_token='controlled',agent_id='ic-'+machine['binding_id'],journal=tmp_path/'result.json',
            discover_models=lambda:[{'id':'test/model','name':'Test'}],client=httpx.Client(transport=httpx.MockTransport(dispatch)))
    worker=connector()
    assert worker.run_once()['status']=='result_recorded'
    worker.close()
    from src.storage.service_store import ServiceStore
    from src.api.system_auth import api_context
    from types import SimpleNamespace
    restarted=ServiceStore(store.data_dir)
    client[1].dependency_overrides[api_context]=lambda:SimpleNamespace(store=restarted,notification_targets=rules.targets)
    worker=connector()
    assert worker.run_once()['status']=='empty'
    worker.close()
    completed=http.get(route+'/latest').json()['data']
    assert completed['status']=='completed' and completed['progress']=={'completed':1,'total':1}
    assert http.post(route,json=payload).json()['data']['preview_id']==preview['preview_id']
    assert len(calls)==1 and rules.get(user['id'],rule['id'])['state']=='draft'
    assert store.connect().execute('SELECT count(*) FROM information_runs').fetchone()[0]==0
    assert not completed['sends_notification'] and not completed['advances_cursor']
    restarted.close()


@pytest.mark.parametrize('mode,reason',[('catalog_only','execution_disabled'),(None,'connector_upgrade_required')])
def test_fresh_directory_cannot_queue_without_execution(context,mode,reason):
    store,rules,user,rule,machine=prepare(context,mode)
    assert catalog(store,machine['binding_id'])['status']=='ready'
    with pytest.raises(RuleError) as failure:
        rules.test(user['id'],rule['id'],1,['article'],'one')
    assert failure.value.code==reason
    assert store.connect().execute('SELECT count(*) FROM information_previews').fetchone()[0]==0


def test_old_queue_requires_confirmation_and_unknown_claim_never_reexecutes(context):
    store,rules,user,rule,machine=prepare(context)
    old=rules.test(user['id'],rule['id'],1,['article'],'old')
    conn=store.connect()
    conn.execute('DELETE FROM information_preview_confirmations');conn.execute('DELETE FROM information_preview_requests');conn.commit()
    assert get_preview(rules,user['id'],rule['id'],old['preview_id'])['reason']=='preview_confirmation_required'
    assert claim_work(store,rules.targets,store.test_machine_token)['task'] is None
    new=rules.test(user['id'],rule['id'],1,['article'],'confirmed')
    assert new['preview_id']!=old['preview_id']
    assert get_preview(rules,user['id'],rule['id'],old['preview_id'])['reason']=='preview_superseded'
    task=claim_work(store,rules.targets,store.test_machine_token)['task']
    assert task['preview_id']==new['preview_id']
    expire_claims(conn,datetime.now(timezone.utc)+timedelta(seconds=181));conn.commit()
    uncertain=get_preview(rules,user['id'],rule['id'],new['preview_id'])
    assert uncertain['reason']=='completion_unknown' and uncertain['requires_review']
    assert rules.test(user['id'],rule['id'],1,['article'],'another')['preview_id']==new['preview_id']
    assert claim_work(store,rules.targets,store.test_machine_token)['task'] is None


def test_refresh_receipt_fences_old_sync_and_blocks_release_only_after_ack(context):
    store,_,_,_,machine=prepare(context)
    conn=store.connect();block_model(conn,machine['binding_id'],'test/model');conn.commit()
    first=request_refresh(store,machine['binding_id'])['refresh']['id']
    assert request_refresh(store,machine['binding_id'])['refresh']['id']==first
    assert catalog(store,machine['binding_id'])['models']==[]
    conn.execute("UPDATE information_refresh_requests SET requested_at=?",((datetime.now(timezone.utc)-timedelta(seconds=121)).isoformat(),));conn.commit()
    second=request_refresh(store,machine['binding_id'])['refresh']['id']
    assert second!=first
    sync_catalog(store,machine,Capabilities(protocol_version=2,execution_mode='previews_only',refresh_request_id=first,models=[{'id':'test/model','name':'Test'}]))
    assert control(store,machine)['refresh_request_id']==second
    assert catalog(store,machine['binding_id'])['models']==[]
    sync_catalog(store,machine,Capabilities(protocol_version=2,execution_mode='previews_only',refresh_request_id=second,models=[{'id':'test/model','name':'Test'},{'id':'test/new','name':'New'}]))
    value=catalog(store,machine['binding_id'])
    assert value['refresh']['status']=='completed' and value['refresh']['completed_at']
    assert [row['id'] for row in value['models']]==['test/model','test/new']


@pytest.mark.parametrize('mode', ['catalog_only','previews_only','full'])
def test_runner_and_supervisor_share_modes_without_replaying_old_previews(context,client,tmp_path,monkeypatch,mode):
    from types import SimpleNamespace
    from src.services.agent_connections import analysis_supervisor
    from src.services.agent_connections.analysis_host import write_registry
    from src.services.agent_connections.analysis_manifest import objects, validate_token
    from src.services.secret_store import SecretStore
    from src.services.information_automations.execution import evaluate_pending
    store,rules,user,rule,machine=prepare(context)
    # One legacy preview is deliberately absent from the confirmation sidecar.
    old=rules.test(user['id'],rule['id'],1,['article'])
    store.connect().execute('DELETE FROM information_preview_confirmations');store.connect().commit()
    from src.services.information_automations.config import Trigger
    formal=rules.save(user['id'],context[6].model_copy(update={'name':'Formal','trigger':Trigger(kind='each')}))
    rules.transition(user['id'],formal['id'],1,'enable')
    acquire(context,['new'],datetime.now(timezone.utc))
    evaluate_pending(store,rules.targets,now=datetime.now(timezone.utc))
    calls=[]
    http,_=client
    def dispatch(req):
        if req.url.path=='/tools/invoke':
            payload=json.loads(req.content);calls.append(payload)
            args=payload['args']; result=answer({'input':args['input']['units'],'model':{'id':args['model']}})
            return httpx.Response(200,json={'ok':True,'result':{'details':{'json':result['output'],'provider':'test','model':'model'}}})
        res=http.post(req.url.path,content=req.content,headers={'Authorization':req.headers['Authorization'],'Content-Type':'application/json'})
        return httpx.Response(res.status_code,json=res.json())
    token=store.test_machine_token
    base,_=context[2].export(user['id'])
    root=tmp_path/'host';root.mkdir()
    owned=objects(base)
    (root/'managed'/owned['agent_id']).mkdir(parents=True)
    SecretStore(root,filename='.env').set(owned['secret_ref'],token)
    path=root/'inteliscope-analysis'/(base['binding_id']+'.json')
    write_registry(path,{'base':base,'objects':owned,'token_sha256':validate_token(base,token),'state':'installed','execution_mode':mode})
    host=SimpleNamespace(root=root,gateway=SimpleNamespace(_credentials=lambda:('ws://localhost:18789','controlled')))
    def make(**kwargs):
        kwargs['client'].close()
        kwargs['client']=httpx.Client(transport=httpx.MockTransport(dispatch))
        kwargs['discover_models']=lambda:[{'id':'test/model','name':'Test'}]
        return InformationConnector(**kwargs)
    monkeypatch.setattr(analysis_supervisor,'InformationConnector',make)
    monkeypatch.delenv('INTELISCOPE_ANALYSIS_CATALOG_ONLY',raising=False)
    monkeypatch.delenv('INTELISCOPE_ANALYSIS_EXECUTION_MODE',raising=False)
    # Both paths see the same configured mode; only full may consume the formal run.
    standalone=InformationConnector(service_url='http://localhost',gateway_url='http://localhost:18789',service_token=token,
        gateway_token='controlled',agent_id=owned['agent_id'],journal=tmp_path/'standalone.json',
        discover_models=lambda:[{'id':'test/model','name':'Test'}],client=httpx.Client(transport=httpx.MockTransport(dispatch)))
    standalone.run_once(execution_mode=mode);standalone.close()
    analysis_supervisor.cycle(host,path)
    assert catalog(store,machine['binding_id'])['execution_mode']==mode
    assert len(calls)==(1 if mode=='full' else 0)
    assert get_preview(rules,user['id'],rule['id'],old['preview_id'])['reason']=='preview_confirmation_required'
    if mode=='catalog_only':
        with pytest.raises(RuleError): rules.test(user['id'],rule['id'],1,['new'],'new-click')
    else:
        fresh=rules.test(user['id'],rule['id'],1,['new'],'new-click')
        analysis_supervisor.cycle(host,path)
        assert get_preview(rules,user['id'],rule['id'],fresh['preview_id'])['status']=='completed'
        assert len(calls)==(2 if mode=='full' else 1)


def test_concurrent_tabs_atomically_share_one_preview(context):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from src.storage.service_store import ServiceStore
    from src.services.information_automations.rules import InformationRules
    store,rules,user,rule,_=prepare(context)
    barrier=Barrier(2)
    def submit(request):
        own=ServiceStore(store.data_dir)
        try:
            barrier.wait()
            return InformationRules(own,rules.targets).test(user['id'],rule['id'],1,['article'],request)['preview_id']
        finally: own.close()
    with ThreadPoolExecutor(2) as pool:
        values=list(pool.map(submit,['tab-one','tab-two']))
    assert values[0]==values[1]
    assert store.connect().execute('SELECT count(*) FROM information_previews').fetchone()[0]==1


def test_refresh_consumed_by_connector_failure_is_visible_without_releasing_block(context,client,tmp_path):
    store,_,_,_,machine=prepare(context)
    block_model(store.connect(),machine['binding_id'],'test/model');store.connect().commit()
    receipt=request_refresh(store,machine['binding_id'])['refresh']
    http,_=client
    def dispatch(req):
        res=http.post(req.url.path,content=req.content,headers={'Authorization':req.headers['Authorization'],'Content-Type':'application/json'})
        return httpx.Response(res.status_code,json=res.json())
    def fail(): raise ValueError('private upstream diagnostic')
    connector=InformationConnector(service_url='http://localhost',gateway_url='http://localhost:18789',service_token=store.test_machine_token,
        gateway_token='controlled',agent_id='ic-'+machine['binding_id'],journal=tmp_path/'result.json',discover_models=fail,
        client=httpx.Client(transport=httpx.MockTransport(dispatch)))
    with pytest.raises(ValueError): connector.run_once()
    connector.close()
    value=catalog(store,machine['binding_id'])
    assert value['refresh']['id']==receipt['id'] and value['refresh']['status']=='failed'
    assert value['refresh']['reason']=='model_discovery_failed' and value['models']==[]
    assert 'private' not in json.dumps(value)
