"""Discover changed effective configuration while preserving administrator restrictions."""
import asyncio
import json
import pytest
from tests.test_agent_connections import personal  # noqa: F401
from tests.test_agent_managed_host import installation  # noqa: F401
from tests.test_agent_analysis_host import prepared
from src.services.agent_connections.analysis_host import install
from src.services.agent_connections.analysis_supervisor import models
from src.services.agent_connections.analysis_model_policy import policy_path


@pytest.mark.parametrize('policy', ['system','administrator','unknown'])
def test_installed_allowlist_discovers_added_model_only_when_owned(installation,policy):
    host,base,token=prepared(installation)
    asyncio.run(install(host,base,token))
    if policy=='unknown': policy_path(host.root).unlink()
    if policy=='administrator':
        record=json.loads(policy_path(host.root).read_text());record['owner']='administrator'
        policy_path(host.root).write_text(json.dumps(record))
    original=host.gateway._request
    async def request(socket,identity,method,params):
        if method=='models.list':
            return {'models':[{'id':'model','provider':'test'},{'id':'new','provider':'test'}]}
        return await original(socket,identity,method,params)
    host.gateway._request=request
    value=asyncio.run(models(host,base))
    assert [row['id'] for row in value['models']]==(['test/model','test/new'] if policy=='system' else ['test/model'])
    if policy!='system':
        assert value['filtered_models'][0]['reason']==('allowlist_ownership_unknown' if policy=='unknown' else 'model_unauthorized')
    else:
        # Repeated sync is read-only once the configuration matches.
        count=len(host.gateway.writes);asyncio.run(models(host,base));assert len(host.gateway.writes)==count


def test_admin_edit_after_install_is_not_overwritten(installation):
    host,base,token=prepared(installation)
    asyncio.run(install(host,base,token))
    path=host.root/'openclaw.json';config=json.loads(path.read_text())
    config['plugins']['entries']['llm-task']['llm']['allowedCompletionModels']=[]
    path.write_text(json.dumps(config))
    assert asyncio.run(models(host,base))['models']==[]
    assert json.loads(path.read_text())==config
    assert json.loads(policy_path(host.root).read_text())['owner']=='administrator'
