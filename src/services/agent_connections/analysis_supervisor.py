"""One host supervisor, isolated credentials/journals and bounded binding workers."""
import asyncio
import hashlib
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit, urlunsplit
import httpx
from .analysis_manifest import objects
from .analysis_host import write_registry
from .managed_host import host_lock
from ..secret_store import SecretStore
from ..information_automations.connector_runner import InformationConnector
from ..information_automations.model_discovery import project_models


async def models(host, base):
    async def operation(socket, hello):
        payload = await host.gateway._request(socket, 'managed-models', 'models.list',
            {'view': 'configured', 'agentId': objects(base)['agent_id']})
        personal = await host.gateway._request(socket, 'personal-models', 'models.list',
            {'view': 'configured', 'agentId': base['agent_id']})
        config = json.loads((host.root / 'openclaw.json').read_text())
        permitted = {row['id'] for row in project_models(personal, config)}
        return [row for row in project_models(payload, config) if row['id'] in permitted]
    return await host.gateway._session(operation)


def cycle(host, path):
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError('Unsafe registry')
    record = json.loads(path.read_text())
    base = record['base']
    owned = objects(base)
    if path.name != base['binding_id'] + '.json' or record['objects'] != owned or record['state'] != 'installed':
        return
    directory = host.root / 'managed' / owned['agent_id']
    if directory.resolve() != directory:
        raise ValueError('Unsafe runtime directory')
    with host_lock(directory):
        # Re-read the fence after acquiring the per-binding execution lock.
        if json.loads(path.read_text()) != record or (host.root / 'inteliscope-revoked' / base['binding_id']).exists():
            return
        values = SecretStore(host.root, filename='.env').read()
        token = values.get(owned['secret_ref'], '')
        if hashlib.sha256(token.encode()).hexdigest() != record['token_sha256']:
            raise ValueError('Credential changed')
        url, gateway_token = host.gateway._credentials()
        parsed = urlsplit(url)
        gateway_url = urlunsplit(('https' if parsed.scheme == 'wss' else 'http', parsed.netloc, '', '', ''))
        connector = InformationConnector(service_url=base['mcp_url'].removesuffix('/mcp'), service_token=token,
            gateway_url=gateway_url, gateway_token=gateway_token, agent_id=owned['agent_id'],
            journal=directory / 'result.json', discover_models=lambda: asyncio.run(models(host, base)),
            client=httpx.Client(timeout=75, follow_redirects=False))
        try:
            result = connector.run_once(catalog_only=record['catalog_only'] or os.getenv('INTELISCOPE_ANALYSIS_CATALOG_ONLY', 'true') != 'false')
            write_registry(directory / 'supervisor-status.json',
                {'binding_id': base['binding_id'], 'state': result['status'], 'checked_at': time.time()})
        finally:
            connector.close()


def serve(host, stop):
    running, last_started = {}, {}
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix='analysis-binding') as workers:
        while not stop.wait(1):
            for path, (future, started) in list(running.items()):
                if future.done() and time.monotonic() - started >= 30:
                    # Never print exception text, credentials, prompts or upstream responses.
                    if future.exception():
                        logging.getLogger(__name__).warning('managed_analysis_unavailable')
                    del running[path]
            directory = host.root / 'inteliscope-analysis'
            if not directory.exists():
                continue
            if directory.is_symlink():
                raise ValueError('Unsafe registry directory')
            for path in sorted(directory.glob('*.json'), key=lambda value: last_started.get(value, 0)):
                if path not in running and len(running) < 4:
                    last_started[path] = time.monotonic()
                    running[path] = (workers.submit(cycle, host, path), last_started[path])
