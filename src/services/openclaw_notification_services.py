"""Admin-owned OpenClaw destinations for information automations."""

import hashlib
import re
import uuid
from datetime import datetime, timezone

from ..storage.notification_extension_schema import ready
from .notification_telegram_transport import normalize_telegram_message_thread_id
from .openclaw_notification_transport import OpenClawDeliveryError, OpenClawNotificationGateway
from .secret_store import SecretStore


class OpenClawServiceError(ValueError):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.status = code, status


def _now():
    return datetime.now(timezone.utc).isoformat()


def _public(row, *, available=False, destination_ready=False, usage=0):
    result = {'id': row['id'], 'name': row['name'], 'scope': 'shared', 'channel': 'openclaw',
              'openclaw_channel': row['channel_id'], 'openclaw_account': row['account_id'],
              'configured': destination_ready, 'enabled': bool(row['enabled']), 'available': bool(available),
              'transport_ready': destination_ready, 'can_validate': True,
              'last_test_status': row['last_test_status'], 'config_generation': row['config_generation'],
              'activation_generation': row['activation_generation'],
              'telegram_topic_configured': row['message_thread_id'] is not None,
              'legacy_private': False, 'can_edit': True, 'can_test': True, 'can_enable': True,
              'enabled_at': row['last_tested_at'] if row['enabled'] else None,
              'last_tested_at': row['last_tested_at'], 'last_test_error_code': None,
              'updated_at': row['updated_at'],
              'usage': {'user_binding_count': usage, 'alert_binding_count': 0,
                        'preferred_active_delivery_count': 0, 'alert_active_delivery_count': 0}}
    return result


