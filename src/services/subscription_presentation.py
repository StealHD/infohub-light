"""Public platform labels for subscribed sources; source configuration never leaves this projection."""
import json


def subscription_platforms(store, user):
    conn = store.connect()
    routes = {}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='actor_routes_v2'").fetchone():
        routes = {row['route_id']: row['platform'] for row in conn.execute(
            'SELECT route_id,platform FROM actor_routes_v2 WHERE workspace_id=?', (user['workspace_id'],))}
    rows = conn.execute('''SELECT sc.id,sc.type,sc.config_json FROM source_catalog sc
        JOIN user_subscriptions us ON us.source_id=sc.id WHERE us.user_id=? AND sc.workspace_id=?''',
        (user['id'],user['workspace_id']))
    result = {}
    for row in rows:
        config = json.loads(row['config_json'])
        platform = routes.get(config.get('profile_id')) or config.get('platform') if row['type']=='apify_social' else row['type']
        result[row['id']] = platform if isinstance(platform,str) and platform in {
            'x','twitter','youtube','instagram','rss','github','reddit','telegram','telegram_channel','hackernews','openbb','ossinsight'
        } else row['type']
    return result
