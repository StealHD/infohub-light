"""Trigger, cross-item synthesis, bounded recovery and runtime model fencing."""
from datetime import datetime, timedelta, timezone
import json
import pytest
from test_information_automation_rules import context  # noqa: F401
from test_information_automation_execution import acquire, judge_all, ACK
from test_information_semantic_claims import answer
from src.services.information_automations.config import RuleConfig, Trigger
from src.services.information_automations.scheduling import next_due, advance_due
from src.services.information_automations.execution import evaluate_pending
from src.services.information_automations.semantic_claims import claim_work, submit_result, expire_claims
from src.services.information_automations.delivery import dispatch_pending
from src.services.information_automations.model_catalog import Capabilities, sync_catalog, catalog
from src.services.information_automations.connector_auth import authenticate
from src.services.information_automations.model_discovery import project_models


def activated(ctx, trigger):
    store,rules,_,user,_,_,config,_ = ctx
    now = datetime.now(timezone.utc)
    acquire(ctx,['baseline'],now)
    config = config.model_copy(update={'trigger':Trigger(**trigger)})
    rule = rules.save(user['id'],config)
    rules.transition(user['id'],rule['id'],1,'enable')
    return store,rules,user,rule,now


@pytest.mark.parametrize('trigger,early,late,expected',[
    ({'kind':'each'},0,0,1),
    ({'kind':'count','count':3,'max_wait_seconds':None},0,3600,0),
    ({'kind':'count','count':3,'max_wait_seconds':60},59,61,1),
    ({'kind':'interval','interval_seconds':60},59,61,1),
])
def test_trigger_time_and_count_only_consume_ready_content(context,trigger,early,late,expected):
    store,rules,user,rule,now=activated(context,trigger)
    acquire(context,['one','two'],now)
    if trigger['kind']!='each':
        assert evaluate_pending(store,rules.targets,now=now+timedelta(seconds=early))==[]
        assert rules.row(user,rule['id'])['cursor']==0
    assert len(evaluate_pending(store,rules.targets,now=now+timedelta(seconds=late)))==expected
    if trigger['kind']=='each':
        assert rules.get(user['id'],rule['id'])['pending_count']==1


def test_count_batch_spans_selected_sources_and_remainder_waits(context):
    store,rules,_,user,_,_,config,_=context
    other=store.create_source(workspace_id=user['workspace_id'],scope='workspace',owner_user_id=user['id'],
                             source_type='rss',display_name='Other',config={'url':'https://example.com/other'})
    store.create_subscription(user_id=user['id'],source_id=other)
    combined=(*context[:6],config.model_copy(update={'source_ids':[*config.source_ids,other]}),context[7])
    store,rules,_,rule,now=activated(combined,{'kind':'count','count':3,'max_wait_seconds':None})
    acquire(context,['a','b'],now)
    second=(*context[:6],config.model_copy(update={'source_ids':[other]}),context[7])
    acquire(second,['c','d'],now)
    assert len(evaluate_pending(store,rules.targets,now=now))==1
    assert evaluate_pending(store,rules.targets,now=now+timedelta(hours=1))==[]
    row=store.connect().execute('SELECT event_ids_json,input_json FROM information_runs').fetchone()
    assert len(json.loads(row[0]))==3
    assert {source for item in json.loads(row[1]) for source in item['source_ids']}=={*config.source_ids,other}


def test_calendar_dst_weekday_and_interval_do_not_drift():
    utc=timezone.utc
    trigger=Trigger(kind='calendar',time='02:30',timezone='America/New_York')
    assert next_due(trigger,datetime(2026,3,8,0,tzinfo=utc))==datetime(2026,3,9,6,30,tzinfo=utc)
    folded=Trigger(kind='calendar',time='01:30',timezone='America/New_York')
    assert next_due(folded,datetime(2026,11,1,5,31,tzinfo=utc))==datetime(2026,11,2,6,30,tzinfo=utc)
    weekly=Trigger(kind='calendar',weekdays=[0],time='08:00')
    assert next_due(weekly,datetime(2026,9,8,tzinfo=utc))==datetime(2026,9,14,0,tzinfo=utc)
    assert advance_due(Trigger(kind='interval',interval_seconds=60),'2026-09-08T00:00:00+00:00',datetime(2026,9,8,0,3,7,tzinfo=utc))==datetime(2026,9,8,0,4,tzinfo=utc)


