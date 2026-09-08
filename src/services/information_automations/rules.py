"""Versioned reminder drafts and explicit, compare-and-swap user confirmation."""
import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ...storage.information_automation_schema import ready
from ..agent_connections.service import AgentConnections
from ..user_content_store import UserContentStore
from .matching import keyword_match
from .content import evidence_input

Term = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]


class Conditions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    all: list[Term] = Field(default_factory=list, max_length=30)
    any: list[Term] = Field(default_factory=list, max_length=30)
    exclude: list[Term] = Field(default_factory=list, max_length=30)


class RuleConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    mode: Literal['keyword', 'semantic'] = 'keyword'
    source_ids: list[Term] = Field(default_factory=list, max_length=50)
    target_id: Term | None = None
    conditions: Conditions = Field(default_factory=Conditions)
    requirement: str = Field(default='', max_length=16000)


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


def public_rule(row):
    return {**{key: row[key] for key in ('id', 'version', 'state', 'issue', 'created_at', 'updated_at', 'confirmed_at')},
            'config': json.loads(row['config_json'])}


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
        return {'items': [public_rule(row) for row in rows[:limit]], 'has_more': len(rows) > limit,
                'next_offset': offset + limit if len(rows) > limit else None}

    def get(self, user_id, rule_id):
        return public_rule(self.row(self.actor(user_id), rule_id))

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
            return public_rule(self.row(user, rule_id))

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
                if config.mode == 'semantic':
                    from .connector_auth import is_verified
                    if not is_verified(self.store, binding['binding_id']):
                        raise RuleError('semantic_connector_required', '语义提醒需要先配置并验证独立判断服务。')
                self.validate_sources(user, config)
                target = self.target(user, config, require_ready=True)
                valid = bool(config.conditions.all or config.conditions.any) if config.mode == 'keyword' else bool(config.requirement.strip())
                if not config.source_ids or not target or not valid:
                    raise RuleError('incomplete_rule', '请补齐来源、判断条件和通知服务。')
                if row['state'] == 'active':
                    if (row['binding_id'], row['target_generation'], row['target_activation'], row['transport_generation']) != (
                            binding['binding_id'], target['config_generation'], target['activation_generation'], transport_generation(self.store, user, target)):
                        raise RuleError('rule_authorization_changed', '授权已变化，请暂停后重新确认。')
                    return public_rule(row)
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
            else:
                conn.execute('UPDATE information_rules SET state=?,updated_at=? WHERE id=?',
                             ('paused' if action == 'pause' else 'archived', now, rule_id))
                cancel_unsent(conn, rule_id, 'rule_' + action)
            return public_rule(self.row(user, rule_id))

    def test(self, user_id, rule_id, version, article_ids):
        user = self.actor(user_id)
        row = self.row(user, rule_id)
        if row['version'] != version:
            raise RuleError('rule_version_conflict', '提醒已变化，请重新测试。')
        if not 1 <= len(article_ids) <= 20:
            raise RuleError('invalid_test_items', '请选择 1–20 篇本人文章。', 400)
        config = RuleConfig.model_validate_json(row['config_json'])
        if config.mode != 'keyword':
            from .semantic_previews import create_preview
            return create_preview(self, user, row, config, article_ids)
        results = []
        remaining = 32000
        for article_id in dict.fromkeys(article_ids):
            item = UserContentStore(self.store).get_item(workspace_id=user['workspace_id'], user_id=user_id, article_id=article_id)
            if not item:
                raise RuleError('not_found', '测试文章不存在。', 404)
            evidence = evidence_input(item, remaining)
            remaining -= len(evidence['text'])
            matched = keyword_match(evidence['text'], config.conditions.model_dump())
            status = 'insufficient' if evidence['truncated'] else 'matched' if matched else 'not_matched'
            if not set(config.source_ids) & set(evidence['source_ids']):
                status = 'not_matched'
            results.append({'article_id': article_id, 'status': status})
        return {'version': version, 'results': results, 'sends_notification': False, 'advances_cursor': False}
