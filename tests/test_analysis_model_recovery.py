"""Configured models stay usable after retiring every legacy model allowlist."""
import asyncio
import json
import pytest
from tests.test_agent_connections import personal  # noqa: F401
from tests.test_agent_managed_host import installation  # noqa: F401
from tests.test_agent_analysis_host import prepared
from src.services.agent_connections.analysis_host import install
from src.services.agent_connections.analysis_supervisor import models


@pytest.mark.parametrize('policy', ['system','administrator','unknown'])
@pytest.mark.parametrize('allowed', [[], ['test/model']])
def test_installed_allowlist_is_retired_regardless_of_old_ownership(installation,policy,allowed):
    host,base,token=prepared(installation)
    asyncio.run(install(host,base,token))
    path = host.root / 'openclaw.json'
    config = json.loads(path.read_text())
    config['plugins']['entries']['llm-task']['llm']['allowedCompletionModels'] = allowed
    path.write_text(json.dumps(config))
    if policy != 'unknown':
        (host.root/'inteliscope-analysis-policy.json').write_text(json.dumps({'owner':policy,'models':allowed}))
    original=host.gateway._request
    async def request(socket,identity,method,params):
        if method=='models.list':
            return {'models':[{'id':'model','provider':'test'},{'id':'new','provider':'test'}]}
        return await original(socket,identity,method,params)
    host.gateway._request=request
    value=asyncio.run(models(host,base))
    assert [row['id'] for row in value['models']]==['test/model','test/new']
    assert value['filtered_models']==[]
    assert 'allowedCompletionModels' not in json.loads(path.read_text())['plugins']['entries']['llm-task']['llm']
    # Repeated sync is read-only once the configuration matches.
    count=len(host.gateway.writes);asyncio.run(models(host,base));assert len(host.gateway.writes)==count


def test_allowlist_retirement_preserves_other_settings_and_creates_no_snapshot(installation):
    host,base,token=prepared(installation)
    asyncio.run(install(host,base,token))
    path=host.root/'openclaw.json';config=json.loads(path.read_text())
    config['plugins']['entries']['llm-task']['llm']['allowedCompletionModels']=[]
    config['plugins']['entries']['llm-task']['llm']['allowModelOverride']=True
    path.write_text(json.dumps(config))
    assert asyncio.run(models(host,base))['models'][0]['id']=='test/model'
    del config['plugins']['entries']['llm-task']['llm']['allowedCompletionModels']
    assert json.loads(path.read_text())==config
    assert not (host.root/'inteliscope-analysis-policy.json').exists()


@pytest.mark.parametrize('allowed', [None, [], ['test/personal'], ['test/both']])
def test_catalog_is_usable_configured_intersection(allowed):
    from src.services.agent_connections.analysis_model_policy import project_discovery
    policy = {'allowModelOverride': True}
    if allowed is not None:
        policy['allowedCompletionModels'] = allowed
    config = {'plugins': {'entries': {'llm-task': {'enabled': True, 'llm': policy}}}}
    personal = {'models': [{'provider': 'test', 'id': 'both'}, {'provider': 'test', 'id': 'personal'}, {'provider': 'test', 'id': 'offline', 'available': False}]}
    analysis = {'models': [{'provider': 'test', 'id': 'both'}, {'provider': 'test', 'id': 'analysis'}, {'provider': 'test', 'id': 'offline'}]}
    value = project_discovery(personal, analysis, config)
    assert [row['id'] for row in value['models']] == ['test/both']
    assert value['filtered_models'] == [{'id':'test/personal','reason':'agent_model_unavailable'}]


def test_config_race_prevents_retiring_a_different_revision(installation):
    host,base,token=prepared(installation)
    asyncio.run(install(host,base,token))
    path=host.root/'openclaw.json';config=json.loads(path.read_text())
    config['plugins']['entries']['llm-task']['llm']['allowedCompletionModels']=[]
    path.write_text(json.dumps(config))
    original=host.gateway._request
    async def request(socket,identity,method,params):
        result=await original(socket,identity,method,params)
        if identity=='refresh-config':
            changed=json.loads(path.read_text());changed['changed']=True;path.write_text(json.dumps(changed))
        return result
    host.gateway._request=request
    count=len(host.gateway.writes)
    with pytest.raises(ValueError,match='configuration changed'):
        asyncio.run(models(host,base))
    assert len(host.gateway.writes)==count


def test_standalone_discovery_retires_legacy_policy_once(installation, monkeypatch):
    from src.services.information_automations import model_discovery as discovery
    host,base,token=prepared(installation)
    asyncio.run(install(host,base,token))
    path=host.root/'openclaw.json';config=json.loads(path.read_text())
    config['plugins']['entries']['llm-task']['llm']['allowedCompletionModels']=[]
    path.write_text(json.dumps(config))
    scopes=[]
    async def rpc(*args, operation, **kwargs):
        scopes.append(kwargs.get('scopes'))
        return await operation(None)
    monkeypatch.setattr(discovery,'rpc_models',rpc)
    monkeypatch.setattr(discovery,'model_request',host.gateway._request)
    for _ in range(2):
        value=discovery.discover('http://127.0.0.1:18789','fixture-token','ic-'+base['binding_id'],host.root/'device',path)
        assert value['models'][0]['id']=='test/model'
    assert scopes==[['operator.admin'],None]
