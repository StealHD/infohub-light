"""Versioned reminder drafts and explicit, compare-and-swap user confirmation."""
import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from ...storage.information_unified_schema import ready
from ..agent_connections.service import AgentConnections

from .config import RuleConfig


class RuleError(ValueError):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code, self.status = code, status


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def transport_generation(store, user, target):
    channel = target.get('channel')
    getter = (store.get_workspace_email_transport if channel == 'email' else
              store.get_workspace_telegram_transport if channel == 'telegram' else None)
    current = getter(workspace_id=user['workspace_id']) if getter else None
    return int(current['generation']) if current else 0


@contextmanager
def transaction(store):
    conn = store.connect()
    if conn.in_transaction:
        raise RuntimeError('reminder mutation requires its own transaction')
    conn.execute('BEGIN IMMEDIATE')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def public_rule(row, conn=None):
    result = {**{key: row[key] for key in ('id','version','state','issue','created_at','updated_at','confirmed_at')},
              'config': RuleConfig.model_validate_json(row['config_json']).model_dump()}
    if conn is not None:
        from .execution import matching_events
        from .batches import progress
        config = RuleConfig.model_validate_json(row['config_json'])
        events = matching_events(conn,row,config,datetime.now(timezone.utc)) if row['state']=='active' else []
        due = conn.execute('SELECT next_due FROM information_trigger_state WHERE rule_id=?',(row['id'],)).fetchone()
        result.update(pending_count=len(events),next_due=due['next_due'] if due else None)
        if events and config.trigger.kind == 'count' and config.trigger.max_wait_seconds:
            result['next_due'] = (datetime.fromisoformat(events[0]['created_at']) + timedelta(seconds=config.trigger.max_wait_seconds)).isoformat()
        result['source_names'] = [source['display_name'] for identity in config.source_ids
            if (source := conn.execute('SELECT display_name FROM source_catalog WHERE id=? AND workspace_id=?', (identity,row['workspace_id'])).fetchone())]

        latest = conn.execute('SELECT id,status,notification_status FROM information_runs WHERE rule_id=? ORDER BY created_at DESC,id DESC LIMIT 1',(row['id'],)).fetchone()
        result['latest_run'] = {**dict(latest),**progress(conn,run_id=latest['id'])} if latest else None
    return result


def cancel_unsent(conn, rule_id, reason):
    conn.execute('''UPDATE information_runs SET status=CASE WHEN status IN
        ('pending','judging','quota_wait') THEN 'cancelled' ELSE status END,
        notification_status='cancelled', reason=?, updated_at=? WHERE rule_id=?
        AND (notification_status IN ('pending','quota_wait') OR status IN
        ('pending','judging','quota_wait'))''', (reason, now_iso(), rule_id))


