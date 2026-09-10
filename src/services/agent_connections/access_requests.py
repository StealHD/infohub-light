"""Workspace-scoped request storage, versioned approval and public projections."""
import uuid
from datetime import datetime, timezone
from ...storage.agent_access_schema import ready
from .service import AgentConnections


class AccessError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


class AccessRequests:
    def __init__(self, context):
        self.context, self.store = context, context.store
        self.conn = context.store.connect()

    def require_schema(self):
        if not ready(self.conn):
            raise AccessError('接入申请尚未启用，请管理员完成数据库升级。')

    def latest(self, user):
        if not ready(self.conn):
            return None
        row = self.conn.execute('SELECT * FROM agent_access_requests WHERE user_id=? AND workspace_id=? ORDER BY created_at DESC,id DESC LIMIT 1',
                                (user['id'], user['workspace_id'])).fetchone()
        return dict(row) if row else None

    def get(self, identity, actor):
        self.require_schema()
        row = self.conn.execute('SELECT * FROM agent_access_requests WHERE id=? AND workspace_id=?',
                                (identity, actor['workspace_id'])).fetchone()
        if not row:
            raise AccessError('申请不存在或无权访问。')
        return dict(row)

    def submit(self, user):
        self.require_schema()
        from .cleanup_store import pending
        if pending(self.store, user['id']):
            raise AccessError('OpenClaw 清理尚未完成，暂不能重新申请。')
        if user['role'] != 'member' or not user['enabled']:
            raise AccessError('仅已启用成员可申请接入。')
        if AgentConnections(self.store, self.context.secret_values).live(user):
            raise AccessError('当前账号已有接入，无需重复申请。')
        try:
            self.conn.execute('BEGIN IMMEDIATE')
            if pending(self.store, user['id']):
                raise AccessError('OpenClaw 清理尚未完成，暂不能重新申请。')
            existing = self.latest(user)
            if not existing or existing['state'] not in {'pending', 'approved'}:
                self.conn.execute('INSERT INTO agent_access_requests(id,workspace_id,user_id,state,created_at) VALUES(?,?,?,\'pending\',?)',
                                  (uuid.uuid4().hex, user['workspace_id'], user['id'], now()))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return self.latest(user)

    def decide(self, identity, actor, revision, decision, reason):
        self.require_schema()
        try:
            self.conn.execute('BEGIN IMMEDIATE')
            row = self.get(identity, actor)
            self.authorize(actor, row)
            changed = self.conn.execute('''UPDATE agent_access_requests SET state=?,reviewer_id=?,reviewed_at=?,
                reason=?,phase=?,revision=revision+1 WHERE id=? AND state='pending' AND revision=?''',
                (decision, actor['id'], now(), reason if decision == 'rejected' else None,
                 'queued' if decision == 'approved' else None, identity, revision)).rowcount
            if changed != 1:
                raise AccessError('申请已被处理，请刷新后查看。')
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return self.get(identity, actor)

    def authorize(self, actor, row):
        admin = self.store.get_user(actor['id'])
        target = self.store.get_user(row['user_id'])
        if (not admin or not admin['enabled'] or admin['role'] not in {'owner', 'admin'}
                or not target or not target['enabled'] or target['role'] != 'member'
                or admin['workspace_id'] != row['workspace_id'] or target['workspace_id'] != row['workspace_id']):
            raise AccessError('审批权限或成员状态已变化，未执行接入。')
        return target

    def listing(self, actor, group, search, page):
        self.require_schema()
        states = {'pending': ['pending'], 'processing': ['approved'], 'processed': ['ready', 'rejected']}[group]
        where = 'r.workspace_id=? AND r.state IN (' + ','.join('?' for _ in states) + ') AND (instr(lower(u.username),lower(?))>0 OR instr(lower(coalesce(u.display_name,\'\')),lower(?))>0)'
        from ...storage.agent_cleanup_schema import ready as cleanup_ready
        if cleanup_ready(self.conn):
            cleaning = "EXISTS(SELECT 1 FROM agent_cleanup c WHERE c.binding_id=r.binding_id AND c.phase!='complete')"
            state_filter = 'r.state IN (' + ','.join('?' for _ in states) + ')'
            if group == 'processing':
                where = where.replace(state_filter, '(' + state_filter + ' OR ' + cleaning + ')')
            elif group == 'processed':
                where += ' AND NOT ' + cleaning
        args = (actor['workspace_id'], *states, search, search)
        base = ' FROM agent_access_requests r JOIN users u ON u.id=r.user_id WHERE ' + where
        total = self.conn.execute('SELECT count(*)' + base, args).fetchone()[0]
        rows = self.conn.execute('SELECT r.*,u.username,u.display_name,u.role' + base +
                                ' ORDER BY r.created_at DESC,r.id DESC LIMIT 20 OFFSET ?', (*args, (page-1)*20)).fetchall()
        count = self.conn.execute("SELECT count(*) FROM agent_access_requests WHERE workspace_id=? AND state='pending'", (actor['workspace_id'],)).fetchone()[0]
        return {'items': [dict(row) for row in rows], 'total': total, 'pending_count': count}
