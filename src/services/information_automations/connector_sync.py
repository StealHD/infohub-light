"""Shared control polling for standalone and supervised connectors."""
import time
from . import completion_guard


def synchronize(connector, mode):
    if not connector.discover_models:
        return
    request = connector.service('control', {}).get('refresh_request_id')
    if mode == 'catalog_only' or request or time.monotonic()-connector.catalog_at >= 30:
        try:
            models = connector.discover_models()
        except Exception:
            if request:
                connector.service('refresh-failure', {'request_id':request})
            raise
        payload = models if isinstance(models,dict) else {'models':models}
        connector.service('capabilities', {'protocol_version':2,'catalog_only':mode=='catalog_only',
            'execution_mode':mode,'refresh_request_id':request,
            'runtime_block':'completion_unknown' if completion_guard.uncertain(connector.journal) else None, **payload})
        connector.catalog_at = time.monotonic()


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
