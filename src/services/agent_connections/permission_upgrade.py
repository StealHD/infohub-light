"""Idempotent upgrade of existing personal bindings without rotating their credentials."""
import asyncio
import json
from ..operation_log import safe_emit_operation_event
from .manifest import USER_TOOLS, canonical, receipt, validate_manifest
from .service import AgentConnections
from .host_dispatch import ManagedHost, installation_digest
from .managed_host import host_lock


async def upgrade(context, user):
    connections = AgentConnections(context.store, context.secret_values)
    host = ManagedHost(context)
    with host_lock(host.root):
        if not connections.live(user):
            return
        from .cleanup_store import pending
        if pending(context.store, user['id']):
            return
        original, token = connections.export(user['id'])
        if original['version'] == 3:
            return
        manifest = validate_manifest({**original, 'version': 3, 'skills': original.get('skills', []), 'tools': list(USER_TOOLS)})
        config = await host.install(manifest, token)
        if not connections.live(user):
            raise ValueError('Binding revoked during permission upgrade')
        conn = context.store.connect()
        changed = conn.execute("UPDATE agent_connections SET manifest_json=? WHERE user_id=? AND state='active' AND manifest_json=?",
                               (canonical(manifest), user['id'], canonical(original))).rowcount
        conn.commit()
        if changed != 1:
            raise ValueError('Binding changed during permission upgrade')
        connections.activate(user['id'], receipt(manifest, token, installation_digest(config)))
        safe_emit_operation_event(category='agent', action='mcp_permission_upgrade', outcome='succeeded', counts={'tools': len(USER_TOOLS)})


async def upgrade_existing(context):
    connections = AgentConnections(context.store, context.secret_values)
    if not connections.schema_ready():
        return
    rows = context.store.connect().execute("SELECT user_id,manifest_json FROM agent_connections WHERE state='active'").fetchall()
    for row in rows:
        if json.loads(row['manifest_json']).get('version') == 3:
            continue
        user = context.store.get_user(row['user_id'])
        try:
            await upgrade(context, user)
        except Exception:
            safe_emit_operation_event(category='agent', action='mcp_permission_upgrade', outcome='failed', error_code='upgrade_pending')


def run_existing(context):
    try:
        asyncio.run(upgrade_existing(context))
    finally:
        context.store.close_current()