def test_large_batch_waits_for_all_segments_and_sends_one_summary(context):
    store,rules,user,rule,now=activated(context,{'kind':'interval','interval_seconds':60})
    acquire(context,[f'item-{i}' for i in range(45)],now)
    when=now+timedelta(seconds=61)
    assert len(evaluate_pending(store,rules.targets,now=when))==1
    token=store.test_machine_token
    task=claim_work(store,rules.targets,token,now=when)['task']
    assert task['stage']=='extract' and len(task['input'])<=20
    assert submit_result(store,rules.targets,token,task['claim_id'],task['claim_token'],answer(task),now=when)['status']=='pending'
    assert dispatch_pending(store,rules.targets,lambda *_:pytest.fail('partial batch sent'))==[]
    store.close()
    judge_all(context,when)
    runs=rules.runs(user['id'],rule['id'])['items']
    assert len(runs)==1 and runs[0]['result']['summary']=='Combined conclusion'
    assert runs[0]['progress']=={'completed':4,'total':4}
    calls=[]
    assert dispatch_pending(store,rules.targets,lambda *_:(calls.append(1) or ACK))==['sent']
    assert dispatch_pending(store,rules.targets,lambda *_:pytest.fail('duplicate'))==[]
    assert calls==[1]


def test_runtime_model_failure_blocks_repeated_calls_until_refresh(context):
    store,rules,user,rule,now=activated(context,{'kind':'each'})
    acquire(context,['item'],now)
    evaluate_pending(store,rules.targets,now=now)
    token=store.test_machine_token
    task=claim_work(store,rules.targets,token,now=now)['task']
    result=submit_result(store,rules.targets,token,task['claim_id'],task['claim_token'],{'error':'isolated_completion_failed'},now=now)
    assert result['status']=='pending'
    machine=authenticate(store,token)
    sync_catalog(store,machine,Capabilities(protocol_version=2,execution_mode='full',models=[{'id':'test/model','name':'Test'}]),now+timedelta(minutes=10))
    assert catalog(store,machine['binding_id'],now+timedelta(minutes=10))['models']==[]
    assert claim_work(store,rules.targets,token,now=now+timedelta(minutes=10))['task'] is None
    assert store.connect().execute('SELECT count(*) FROM information_claims').fetchone()[0]==1


def test_model_only_edit_reapproves_original_queue_without_historical_replay(context):
    store,rules,user,rule,now=activated(context,{'kind':'each'})
    acquire(context,['item'],now)
    evaluate_pending(store,rules.targets,now=now)
    config=RuleConfig.model_validate(rules.get(user['id'],rule['id'])['config'])
    config.model.thinking='low'
    changed=rules.save(user['id'],config,rule_id=rule['id'],expected_version=1)
    assert changed['state']=='paused'
    assert store.connect().execute('SELECT count(*) FROM information_rule_carry').fetchone()[0]==1
    rules.transition(user['id'],rule['id'],2,'enable')
    rules.transition(user['id'],rule['id'],2,'enable')
    assert store.connect().execute('SELECT count(*) FROM information_runs').fetchone()[0]==2
    assert store.connect().execute("SELECT count(*) FROM information_runs WHERE status='pending'").fetchone()[0]==1
    assert evaluate_pending(store,rules.targets,now=now+timedelta(seconds=1))==[]


def test_paused_lease_is_never_resurrected(context):
    store,rules,user,rule,now=activated(context,{'kind':'each'})
    acquire(context,['item'],now)
    evaluate_pending(store,rules.targets,now=now)
    claim_work(store,rules.targets,store.test_machine_token,now=now)
    rules.transition(user['id'],rule['id'],1,'pause')
    expire_claims(store.connect(),now+timedelta(seconds=181))
    assert rules.runs(user['id'],rule['id'])['items'][0]['status']=='cancelled'


def test_discovery_intersects_host_policy_with_configured_models():
    config={'plugins':{'entries':{'llm-task':{'enabled':True,'llm':{'allowModelOverride':True,'allowedCompletionModels':['a/one']}}}}}
    payload={'models':[{'id':'one','provider':'a','thinkingLevels':[{'id':'low'}]}, {'id':'two','provider':'a'}, {'id':'broken','provider':'a','available':False}]}
    assert project_models(payload,config)==[{'id':'a/one','name':'a/one','thinking_levels':['low']}]
    config['plugins']['entries']['llm-task']['llm']['allowModelOverride']=False
    assert project_models(payload,config)==[]


def test_periodic_batch_cutoff_leaves_later_events_for_next_boundary(context):
    store,rules,user,rule,now=activated(context,{'kind':'interval','interval_seconds':60})
    clock=datetime.fromisoformat(rules.get(user['id'],rule['id'])['next_due'])
    acquire(context,['before'],clock-timedelta(seconds=1))
    acquire(context,['after'],clock+timedelta(seconds=1))
    assert len(evaluate_pending(store,rules.targets,now=clock+timedelta(seconds=10)))==1
    first=rules.runs(user['id'],rule['id'])['items'][0]
    raw=store.connect().execute('SELECT input_json FROM information_runs WHERE id=?',(first['id'],)).fetchone()[0]
    assert [item['article_id'] for item in json.loads(raw)]==['before']
    cursor=rules.row(user,rule['id'])['cursor']
    assert store.connect().execute('SELECT count(*) FROM information_events WHERE id>?',(cursor,)).fetchone()[0]==1
    assert len(evaluate_pending(store,rules.targets,now=clock+timedelta(minutes=4)))==1
    assert rules.get(user['id'],rule['id'])['pending_count']==0


