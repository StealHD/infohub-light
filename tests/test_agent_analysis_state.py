import json
import pytest
from tests.test_information_automation_rules import context  # noqa: F401
from src.storage.agent_analysis_schema import apply_migration, ready
from src.services.agent_connections.analysis_state import record, public
from src.services.agent_connections.managed_host import ManagedSetupError
from src.services.information_automations.model_catalog import Capabilities, sync_catalog, catalog
from src.services.information_automations.connector_auth import authenticate


def test_existing_database_is_not_automatically_migrated_or_populated(context):
    store = context[0]
    conn = store.connect()
    conn.execute('DROP TABLE agent_analysis')
    conn.execute('DELETE FROM schema_migrations WHERE version=44')
    conn.commit()
    store.initialize()
    assert not ready(conn)
    apply_migration(conn)
    apply_migration(conn)
    assert ready(conn)
    assert conn.execute('SELECT count(*) FROM agent_analysis').fetchone()[0] == 0


def test_state_is_bound_and_revocation_cannot_be_overwritten(context):
    store, _, bindings, alice, bob, *_ = context
    base, token = bindings.export(alice['id'])
    other, _ = bindings.export(bob['id'])
    record(store, base, 'configuring')
    assert public(store, other['binding_id'])['phase'] == 'not_configured'
    row = store.connect().execute('SELECT * FROM agent_analysis').fetchone()
    assert token not in str(dict(row))
    assert json.loads(row['objects_json'])['agent_id'] == 'ic-' + base['binding_id']
    record(store, base, 'revoking')
    with pytest.raises(ManagedSetupError):
        record(store, base, 'ready')
    assert public(store, base['binding_id'])['phase'] == 'revoking'


def test_host_catalog_alone_does_not_prove_supervisor_heartbeat(context):
    store, _, bindings, alice, *_ = context
    base, _ = bindings.export(alice['id'])
    record(store, base, 'catalog_ready')
    machine = authenticate(store, store.test_machine_token)
    store.connect().execute('UPDATE information_connectors SET last_seen=NULL,verified_at=NULL')
    store.connect().commit()
    body = Capabilities(protocol_version=2, models=[{'id': 'test/model', 'name': 'Test'}], catalog_only=True)
    sync_catalog(store, machine, body, runtime_verified=False)
    assert catalog(store, base['binding_id'])['status'] != 'ready'
    sync_catalog(store, machine, body)
    assert public(store, base['binding_id'])['phase'] == 'catalog_only'
    assert catalog(store, base['binding_id'])['status'] == 'ready'
