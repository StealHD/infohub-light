"""Acquisition facts share the Feed transaction, including shared-source fanout."""
import json
from datetime import datetime, timezone

from ...storage.information_automation_schema import ready, migration_marker_exists
from ...content_identity import feed_item_fingerprint
from ..user_content_store import UserContentStore


def record_events(connection, *, workspace_id, user_id, items, successful_sources, now=None):
    """Caller owns the transaction. First successful collection establishes a baseline."""
    if not ready(connection):
        if migration_marker_exists(connection):
            raise RuntimeError('information event schema is inconsistent')
        return 0
    if not connection.in_transaction:
        raise RuntimeError('information events must share the Feed transaction')
    now = now or datetime.now(timezone.utc).isoformat()
    known = {row[0] for row in connection.execute(
        'SELECT source_id FROM information_source_baselines WHERE user_id=?', (user_id,))}
    active = set(successful_sources)
    count = 0
    for item in items:
        article_id = item.get('id')
        if not isinstance(article_id, str) or not article_id:
            continue
        sources = set(item.get('source_ids') or [])
        if item.get('source_id'):
            sources.add(item['source_id'])
        sources &= active
        if not sources:
            continue
        new = connection.execute('INSERT OR IGNORE INTO information_seen_items VALUES(?,?)',
                                 (user_id, article_id)).rowcount
        new_identity = connection.execute('INSERT OR IGNORE INTO information_seen_identities VALUES(?,?)',
                                          (user_id, feed_item_fingerprint(item))).rowcount
        eligible = sorted(sources & known)
        if new and new_identity and eligible:
            connection.execute('''INSERT INTO information_events
                (workspace_id,user_id,article_id,source_ids_json,created_at) VALUES(?,?,?,?,?)''',
                               (workspace_id, user_id, article_id, json.dumps(eligible), now))
            count += 1
    connection.executemany('INSERT OR IGNORE INTO information_source_baselines VALUES(?,?,?)',
                           [(user_id, source, now) for source in sorted(active)])
    return count


def record_feed_publication(store, workspace_id, user_id, result, snapshot):
    UserContentStore(store).upsert_captured_items(
        workspace_id=workspace_id, user_id=user_id, items=list(result.items))
    if not ready(store.connect()):
        if migration_marker_exists(store.connect()):
            raise RuntimeError('information event schema is inconsistent')
        return
    # Preserve all provenance from the canonical Feed projection. Failed/cached
    # outcomes cannot establish baselines or turn old content into new events.
    active = {row['source_id'] for row in store.list_enabled_user_subscriptions_with_sources(
        workspace_id=workspace_id, user_id=user_id)}
    succeeded = {outcome.source_id for outcome in result.source_outcomes
                 if outcome.status == 'succeeded' and outcome.capture_status != 'cached'} & active
    record_events(store.connect(), workspace_id=workspace_id, user_id=user_id,
                  items=snapshot.get('payload', {}).get('items', []), successful_sources=succeeded)
