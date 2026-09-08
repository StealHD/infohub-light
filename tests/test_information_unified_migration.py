"""Global 40 preserves immutable legacy facts and never implicitly upgrades."""
import json
from pathlib import Path
import pytest
from test_information_automation_rules import context  # noqa: F401
from src.storage import information_unified_schema as schema
from src.storage.information_automation_schema import schema_shapes_valid as v38_valid
from src.storage.information_connector_schema import schema_shapes_valid as v39_valid
from scripts.migrate_information_unified_v40 import migrate


def remove_v40(store):
    conn=store.connect()
    for name in reversed(schema.TABLES):
        conn.execute('DROP TABLE '+name)
    conn.execute('DELETE FROM schema_migrations WHERE version=40')
    conn.commit()


def test_explicit_backup_conversion_and_idempotence(context):
    store,rules,_,user,_,_,config,_=context
    rule=rules.save(user['id'],config)
    rules.transition(user['id'],rule['id'],1,'enable')
    remove_v40(store)
    conn=store.connect()
    legacy=json.dumps({'name':'Legacy','mode':'keyword','conditions':{'all':['AI'],'exclude':['advert']},
                       'source_ids':config.source_ids,'target_id':config.target_id,'requirement':''})
    conn.execute('UPDATE information_rules SET config_json=? WHERE id=?',(legacy,rule['id']))
    conn.execute('UPDATE information_rule_versions SET config_json=? WHERE rule_id=? AND version=1',(legacy,rule['id']))
    conn.commit()
    store.initialize()
    assert not schema.ready(store.connect())
    assert migrate(store.data_dir,apply=False)['status']=='migration_required'
    result=migrate(store.data_dir,apply=True)
    assert result['rules_upgraded']==1 and Path(result['backup']).stat().st_mode & 0o777 == 0o600
    updated=rules.get(user['id'],rule['id'])
    assert updated['version']==2 and updated['state']=='paused' and updated['config']['model'] is None
    assert 'AI' in updated['config']['requirement'] and 'advert' in updated['config']['requirement']
    assert store.connect().execute('SELECT config_json FROM information_rule_versions WHERE rule_id=? AND version=1',(rule['id'],)).fetchone()[0]==legacy
    assert v38_valid(store.connect()) and v39_valid(store.connect()) and schema.ready(store.connect())
    assert store.connect().execute('SELECT count(*) FROM information_events').fetchone()[0]==0
    assert migrate(store.data_dir,apply=True)['status']=='already_migrated'


def test_migration_restore_on_validation_failure(context,monkeypatch):
    store=context[0]
    remove_v40(store)
    monkeypatch.setattr(schema,'schema_shapes_valid',lambda _:False)
    with pytest.raises(RuntimeError):
        migrate(store.data_dir,apply=True)
    store.close()
    assert not schema.migration_marker_exists(store.connect())
    assert not store.connect().execute("SELECT name FROM sqlite_master WHERE name='information_batches'").fetchone()
    assert v39_valid(store.connect())
