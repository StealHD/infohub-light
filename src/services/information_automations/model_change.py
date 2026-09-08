"""A model-only edit keeps already queued content for the next explicit approval."""
import json
import uuid
from datetime import datetime, timezone
from .config import RuleConfig
from .batches import create_batch


def preserve_waiting(conn, row, config):
    before = RuleConfig.model_validate_json(row['config_json']).model_dump(exclude={'model'})
    if before != config.model_dump(exclude={'model'}):
        conn.execute('DELETE FROM information_rule_carry WHERE rule_id=?',(row['id'],))
        conn.execute('DELETE FROM information_event_carry WHERE rule_id=?',(row['id'],))
        return
    if row['state'] == 'active':
        from .execution import matching_events
        for event in matching_events(conn,row,config,datetime.now(timezone.utc)):
            conn.execute('INSERT OR IGNORE INTO information_event_carry VALUES(?,?)',(row['id'],event['id']))
    conn.execute('''INSERT OR IGNORE INTO information_rule_carry(old_run_id,rule_id)
        SELECT id,rule_id FROM information_runs WHERE rule_id=? AND status IN ('pending','judging','quota_wait')
        AND notification_status='not_required' ''',(row['id'],))


def resume_waiting(conn, row, config, now):
    previous = conn.execute('''SELECT r.* FROM information_runs r JOIN information_rule_carry c ON c.old_run_id=r.id
        WHERE c.rule_id=? ORDER BY r.created_at,r.id''',(row['id'],)).fetchall()
    for old in previous:
        identity = 'iarun_' + uuid.uuid4().hex
        conn.execute('''INSERT INTO information_runs
            (id,rule_id,version,confirmation_id,status,notification_status,input_json,event_ids_json,ready_at,created_at,updated_at)
            VALUES(?,?,?,?,'pending','not_required',?,?,?,?,?)''',
            (identity,row['id'],row['version'],row['confirmation_id'],old['input_json'],old['event_ids_json'],now,now,now))
        create_batch(conn,config,json.loads(old['input_json']),now,run_id=identity)
    conn.execute('DELETE FROM information_rule_carry WHERE rule_id=?',(row['id'],))
