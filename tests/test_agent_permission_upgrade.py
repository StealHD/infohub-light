import asyncio
import json
from types import SimpleNamespace
from tests.test_agent_connections import personal, bind  # noqa: F401
from tests.test_agent_managed_host import installation  # noqa: F401
from src.services.agent_connections.manifest import READ_TOOLS, USER_TOOLS, canonical, receipt
from src.services.agent_connections.permission_upgrade import upgrade
from src.services.agent_connections.gateway_config import configure


def test_upgrade_preserves_token_identity_and_retries_without_drift(installation, personal, monkeypatch):
    host, manifest, token = installation
    store, connections, owner, _ = personal
    legacy = {**manifest, 'version': 2, 'tools': list(READ_TOOLS)}
    store.connect().execute('UPDATE agent_connections SET manifest_json=? WHERE user_id=?', (canonical(legacy), owner['id']))
    store.connect().commit()
    asyncio.run(host.install(legacy, token))
    connections.activate(owner['id'], receipt(legacy, token, 'a'*64))
    monkeypatch.setattr('src.services.agent_connections.permission_upgrade.ManagedHost', lambda _: host)
    context = SimpleNamespace(store=store, secret_values=connections.secrets)
    asyncio.run(upgrade(context, owner))
    current, same_token = connections.export(owner['id'])
    assert same_token == token
    assert current['binding_id'] == legacy['binding_id']
    assert current['delegation_id'] == legacy['delegation_id']
    assert current['version'] == 3 and current['tools'] == list(USER_TOOLS)
    installed = json.loads((host.root/'openclaw.json').read_text())
    assert configure(installed, current, host.root) == installed
    count = len(host.gateway.writes)
    asyncio.run(upgrade(context, owner))
    assert len(host.gateway.writes) == count
