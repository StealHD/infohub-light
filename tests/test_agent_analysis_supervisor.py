import asyncio
import json
import pytest
from tests.test_agent_connections import personal  # noqa: F401
from tests.test_agent_managed_host import installation  # noqa: F401
from tests.test_agent_analysis_host import prepared
from src.services.agent_connections.analysis_host import install, registry_path, write_registry
from src.services.agent_connections import analysis_supervisor as supervisor
from src.services.secret_store import SecretStore


def test_restart_catalog_only_and_revocation_fence(installation, monkeypatch):
    host, base, token = prepared(installation)
    asyncio.run(install(host, base, token))
    path = registry_path(host.root, base)
    host.gateway._credentials = lambda: ('ws://127.0.0.1:18789', 'private-gateway-token')
    calls = []
    class Connector:
        def __init__(self, **kwargs):
            assert kwargs['service_token'] == token
            assert kwargs['agent_id'] == 'ic-' + base['binding_id']
            self.client = kwargs['client']
        def run_once(self, **kwargs):
            calls.append(kwargs)
            return {'status': 'catalog_synced'}
        def close(self):
            self.client.close()
    monkeypatch.setattr(supervisor, 'InformationConnector', Connector)
    monkeypatch.delenv('INTELISCOPE_ANALYSIS_CATALOG_ONLY', raising=False)
    supervisor.cycle(host, path)
    supervisor.cycle(host, path)  # A new cycle/process does not install or enable claims.
    assert calls == [{'catalog_only': True}, {'catalog_only': True}]
    assert len(host.gateway.writes) == 1
    record = json.loads(path.read_text())
    write_registry(path, {**record, 'state': 'revoked'})
    supervisor.cycle(host, path)
    assert len(calls) == 2


def test_changed_credential_never_used_for_claims(installation):
    host, base, token = prepared(installation)
    asyncio.run(install(host, base, token))
    SecretStore(host.root, filename='.env').set('INTELISCOPE_CONNECTOR_' + base['binding_id'].upper(), 'changed')
    with pytest.raises(ValueError, match='Credential changed'):
        supervisor.cycle(host, registry_path(host.root, base))


def test_service_installation_does_not_enable_claims():
    from scripts.install_analysis_supervisor import unit
    from pathlib import Path
    value = unit(Path('/srv/adapter'))
    assert 'UMask=0077' in value and 'KillMode=control-group' in value
    assert 'CATALOG_ONLY=false' not in value and 'openclaw-gateway.service' in value
    with pytest.raises(ValueError):
        unit(Path('/srv/%n'))
