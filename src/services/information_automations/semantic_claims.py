"""One fenced, quota-accounted connector pipeline for every automation."""
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from .connector_auth import authenticate, token_digest
from .rules import RuleError, transaction
from .limits import SEMANTIC_USER_DAILY_BATCHES
from .batches import validate, complete_step
from .claim_context import parent_context, parent_state, context_error

LEASE_SECONDS = 180
MAX_ATTEMPTS = 3


def expire_claims(conn, now):
    rows = conn.execute("""SELECT c.*,s.id AS step_id,s.attempts AS step_attempts,b.id AS batch_id FROM information_claims c
        JOIN information_batch_steps s ON s.claim_id=c.id JOIN information_batches b ON b.id=s.batch_id
        WHERE c.status='claimed' AND c.expires_at<=?""", (now.isoformat(),)).fetchall()
    for claim in rows:
        batch = conn.execute('SELECT * FROM information_batches WHERE id=?',(claim['batch_id'],)).fetchone()
        status = 'pending' if claim['step_attempts'] < MAX_ATTEMPTS else 'failed'
        conn.execute('UPDATE information_batch_steps SET status=? WHERE id=?', (status,claim['step_id']))
        table, identity = ('information_runs',batch['run_id']) if batch['run_id'] else ('information_previews',batch['preview_id'])
        parent = conn.execute(f'SELECT status,claim_hash FROM {table} WHERE id=?',(identity,)).fetchone()
        if not batch['result_json'] and parent['status']=='judging' and parent['claim_hash']==claim['token_hash']:
            parent_state(conn,batch,status,'semantic_lease_expired')
        conn.execute("UPDATE information_claims SET status='expired',completed_at=? WHERE id=?", (now.isoformat(),claim['id']))


def allocate(conn, machine, batch, step, parent, config, now):
    identity, lease = 'icclaim_' + uuid.uuid4().hex, secrets.token_urlsafe(32)
    expires = (now + timedelta(seconds=LEASE_SECONDS)).isoformat()
    conn.execute('''INSERT INTO information_claims
        (id,run_id,preview_id,user_id,binding_id,connector_generation,token_hash,status,created_at,expires_at)
        VALUES(?,?,?,?,?,?,?,'claimed',?,?)''',
        (identity,batch['run_id'],batch['preview_id'],machine['user_id'],machine['binding_id'],machine['generation'],token_digest(lease),now.isoformat(),expires))
    conn.execute("UPDATE information_batch_steps SET status='judging',attempts=attempts+1,claim_id=? WHERE id=?",(identity,step['id']))
    parent_state(conn,batch,'judging')
    table, parent_id = ('information_runs',batch['run_id']) if batch['run_id'] else ('information_previews',batch['preview_id'])
    conn.execute(f'UPDATE {table} SET claim_hash=?,attempts=attempts+1 WHERE id=?',(token_digest(lease),parent_id))
    return {'task': {'protocol_version':2,'claim_id':identity,'claim_token':lease,'agent_id':machine['agent_id'],
            'run_id':batch['run_id'],'preview_id':batch['preview_id'],'stage':step['kind'],
            'requirement':config.requirement,'model':config.model.model_dump(),'input':json.loads(step['input_json']),
            'expires_at':expires},'retry_after':0}


def claim_work(store, targets, machine_token, *, now=None, daily_limit=SEMANTIC_USER_DAILY_BATCHES, protocol_version=2):
    from ...storage.information_unified_schema import ready
    if not ready(store.connect()):
        raise RuleError('information_migration_required','请先完成 global 40 迁移。',503)
    now = now or datetime.now(timezone.utc)
    with transaction(store) as conn:
        machine = authenticate(store,machine_token)
        if protocol_version != 2:
            raise RuleError('connector_upgrade_required','请升级自动化 connector 至协议 2。')
        conn.execute('UPDATE information_connectors SET last_seen=? WHERE binding_id=?',(now.isoformat(),machine['binding_id']))
        expire_claims(conn,now)
        if conn.execute("SELECT 1 FROM information_claims WHERE user_id=? AND status='claimed' AND expires_at>?",(machine['user_id'],now.isoformat())).fetchone():
            return {'task':None,'reason':'user_concurrency','retry_after':15}
        start = now.astimezone(ZoneInfo('Asia/Shanghai')).replace(hour=0,minute=0,second=0,microsecond=0)
        count = conn.execute('SELECT count(*) FROM information_claims WHERE user_id=? AND created_at>=?',(machine['user_id'],start.astimezone(timezone.utc).isoformat())).fetchone()[0]
        steps = conn.execute('''SELECT s.* FROM information_batch_steps s JOIN information_batches b ON b.id=s.batch_id
            LEFT JOIN information_runs r ON r.id=b.run_id LEFT JOIN information_previews p ON p.id=b.preview_id
            JOIN information_rules q ON q.id=COALESCE(r.rule_id,p.rule_id)
            WHERE q.user_id=? AND s.status='pending' AND b.result_json IS NULL
            AND COALESCE(r.status,p.status) IN ('pending','quota_wait') AND COALESCE(r.ready_at,p.ready_at)<=?
            ORDER BY b.created_at,s.level,s.ordinal LIMIT 50''',(machine['user_id'],now.isoformat())).fetchall()
        waiting = None
        for step in steps:
            batch = conn.execute('SELECT * FROM information_batches WHERE id=?',(step['batch_id'],)).fetchone()
            try:
                parent,config,_ = parent_context(store,targets,batch,machine,now)
            except RuleError as error:
                context_error(conn,batch,error,now); waiting = error.code; continue
            if count >= daily_limit:
                parent_state(conn,batch,'quota_wait','daily_semantic_limit',(start+timedelta(days=1)).astimezone(timezone.utc).isoformat())
                return {'task':None,'reason':'daily_semantic_limit','retry_after':60}
            return allocate(conn,machine,batch,step,parent,config,now)
        return {'task':None,'reason':waiting or 'empty','retry_after':15}


