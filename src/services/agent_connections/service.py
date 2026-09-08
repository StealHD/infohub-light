"""Service-owned identities. Browser callers cannot provision or choose an Agent."""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from ...storage.agent_connection_schema import migration_marker_exists, schema_shapes_valid
from .manifest import READ_TOOLS, canonical, validate_manifest, validate_receipt


class BindingError(ValueError):
    pass


class AgentConnections:
    def __init__(self, store, secrets):
        self.store, self.secrets = store, secrets

    def schema_ready(self):
        return migration_marker_exists(self.store.connect()) and schema_shapes_valid(self.store.connect())

    def row(self, user_id):
        if not self.schema_ready():
            return None
        row = self.store.connect().execute('SELECT * FROM agent_connections WHERE user_id=?', (user_id,)).fetchone()
        return dict(row) if row else None

    def live(self, user):
        row = self.row(user['id'])
        if not row or row['state'] != 'active' or row['workspace_id'] != user['workspace_id']:
            return None
        principal = self.store.get_active_agent_delegation_principal(row['delegation_id'])
        if (not principal or principal['user_id'] != user['id']
                or principal['workspace_id'] != user['workspace_id']
                or principal['scopes'] != ['inteliscope:read']):
            return None
        return row

    def status(self, user):
        row = self.row(user['id'])
        active = self.live(user) if row else None
        state = ('migration_required' if not self.schema_ready() else 'unconfigured' if not row
                 else 'revoked' if row['state'] == 'revoked' else 'ready' if active
                 else 'pending_verification' if row['state'] == 'pending' else 'invalid')
        return {'state': state, 'agent_id': row['agent_id'] if row else None,
                'delegation_id': row['delegation_id'] if row else None,
                'verified_at': row['verified_at'] if row else None,
                'verification': {'deployment': bool(active), 'chat': False, 'own_content': bool(active),
                                 'information_automations': False, 'notifications': False},
                'can_connect': bool(active), 'can_chat': bool(active and user['role'] != 'viewer')}

    def prepare(self, user_id, mcp_url):
        if not self.schema_ready():
            raise BindingError('Run the explicit global 37 migration first')
        user = self.store.get_user(user_id)
        if not user or not user['enabled']:
            raise BindingError('Enabled user required')
        conn = self.store.connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            if self.row(user_id):
                raise BindingError('Revoke and retire the existing binding before provisioning again')
            binding_id = uuid.uuid4().hex
            delegation, token = self.store.create_agent_delegation(
                workspace_id=user['workspace_id'], user_id=user_id, name='Personal Agent ' + binding_id[:8])
            manifest = validate_manifest({
                'version': 1, 'binding_id': binding_id, 'user_id': user_id, 'workspace_id': user['workspace_id'],
                'agent_id': 'ih-' + binding_id, 'mcp_server': 'ih_' + binding_id[:24],
                'secret_ref': 'INTELISCOPE_MCP_' + binding_id.upper(), 'mcp_url': mcp_url,
                'delegation_id': delegation['id'], 'token_sha256': hashlib.sha256(token.encode()).hexdigest(),
                'tools': list(READ_TOOLS),
            })
            self.secrets.set(manifest['secret_ref'], token)
            conn.execute('''INSERT INTO agent_connections VALUES(?,?,?,?,?,?,?,?, 'pending',NULL,?)''',
                         (user_id, user['workspace_id'], binding_id, manifest['agent_id'], manifest['mcp_server'],
                          manifest['secret_ref'], delegation['id'], canonical(manifest),
                          datetime.now(timezone.utc).isoformat()))
            conn.commit()
        except Exception:
            conn.rollback()
            # An orphaned secret has no delegation authority and can be safely removed by the operator.
            raise
        return manifest

    def export(self, user_id):
        row = self.row(user_id)
        if not row or row['state'] == 'revoked':
            raise BindingError('Provision a binding first')
        manifest = validate_manifest(json.loads(row['manifest_json']))
        token = self.secrets.read().get(row['secret_ref'], '')
        if hashlib.sha256(token.encode()).hexdigest() != manifest['token_sha256']:
            raise BindingError('Binding secret missing or changed; reprovision required')
        return manifest, token

    def activate(self, user_id, proof):
        manifest, token = self.export(user_id)
        validate_receipt(manifest, token, proof)
        principal = self.store.get_active_agent_delegation_principal(manifest['delegation_id'])
        if not principal or principal['user_id'] != user_id or principal['scopes'] != ['inteliscope:read']:
            raise BindingError('Delegation invalid')
        changed = self.store.connect().execute("UPDATE agent_connections SET state='active',verified_at=? WHERE user_id=? AND binding_id=? AND state!='revoked'",
                                     (proof['verified_at'], user_id, manifest['binding_id'])).rowcount
        self.store.connect().commit()
        if changed != 1:
            raise BindingError('Binding changed or was revoked during activation')

    def revoke(self, user_id):
        row = self.row(user_id)
        if row:
            # Revoking the bearer first closes MCP access even if later metadata persistence fails.
            if row['delegation_id']:
                self.store.revoke_agent_delegation(user_id, row['delegation_id'], reason='agent_binding_revoked')
            self.store.connect().execute("UPDATE agent_connections SET state='revoked' WHERE user_id=?", (user_id,))
            self.store.connect().commit()
            self.secrets.delete(row['secret_ref'])

    def retire(self, user_id):
        """Operator-only reset. Old Agent IDs and ownership history are never reassigned."""
        self.revoke(user_id)
        self.store.connect().execute("DELETE FROM agent_connections WHERE user_id=? AND state='revoked'", (user_id,))
        self.store.connect().commit()
