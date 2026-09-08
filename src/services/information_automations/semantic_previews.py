"""Preview creation uses the same durable batch engine without production cursors."""
import json
import uuid
from datetime import datetime, timezone
from .rules import RuleError, transaction
from .content import evidence_input
from .batches import create_batch, progress
from .model_catalog import require_model
from ..user_content_store import UserContentStore


def get_preview(rules, user_id, rule_id, preview_id):
    rules.row(rules.actor(user_id), rule_id)
    row = rules.store.connect().execute('SELECT * FROM information_previews WHERE id=? AND user_id=? AND rule_id=?',
                                       (preview_id, user_id, rule_id)).fetchone()
    if not row:
        raise RuleError('not_found', '测试不存在。', 404)
    return {'preview_id': row['id'], 'version': row['version'], 'status': row['status'], 'reason': row['reason'],
            'results': json.loads(row['results_json']), 'sends_notification': False, 'advances_cursor': False,
            **progress(rules.store.connect(), preview_id=preview_id)}


def create_preview(rules, user, row, config, article_ids):
    binding = rules.binding(user)
    require_model(rules.store, binding['binding_id'], config.model)
    if not config.requirement.strip():
        raise RuleError('incomplete_rule', '请填写完整判断要求。')
    inputs = []
    for article_id in dict.fromkeys(article_ids):
        stored = UserContentStore(rules.store).get_item(workspace_id=user['workspace_id'], user_id=user['id'], article_id=article_id)
        if not stored:
            raise RuleError('not_found', '测试文章不存在。', 404)
        item = evidence_input(stored, 1000000)
        if not set(config.source_ids) & set(item['source_ids']):
            raise RuleError('test_source_mismatch', '测试文章不属于所选来源。', 400)
        inputs.append(item)
    now, identity = datetime.now(timezone.utc).isoformat(), 'iapreview_' + uuid.uuid4().hex
    with transaction(rules.store) as conn:
        current = rules.row(rules.actor(user['id'], write=True), row['id'])
        if current['version'] != row['version'] or current['state'] == 'archived':
            raise RuleError('rule_version_conflict', '请刷新后重新测试。')
        rules.validate_sources(user, config)
        pending = conn.execute("SELECT count(*) FROM information_previews WHERE user_id=? AND status IN ('pending','judging','quota_wait')", (user['id'],)).fetchone()[0]
        if pending >= 5:
            raise RuleError('preview_limit', '请等待已有测试完成。', 429)
        conn.execute('''INSERT INTO information_previews
            (id,rule_id,user_id,version,binding_id,input_json,requirement,status,ready_at,created_at)
            VALUES(?,?,?,?,?,?,?,'pending',?,?)''',
            (identity,row['id'],user['id'],row['version'],binding['binding_id'],json.dumps(inputs,ensure_ascii=False),config.requirement,now,now))
        create_batch(conn, config, inputs, now, preview_id=identity)
    return get_preview(rules, user['id'], row['id'], identity)