class OpenClawNotificationServices:
    def __init__(self, store, data_dir, gateway=None):
        self.store = store
        self.secrets = SecretStore(data_dir)
        self.gateway = gateway or OpenClawNotificationGateway(self.secrets, data_dir)

    def _ready(self):
        if not ready(self.store.connect()):
            raise OpenClawServiceError('notification_migration_required', '请先完成 global 47 迁移。', 503)

    def catalog(self):
        try:
            return self.gateway.catalog()
        except OpenClawDeliveryError as error:
            raise OpenClawServiceError(error.code, 'OpenClaw 渠道目录不可用。', 503) from error

    def row(self, workspace_id, service_id):
        self._ready()
        row = self.store.connect().execute('SELECT * FROM openclaw_notification_services WHERE id=? AND workspace_id=? AND archived_at IS NULL',
                                           (service_id, workspace_id)).fetchone()
        return dict(row) if row else None

    def list(self, workspace_id):
        self._ready()
        rows = self.store.connect().execute('SELECT * FROM openclaw_notification_services WHERE workspace_id=? AND archived_at IS NULL ORDER BY name,id',
                                            (workspace_id,)).fetchall()
        result = []
        for row in rows:
            usage = self.store.connect().execute('''SELECT count(*) FROM information_rules
                WHERE workspace_id=? AND state!='archived' AND json_extract(config_json,'$.target_id')=?''',
                (workspace_id, row['id'])).fetchone()[0]
            result.append(_public(row, available=self.available(row),
                                  destination_ready=self.destination_valid(row), usage=usage))
        return result

    def destination_valid(self, row):
        value = self.secrets.read().get(row['destination_env_name'])
        return bool(value and hashlib.sha256(value.encode()).hexdigest() == row['destination_digest'])

    def available(self, row):
        return (bool(row['enabled']) and row['last_test_status'] == 'sent'
                and row['last_test_generation'] == row['config_generation']
                and self.destination_valid(row))

    def _validate(self, *, name, channel, account, destination, topic, require_available=True):
        clean_name = ' '.join(str(name or '').split())
        if not 1 <= len(clean_name) <= 80:
            raise OpenClawServiceError('invalid_name', '通知服务名称应为 1–80 个字符。')
        if not isinstance(channel, str) or not channel or len(channel) > 64 or not isinstance(account, str) or not account or len(account) > 128:
            raise OpenClawServiceError('invalid_channel', '请选择 OpenClaw 渠道和账号。')
        if not isinstance(destination, str) or not 1 <= len(destination.strip()) <= 4096:
            raise OpenClawServiceError('invalid_destination', '请填写收件目标。')
        if re.search(r'[\r\n\x00]', destination):
            raise OpenClawServiceError('invalid_destination', '收件目标只能是单行文本。')
        if topic is not None and channel != 'telegram':
            raise OpenClawServiceError('invalid_topic', '只有 Telegram 渠道支持话题 ID。')
        try:
            topic = normalize_telegram_message_thread_id(topic)
        except ValueError as error:
            raise OpenClawServiceError('invalid_topic', '话题 ID 必须是正整数。') from error
        if require_available and not any(item['channel'] == channel and item['account_id'] == account and item['available'] for item in self.catalog()):
            raise OpenClawServiceError('channel_unavailable', 'OpenClaw 渠道或账号未就绪。', 409)
        return clean_name, destination.strip(), topic

    def create(self, workspace_id, *, name, channel, account, destination, topic=None):
        self._ready()
        name, destination, topic = self._validate(name=name, channel=channel, account=account,
                                                   destination=destination, topic=topic)
        if self.store.connect().execute('''SELECT 1 FROM openclaw_notification_services
            WHERE workspace_id=? AND name_key=?''', (workspace_id, name.casefold())).fetchone():
            raise OpenClawServiceError('name_conflict', '通知服务名称已存在。', 409)
        identity = 'ocn_' + uuid.uuid4().hex
        env_name = 'HORIZON_OPENCLAW_NOTIFY_' + hashlib.sha256(identity.encode()).hexdigest()[:24].upper()
        digest = hashlib.sha256(destination.encode()).hexdigest()
        now = _now()
        conn = self.store.connect()
        self.secrets.set(env_name, destination)
        try:
            conn.execute('''INSERT INTO openclaw_notification_services
                (id,workspace_id,name,name_key,channel_id,account_id,destination_env_name,destination_digest,
                 message_thread_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                (identity, workspace_id, name, name.casefold(), channel, account, env_name, digest, topic, now, now))
            conn.commit()
        except Exception:
            conn.rollback()
            self.secrets.delete(env_name)
            raise
        return self.row(workspace_id, identity)

    def update(self, workspace_id, service_id, *, name=None, channel=None, account=None,
               destination=None, topic=..., enabled=None):
        row = self.row(workspace_id, service_id)
        if not row:
            raise OpenClawServiceError('service_not_found', '通知服务不存在。', 404)
        next_name = name if name is not None else row['name']
        next_channel = channel if channel is not None else row['channel_id']
        next_account = account if account is not None else row['account_id']
        next_destination = destination if destination is not None else self.secrets.read().get(row['destination_env_name'])
        next_topic = row['message_thread_id'] if topic is ... else topic
        destination_change = destination is not None and destination.strip() != self.secrets.read().get(row['destination_env_name'])
        configuration_change = (next_channel != row['channel_id'] or next_account != row['account_id']
                                or destination_change or next_topic != row['message_thread_id'])
        next_name, next_destination, next_topic = self._validate(name=next_name, channel=next_channel,
            account=next_account, destination=next_destination, topic=next_topic,
            require_available=configuration_change or enabled is True)
        changed = (next_channel, next_account, next_destination, next_topic) != (
            row['channel_id'], row['account_id'], self.secrets.read().get(row['destination_env_name']), row['message_thread_id'])
        previous = self.secrets.read().get(row['destination_env_name'])
        if destination is not None:
            self.secrets.set(row['destination_env_name'], next_destination)
        conn = self.store.connect()
        try:
            conn.execute('''UPDATE openclaw_notification_services SET name=?,name_key=?,channel_id=?,account_id=?,
                destination_digest=?,message_thread_id=?,enabled=?,config_generation=?,last_test_status=?,
                last_test_generation=?,updated_at=? WHERE id=? AND workspace_id=?''',
                (next_name, next_name.casefold(), next_channel, next_account,
                 hashlib.sha256(next_destination.encode()).hexdigest(), next_topic,
                 0 if changed else int(enabled) if enabled is not None else row['enabled'],
                 row['config_generation'] + int(changed), None if changed else row['last_test_status'],
                 None if changed else row['last_test_generation'], _now(), service_id, workspace_id))
            conn.commit()
        except Exception:
            conn.rollback()
            if destination is not None:
                self.secrets.replace_many({row['destination_env_name']: previous})
            raise
        return self.row(workspace_id, service_id)

    def archive(self, workspace_id, service_id):
        row = self.row(workspace_id, service_id)
        if not row:
            raise OpenClawServiceError('service_not_found', '通知服务不存在。', 404)
        if self.store.connect().execute('''SELECT 1 FROM information_rules WHERE workspace_id=? AND
            state!='archived' AND json_extract(config_json,'$.target_id')=? LIMIT 1''',
            (workspace_id, service_id)).fetchone():
            raise OpenClawServiceError('service_in_use', '请先从自动化任务中移除该服务。', 409)
        self.store.connect().execute('UPDATE openclaw_notification_services SET enabled=0,archived_at=?,updated_at=? WHERE id=?',
                                     (_now(), _now(), service_id))
        self.store.connect().commit()

    def send(self, row, message, idempotency_key):
        try:
            accounts = self.gateway.catalog()
        except OpenClawDeliveryError as error:
            raise OpenClawDeliveryError(error.code) from error
        if not any(item['channel'] == row['channel_id'] and item['account_id'] == row['account_id'] and item['available']
                   for item in accounts):
            raise OpenClawDeliveryError('channel_unavailable')
        destination = self.secrets.read().get(row['destination_env_name'])
        if not destination or hashlib.sha256(destination.encode()).hexdigest() != row['destination_digest']:
            raise OpenClawDeliveryError('destination_unavailable')
        return self.gateway.send(channel=row['channel_id'], account_id=row['account_id'], destination=destination,
                                 message=message, message_thread_id=row['message_thread_id'], idempotency_key=idempotency_key)

    def test_and_enable(self, workspace_id, service_id):
        row = self.row(workspace_id, service_id)
        if not row:
            raise OpenClawServiceError('service_not_found', '通知服务不存在。', 404)
        if not any(item['channel'] == row['channel_id'] and item['account_id'] == row['account_id'] and item['available']
                   for item in self.catalog()):
            raise OpenClawServiceError('channel_unavailable', 'OpenClaw 渠道或账号未就绪。', 409)
        try:
            receipt = self.send(row, 'Inteliscope 通知服务测试', 'service-test-' + uuid.uuid4().hex)
            status = ('sent' if receipt.get('channel') == 'openclaw' and receipt.get('verification') == 'provider_accepted'
                      and str(receipt.get('message_id') or '').strip() else 'unknown')
        except OpenClawDeliveryError as error:
            status = 'unknown' if error.outcome_unknown else 'failed'
        conn = self.store.connect()
        updated = conn.execute('''UPDATE openclaw_notification_services SET enabled=?,last_test_status=?,
            last_test_generation=?,activation_generation=activation_generation+?,last_tested_at=?,updated_at=?
            WHERE id=? AND config_generation=? AND archived_at IS NULL''',
            (int(status == 'sent'), status, row['config_generation'], int(status == 'sent'),
             _now(), _now(), service_id, row['config_generation']))
        conn.commit()
        if not updated.rowcount:
            return {'sent': False, 'status': 'cancelled', 'channel': 'openclaw', 'enabled': False,
                    'target_id': service_id}
        return {'sent': status == 'sent', 'status': status, 'channel': 'openclaw', 'enabled': status == 'sent',
                'target_id': service_id}