class InformationRules:
    def __init__(self, store, targets):
        self.store, self.targets = store, targets

    def actor(self, user_id, *, write=False):
        if not ready(self.store.connect()):
            raise RuleError('information_migration_required', '请先完成信息提醒数据迁移。', 503)
        user = self.store.get_user(user_id)
        if not user or not user['enabled']:
            raise RuleError('not_authenticated', '登录账号已失效。', 401)
        if write and user['role'] not in {'owner', 'admin', 'member'}:
            raise RuleError('forbidden', '当前账号只允许查看。', 403)
        return user

    def binding(self, user):
        binding = AgentConnections(self.store, None).live(user)
        if not binding:
            raise RuleError('agent_binding_required', '请先验证个人 Agent 接入。')
        return binding

    def row(self, user, rule_id):
        row = self.store.connect().execute('SELECT * FROM information_rules WHERE id=? AND user_id=?',
                                          (rule_id, user['id'])).fetchone()
        if not row:
            raise RuleError('not_found', '提醒不存在。', 404)
        return dict(row)

    def validate_sources(self, user, config):
        visible = {row['source_id'] for row in self.store.list_enabled_user_subscriptions_with_sources(
            workspace_id=user['workspace_id'], user_id=user['id'])}
        if set(config.source_ids) - visible:
            raise RuleError('subscription_required', '请选择本人已启用的订阅。')

    def target(self, user, config, *, require_ready=False):
        if not config.target_id:
            return None
        visible = self.targets.list_public_targets(workspace_id=user['workspace_id'], user_id=user['id'])
        if config.target_id not in {row['id'] for row in visible['targets']}:
            raise RuleError('notification_target_unavailable', '通知服务不可用。')
        target = self.store.get_notification_target(workspace_id=user['workspace_id'], target_id=config.target_id)
        if not target or (require_ready and not self.targets.target_is_available(target)):
            raise RuleError('notification_target_unavailable', '请先验证并启用通知服务。')
        return target

    def list(self, user_id, *, limit=50, offset=0):
        user = self.actor(user_id)
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
            raise RuleError('invalid_pagination', '分页参数无效。', 400)
        rows = self.store.connect().execute('''SELECT * FROM information_rules WHERE user_id=?
            ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?''', (user['id'], limit + 1, offset)).fetchall()
        return {'items': [public_rule(row, self.store.connect()) for row in rows[:limit]], 'has_more': len(rows) > limit,
                'next_offset': offset + limit if len(rows) > limit else None}

    def get(self, user_id, rule_id):
        return public_rule(self.row(self.actor(user_id), rule_id), self.store.connect())

    def runs(self, user_id, rule_id, *, limit=50, offset=0):
        user = self.actor(user_id)
        self.row(user, rule_id)
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
            raise RuleError('invalid_pagination', '分页参数无效。', 400)
        rows = self.store.connect().execute('''SELECT id,version,status,notification_status,reason,
            evidence_json,receipt_json,created_at,updated_at FROM information_runs WHERE rule_id=?
            ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?''', (rule_id, limit + 1, offset)).fetchall()
        items = []
        for row in rows[:limit]:
            item = dict(row)
            item['evidence'] = json.loads(item.pop('evidence_json'))
            item['receipt'] = json.loads(item.pop('receipt_json') or 'null')
            from .batches import progress
            item.update(progress(self.store.connect(), run_id=row['id']))
            items.append(item)
        return {'items': items, 'has_more': len(rows) > limit,
                'next_offset': offset + limit if len(rows) > limit else None}

    def save(self, user_id, config: RuleConfig, *, rule_id=None, expected_version=None):
        with transaction(self.store) as conn:
            user = self.actor(user_id, write=True)
            self.binding(user)
            self.validate_sources(user, config)
            self.target(user, config)
            now, encoded = now_iso(), config.model_dump_json()
            if rule_id:
                row = self.row(user, rule_id)
                if row['version'] != expected_version or row['state'] == 'archived':
                    raise RuleError('rule_version_conflict', '提醒已变化，请刷新后重新编辑。')
                from .model_change import preserve_waiting
                preserve_waiting(conn,row,config)
                version = row['version'] + 1
                state = 'draft' if row['state'] == 'draft' else 'paused'
                conn.execute('''UPDATE information_rules SET version=?,config_json=?,state=?,
                    confirmed_at=NULL,confirmation_id=NULL,issue=NULL,updated_at=? WHERE id=?''', (version, encoded, state, now, rule_id))
                cancel_unsent(conn, rule_id, 'rule_changed')
            else:
                rule_id, version = 'iar_' + uuid.uuid4().hex, 1
                conn.execute('''INSERT INTO information_rules
                    (id,workspace_id,user_id,version,state,config_json,created_at,updated_at)
                    VALUES(?,?,?,1,'draft',?,?,?)''', (rule_id, user['workspace_id'], user_id, encoded, now, now))
            conn.execute('INSERT INTO information_rule_versions VALUES(?,?,?,?)', (rule_id, version, encoded, now))
            return public_rule(self.row(user, rule_id), conn)

    def transition(self, user_id, rule_id, version, action):
        if action not in {'enable', 'pause', 'archive'}:
            raise RuleError('invalid_action', '操作无效。', 400)
        with transaction(self.store) as conn:
            user = self.actor(user_id, write=True)
            row = self.row(user, rule_id)
            if row['version'] != version or row['state'] == 'archived':
                raise RuleError('rule_version_conflict', '提醒已变化，请刷新后重新确认。')
            now = now_iso()
            if action == 'enable':
                config = RuleConfig.model_validate_json(row['config_json'])
                binding = self.binding(user)
                self.validate_sources(user, config)
                target = self.target(user, config, require_ready=True)
                if not config.source_ids or not target or not config.requirement.strip() or not config.model:
                    raise RuleError('incomplete_rule', '请补齐来源、完整要求、模型和通知服务。')
                from .model_catalog import require_model
                require_model(self.store, binding['binding_id'], config.model)
                if row['state'] == 'active':
                    if (row['binding_id'], row['target_generation'], row['target_activation'], row['transport_generation']) != (
                            binding['binding_id'], target['config_generation'], target['activation_generation'], transport_generation(self.store, user, target)):
                        raise RuleError('rule_authorization_changed', '授权已变化，请暂停后重新确认。')
                    return public_rule(row, conn)
                cursor = conn.execute('SELECT COALESCE(MAX(id),0) FROM information_events WHERE user_id=?', (user_id,)).fetchone()[0]
                confirmation_id = 'iaapproval_' + uuid.uuid4().hex
                approval = {'binding_id': binding['binding_id'], 'target_id': target['id'],
                            'target_generation': target['config_generation'], 'target_activation': target['activation_generation'],
                            'transport_generation': transport_generation(self.store, user, target)}
                conn.execute('INSERT INTO information_rule_approvals VALUES(?,?,?,?,?)',
                             (confirmation_id, rule_id, version, json.dumps(approval), now))
                conn.execute('''UPDATE information_rules SET state='active',issue=NULL,binding_id=?,target_generation=?,
                    target_activation=?,transport_generation=?,confirmed_at=?,confirmation_id=?,cursor=?,updated_at=? WHERE id=?''',
                             (binding['binding_id'], target['config_generation'], target['activation_generation'],
                              transport_generation(self.store, user, target), now, confirmation_id, cursor, now, rule_id))
                from .scheduling import next_due
                due = next_due(config.trigger, datetime.fromisoformat(now))
                conn.execute('INSERT OR REPLACE INTO information_trigger_state VALUES(?,?)', (rule_id, due.isoformat() if due else None))
                from .model_change import resume_waiting
                resume_waiting(conn,self.row(user,rule_id),config,now)
            else:
                conn.execute('UPDATE information_rules SET state=?,updated_at=? WHERE id=?',
                             ('paused' if action == 'pause' else 'archived', now, rule_id))
                cancel_unsent(conn, rule_id, 'rule_' + action)
                conn.execute('DELETE FROM information_rule_carry WHERE rule_id=?',(rule_id,))
                conn.execute('DELETE FROM information_event_carry WHERE rule_id=?',(rule_id,))
            return public_rule(self.row(user, rule_id), conn)

    def test(self, user_id, rule_id, version, article_ids):
        user = self.actor(user_id)
        row = self.row(user, rule_id)
        if row['version'] != version:
            raise RuleError('rule_version_conflict', '提醒已变化，请重新测试。')
        if not 1 <= len(article_ids) <= 1000:
            raise RuleError('invalid_test_items', '请选择 1–1000 篇本人文章。', 400)
        config = RuleConfig.model_validate_json(row['config_json'])
        from .semantic_previews import create_preview
        return create_preview(self, user, row, config, article_ids)