def authorized_claim(conn,machine,claim_id,claim_token,digest,now):
    claim = conn.execute('SELECT * FROM information_claims WHERE id=? AND user_id=?',(claim_id,machine['user_id'])).fetchone()
    if not claim or claim['token_hash'] != token_digest(claim_token) or claim['binding_id'] != machine['binding_id'] or claim['connector_generation'] != machine['generation']:
        raise RuleError('claim_unauthorized','任务领取凭据无效。',403)
    if claim['status'] == 'completed':
        if claim['result_hash'] != digest:
            raise RuleError('result_conflict','结果已提交，不可覆盖。')
        return claim,True
    if claim['status'] != 'claimed' or claim['expires_at'] <= now.isoformat():
        raise RuleError('claim_expired','任务领取已过期。')
    return claim,False


def submit_result(store,targets,machine_token,claim_id,claim_token,result,*,now=None):
    from ...storage.information_unified_schema import ready
    if not ready(store.connect()):
        raise RuleError('information_migration_required','请先完成 global 40 迁移。',503)
    now = now or datetime.now(timezone.utc)
    digest = token_digest(json.dumps(result,sort_keys=True,separators=(',',':'),ensure_ascii=True))
    with transaction(store) as conn:
        machine = authenticate(store,machine_token)
        claim,duplicate = authorized_claim(conn,machine,claim_id,claim_token,digest,now)
        if duplicate:
            return {'accepted':True,'duplicate':True}
        step = conn.execute("SELECT * FROM information_batch_steps WHERE claim_id=? AND status='judging'",(claim_id,)).fetchone()
        if not step:
            raise RuleError('claim_superseded','分析步骤已变化。')
        batch = conn.execute('SELECT * FROM information_batches WHERE id=?',(step['batch_id'],)).fetchone()
        try:
            _,config,inputs = parent_context(store,targets,batch,machine,now)
        except RuleError as error:
            context_error(conn,batch,error,now)
            conn.execute("UPDATE information_claims SET status='rejected',completed_at=? WHERE id=?",(now.isoformat(),claim_id))
            conn.execute("UPDATE information_batch_steps SET status='pending' WHERE id=?",(step['id'],))
            return {'accepted':False,'reason':error.code}
        if result == {'error': 'isolated_completion_failed'}:
            from .model_catalog import block_model
            block_model(conn,machine['binding_id'],config.model.id)
            parent_state(conn,batch,'pending','analysis_model_unavailable',(now+timedelta(minutes=5)).isoformat())
            conn.execute("UPDATE information_batch_steps SET status='pending' WHERE id=?",(step['id'],))
            conn.execute("UPDATE information_claims SET status='completed',result_hash=?,completed_at=? WHERE id=?",(digest,now.isoformat(),claim_id))
            return {'accepted':True,'status':'pending','duplicate':False}
        try:
            if set(result) != {'output','model'} or result['model'] != config.model.id:
                raise ValueError('actual_model_mismatch')
            output = validate(result['output'],step,inputs)
            state = complete_step(conn,step,output,config)
            if state == 'pending':
                parent_state(conn,batch,'pending')
        except (ValueError,TypeError,KeyError):
            state = 'failed'
            parent_state(conn,batch,'failed',result.get('error') if result in ({'error':'analysis_timeout'},{'error':'analysis_call_failed'}) else 'invalid_model_output')
            conn.execute("UPDATE information_batch_steps SET status='failed' WHERE id=?",(step['id'],))
        conn.execute("UPDATE information_claims SET status='completed',result_hash=?,completed_at=? WHERE id=?",(digest,now.isoformat(),claim_id))
        return {'accepted':True,'status':state,'duplicate':False}


def maintain_semantic_leases(store):
    from ...storage.information_unified_schema import ready
    if ready(store.connect()):
        with transaction(store) as conn:
            expire_claims(conn,datetime.now(timezone.utc))
