"""Shared control polling for standalone and supervised connectors."""
from . import completion_guard


def synchronize(connector, mode):
    """Heartbeat first; a model discovery must never race an LLM task.

    The managed connector is recreated for every supervisor cycle, so an
    in-memory refresh timer made every cycle invoke ``models.list``.  That
    starts a Codex app-server process and could make the following isolated
    completion fail before it created its thread.  The Service owns durable
    freshness and tells us when a discovery is actually required.
    """
    runtime_block = 'completion_unknown' if completion_guard.uncertain(connector.journal) else None
    control = connector.service('control', {
        'protocol_version': 2,
        'execution_mode': mode,
        'runtime_block': runtime_block,
    })
    request = control.get('refresh_request_id')
    if not (request or control.get('catalog_refresh_required')):
        return False
    if not connector.discover_models:
        return False
    try:
        models = connector.discover_models()
    except Exception:
        if request:
            connector.service('refresh-failure', {'request_id':request})
        raise
    payload = models if isinstance(models,dict) else {'models':models}
    connector.service('capabilities', {'protocol_version':2,'catalog_only':mode=='catalog_only',
        'execution_mode':mode,'refresh_request_id':request, 'runtime_block':runtime_block, **payload})
    # Never start a completion in the same cycle as a Gateway model read.
    return True


def execution_mode(record, environment):
    explicit = environment.get('INTELISCOPE_ANALYSIS_EXECUTION_MODE')
    mode = explicit or record.get('execution_mode')
    if environment.get('INTELISCOPE_ANALYSIS_CATALOG_ONLY') not in {None,'false'}:
        return 'catalog_only'
    if mode is None:
        # Preserve the old deployment default until an operator explicitly switches it.
        mode = 'catalog_only' if record.get('catalog_only') or environment.get('INTELISCOPE_ANALYSIS_CATALOG_ONLY') != 'false' else 'full'
    if mode not in {'catalog_only','previews_only','full'}:
        raise ValueError('Invalid analysis execution mode')
    return mode
