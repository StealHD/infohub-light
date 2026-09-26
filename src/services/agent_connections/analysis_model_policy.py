"""Remove legacy completion allowlists; configured models own availability."""
import json
from .managed_host import host_lock, wait_loaded
from ..information_automations.model_discovery import project_models


async def reconcile(host, socket, personal, config):
    if 'allowedCompletionModels' not in config.get('plugins',{}).get('entries',{}).get('llm-task',{}).get('llm',{}):
        return config, None
    directory = host.root / 'inteliscope-analysis-policy-lock'
    if directory.resolve() != directory:
        raise ValueError('Unsafe policy lock directory')
    directory.mkdir(mode=0o700,exist_ok=True)
    # Separate from the installation root lock: cleanup holds root then binding,
    # whereas the supervisor holds binding while discovering policy.
    with host_lock(directory):
        current = await host.gateway._request(socket,'refresh-config','config.get',{})
        if current.get('path') != str(host.root/'openclaw.json') or not current.get('hash') or json.loads((host.root/'openclaw.json').read_text()) != config:
            raise ValueError('Analysis configuration changed')
        await host.gateway._request(socket,'refresh-policy','config.patch',{
            'baseHash':current['hash'],'raw':json.dumps({'plugins':{'entries':{'llm-task':{'llm':{'allowedCompletionModels':None}}}}}),
            'replacePaths':['plugins.entries.llm-task.llm.allowedCompletionModels'],
            'note':'Inteliscope managed model discovery'})
        await wait_loaded(host.gateway,socket)
        updated = json.loads((host.root/'openclaw.json').read_text())
        if updated.get('plugins',{}).get('entries',{}).get('llm-task',{}).get('llm',{}).get('allowedCompletionModels') is not None:
            raise ValueError('Analysis policy not loaded')
        return updated, None


def project_discovery(personal, analysis, config, policy_reason=None):
    permitted = {row['id'] for row in project_models(personal,config)}
    models = [row for row in project_models(analysis,config) if row['id'] in permitted]
    available = {row['id'] for row in models}
    filtered = [{'id':row['id'],'reason':'agent_model_unavailable'}
                for row in project_models(personal,config) if row['id'] not in available]
    return {'models':models,'filtered_models':filtered}
