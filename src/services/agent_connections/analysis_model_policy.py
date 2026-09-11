"""Track only a system-created allowlist; never infer ownership of legacy lists."""
import copy
import json
from .managed_host import host_lock, wait_loaded
from ..information_automations.model_discovery import project_models


def policy_path(root):
    path = root / 'inteliscope-analysis-policy.json'
    if path.is_symlink() or path.exists() and path.stat().st_mode & 0o077:
        raise ValueError('Unsafe analysis policy record')
    return path


def record_policy(root, models, owner='system'):
    from .analysis_host import write_registry
    write_registry(policy_path(root),{'owner':owner,'models':sorted(models)})


def unfiltered(payload, config):
    value = copy.deepcopy(config)
    value.get('plugins',{}).get('entries',{}).get('llm-task',{}).get('llm',{}).pop('allowedCompletionModels',None)
    return project_models(payload,value)


async def reconcile(host, socket, personal, config):
    directory = host.root / 'inteliscope-analysis-policy-lock'
    if directory.resolve() != directory:
        raise ValueError('Unsafe policy lock directory')
    directory.mkdir(mode=0o700,exist_ok=True)
    # Separate from the installation root lock: cleanup holds root then binding,
    # whereas the supervisor holds binding while discovering policy.
    with host_lock(directory):
        path = policy_path(host.root)
        policy = json.loads(path.read_text()) if path.exists() else None
        llm = config.get('plugins',{}).get('entries',{}).get('llm-task',{}).get('llm',{})
        allowed = llm.get('allowedCompletionModels')
        if allowed is None:
            return config, None
        if not policy:
            return config, 'allowlist_ownership_unknown'
        if policy['owner'] != 'system' or sorted(allowed) != policy['models']:
            record_policy(host.root,allowed,'administrator')
            return config, 'model_unauthorized'
        desired = sorted(set(allowed) | {row['id'] for row in unfiltered(personal,config)})
        if desired == sorted(allowed):
            return config, None
        current = await host.gateway._request(socket,'refresh-config','config.get',{})
        if current.get('path') != str(host.root/'openclaw.json') or not current.get('hash') or json.loads((host.root/'openclaw.json').read_text()) != config:
            raise ValueError('Analysis configuration changed')
        await host.gateway._request(socket,'refresh-policy','config.patch',{
            'baseHash':current['hash'],'raw':json.dumps({'plugins':{'entries':{'llm-task':{'llm':{'allowedCompletionModels':desired}}}}}),
            'replacePaths':['plugins.entries.llm-task.llm.allowedCompletionModels'],'note':'Inteliscope managed model discovery'})
        await wait_loaded(host.gateway,socket)
        updated = json.loads((host.root/'openclaw.json').read_text())
        if updated.get('plugins',{}).get('entries',{}).get('llm-task',{}).get('llm',{}).get('allowedCompletionModels') != desired:
            raise ValueError('Analysis policy not loaded')
        record_policy(host.root,desired)
        return updated, None


def project_discovery(personal, analysis, config, policy_reason=None):
    permitted = {row['id'] for row in project_models(personal,config)}
    models = [row for row in project_models(analysis,config) if row['id'] in permitted]
    available = {row['id'] for row in models}
    filtered = [{'id':row['id'],'reason':policy_reason or ('model_unauthorized' if row['id'] not in permitted else 'agent_model_unavailable')}
                for row in unfiltered(personal,config) if row['id'] not in available]
    return {'models':models,'filtered_models':filtered}