def test_weekly_dst_gap_skips_nonexistent_occurrence():
    weekly=Trigger(kind='calendar',weekdays=[6],time='02:30',timezone='America/New_York')
    assert next_due(weekly,datetime(2026,3,7,tzinfo=timezone.utc))==datetime(2026,3,15,6,30,tzinfo=timezone.utc)


def test_serialized_input_budget_splits_escape_heavy_text_without_loss():
    from src.services.information_automations.batches import content_units, pack, SYSTEM
    text='\x00\n"'*20000
    requirement='r'*16000
    units=content_units([{'article_id':'a','title':'t','text':text,'source_ids':['private-metadata']}],requirement)
    groups=pack(units,requirement)
    assert ''.join(unit['text'] for group in groups for unit in group)==text
    assert all(len(json.dumps(group,ensure_ascii=False))+len(requirement)+len(SYSTEM)+1024<=32000 for group in groups)
    assert all('source_ids' not in unit for unit in units)


def test_notification_text_preserves_complete_links():
    from src.services.information_automations.delivery import notification_text
    payload={'rule_name':'n','summary':'s'*1200,'reason':'r'*600,
             'items':[{'title':'t'*500,'url':'https://example.com/'+str(i)+'x'*300} for i in range(8)]}
    text=notification_text(payload)
    assert len(text)<=4000 and payload['items'][0]['url'] in text
    assert all(line in [item['url'] for item in payload['items']] for line in text.splitlines() if line.startswith('https://'))


def test_model_edit_retains_unbatched_count_buffer_but_skips_paused_arrivals(context):
    store,rules,user,rule,now=activated(context,{'kind':'count','count':3,'max_wait_seconds':None})
    acquire(context,['one','two'],now)
    assert evaluate_pending(store,rules.targets,now=now)==[]
    config=RuleConfig.model_validate(rules.get(user['id'],rule['id'])['config'])
    config.model.thinking='low'
    rules.save(user['id'],config,rule_id=rule['id'],expected_version=1)
    acquire(context,['paused'],now)
    rules.transition(user['id'],rule['id'],2,'enable')
    assert rules.get(user['id'],rule['id'])['pending_count']==2
    acquire(context,['three'],now)
    assert len(evaluate_pending(store,rules.targets,now=now))==1
    row=store.connect().execute('SELECT input_json FROM information_runs').fetchone()
    assert {item['article_id'] for item in json.loads(row[0])}=={'one','two','three'}
    assert evaluate_pending(store,rules.targets,now=now)==[]


def test_maximum_legacy_conditions_survive_conversion_and_allow_bounded_reduction():
    from src.services.information_automations.batches import output_schema, pack
    conditions={key:[str(i).zfill(2)+'x'*254 for i in range(30)] for key in ('all','any','exclude')}
    config=RuleConfig.model_validate({'name':'Legacy','mode':'keyword','conditions':conditions})
    assert len(config.requirement)>16000
    assert all(term in config.requirement for terms in conditions.values() for term in terms)
    schema=output_schema(config.requirement,'extract')
    assert schema['properties']['evidence']['maxItems']==2
    unit={'unit_id':'s'*50,'status':'insufficient','summary':'s'*400,'reason':'r'*200,
          'evidence':[{'article_id':'i'*256,'quote':'q'*200,'note':'n'*100}]*2}
    assert len(pack([unit,unit],config.requirement))==1


def test_subscription_platform_projection_is_user_scoped_and_does_not_return_configuration(context):
    from src.services.subscription_presentation import subscription_platforms
    store,_,_,user,other,_,_,_=context
    identity=store.create_source(workspace_id=user['workspace_id'],scope='workspace',owner_user_id=user['id'],
                                source_type='apify_social',display_name='Tibo',config={'platform':'x','target':'tibo'})
    store.create_subscription(user_id=user['id'],source_id=identity)
    assert subscription_platforms(store,user)[identity]=='x'
    assert identity not in subscription_platforms(store,other)


@pytest.mark.parametrize('error', ['invalid_model_output', 'analysis_timeout', 'analysis_call_failed'])
def test_completion_failure_finishes_without_blocking_model(context, error):
    store,rules,user,rule,now=activated(context,{'kind':'each'})
    acquire(context,['item'],now)
    evaluate_pending(store,rules.targets,now=now)
    token=store.test_machine_token
    task=claim_work(store,rules.targets,token,now=now)['task']
    result=submit_result(store,rules.targets,token,task['claim_id'],task['claim_token'],{'error':error},now=now)
    assert result['status']=='failed'
    assert catalog(store,authenticate(store,token)['binding_id'],now)['models']
    assert rules.runs(user['id'],rule['id'])['items'][0]['reason']==error
