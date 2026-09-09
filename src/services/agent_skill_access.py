"""Workspace-wide Skill authorization with fail-closed Gateway synchronization."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

from ..storage.agent_skill_policy_schema import ready

SKILL_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


class AgentSkillPolicyError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class AgentSkillAccess:
    def __init__(self, store):
        self.store = store

    def _connection(self):
        connection = self.store.connect()
        if not ready(connection):
            raise AgentSkillPolicyError("agent_skill_policy_migration_required", "Run global 41 migration first")
        return connection

    @staticmethod
    def _stored_keys(raw: str) -> list[str]:
        try:
            keys = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as error:
            raise AgentSkillPolicyError("invalid_skill_policy", "Stored Skill policy is invalid") from error
        if (not isinstance(keys, list) or len(keys) > 256
                or any(not isinstance(key, str) or not SKILL_KEY.fullmatch(key) for key in keys)
                or len(set(keys)) != len(keys)):
            raise AgentSkillPolicyError("invalid_skill_policy", "Stored Skill policy is invalid")
        return sorted(keys)

    def policy(self, workspace_id: str) -> dict:
        connection = self._connection()
        row = connection.execute(
            "SELECT * FROM workspace_agent_skill_policies WHERE workspace_id=?", (workspace_id,)
        ).fetchone()
        if not row:
            raise AgentSkillPolicyError("agent_skill_policy_not_found", "Workspace Skill policy is missing")
        result = dict(row)
        result["allowed_skill_keys"] = self._stored_keys(result.pop("allowed_skill_keys_json"))
        result["bindings"] = [dict(item) for item in connection.execute(
            """SELECT binding_id,policy_revision,state,updated_at FROM agent_skill_policy_syncs
               WHERE workspace_id=? ORDER BY binding_id""", (workspace_id,)
        ).fetchall()]
        return result

    def prepare(self, workspace_id: str, *, expected_revision: int, allowed_skill_keys: list[str]) -> dict:
        if not isinstance(allowed_skill_keys, list) or len(allowed_skill_keys) > 256:
            raise AgentSkillPolicyError("invalid_skill_policy", "Skill keys must be unique and no more than 256")
        if any(not isinstance(key, str) or not SKILL_KEY.fullmatch(key) for key in allowed_skill_keys):
            raise AgentSkillPolicyError("invalid_skill_policy", "Skill key is invalid")
        if len(set(allowed_skill_keys)) != len(allowed_skill_keys):
            raise AgentSkillPolicyError("invalid_skill_policy", "Skill keys must be unique and no more than 256")
        keys = sorted(allowed_skill_keys)
        connection = self._connection()
        now = datetime.now(timezone.utc).isoformat()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT revision,allowed_skill_keys_json,sync_attempt_id FROM workspace_agent_skill_policies WHERE workspace_id=?",
                (workspace_id,),
            ).fetchone()
            if not row or row["revision"] != expected_revision:
                raise AgentSkillPolicyError("agent_skill_policy_conflict", "Skill policy changed; refresh and retry")
            if row["sync_attempt_id"]:
                raise AgentSkillPolicyError("agent_skill_policy_conflict", "Skill policy synchronization is already running")
            current = self._stored_keys(row["allowed_skill_keys_json"])
            revision = expected_revision if current == keys else expected_revision + 1
            attempt_id = uuid.uuid4().hex
            connection.execute(
                """UPDATE workspace_agent_skill_policies SET revision=?,allowed_skill_keys_json=?,
                   sync_state='pending',sync_error_code=NULL,sync_attempt_id=?,updated_at=?,synced_at=NULL
                   WHERE workspace_id=?""",
                (revision, json.dumps(keys, separators=(",", ":")), attempt_id, now, workspace_id),
            )
            connection.execute(
                """INSERT INTO agent_skill_policy_syncs(binding_id,workspace_id,policy_revision,state,updated_at)
                   SELECT binding_id,workspace_id,?,'pending',? FROM agent_connections
                   WHERE workspace_id=? AND state<>'revoked'
                   ON CONFLICT(binding_id) DO UPDATE SET policy_revision=excluded.policy_revision,
                   state='pending',updated_at=excluded.updated_at""",
                (revision, now, workspace_id),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        return self.policy(workspace_id)

    def active_bindings(self, workspace_id: str) -> list[dict]:
        return [dict(row) for row in self._connection().execute(
            "SELECT binding_id,agent_id FROM agent_connections WHERE workspace_id=? AND state='active' ORDER BY agent_id",
            (workspace_id,),
        ).fetchall()]

    def finish(self, workspace_id: str, *, revision: int, attempt_id: str, binding_ids: list[str],
               error_code: str | None = None) -> dict:
        connection = self._connection()
        now = datetime.now(timezone.utc).isoformat()
        state = "failed" if error_code else "synced"
        changed = connection.execute(
            """UPDATE workspace_agent_skill_policies SET sync_state=?,sync_error_code=?,
               sync_attempt_id=NULL,synced_at=?,updated_at=?
               WHERE workspace_id=? AND revision=? AND sync_attempt_id=?""",
            (state, error_code, None if error_code else now, now, workspace_id, revision, attempt_id),
        ).rowcount
        if changed != 1:
            connection.rollback()
            raise AgentSkillPolicyError("agent_skill_policy_conflict", "Skill policy synchronization changed")
        if binding_ids:
            placeholders = ",".join("?" for _ in binding_ids)
            connection.execute(
                f"""UPDATE agent_skill_policy_syncs SET state=?,updated_at=?
                    WHERE workspace_id=? AND policy_revision=? AND binding_id IN ({placeholders})""",
                (state, now, workspace_id, revision, *binding_ids),
            )
        connection.commit()
        return self.policy(workspace_id)

    def chat_ready(self, workspace_id: str, binding_id: str) -> bool:
        try:
            policy = self.policy(workspace_id)
        except AgentSkillPolicyError:
            return False
        return policy["sync_state"] == "synced" and any(
            item["binding_id"] == binding_id and item["policy_revision"] == policy["revision"]
            and item["state"] == "synced" for item in policy["bindings"]
        )

    def mark_binding_synced(self, workspace_id: str, binding_id: str, allowed_skill_keys: list[str], *, commit=True):
        policy = self.policy(workspace_id)
        if sorted(allowed_skill_keys) != sorted(policy["allowed_skill_keys"]):
            raise AgentSkillPolicyError("agent_skill_policy_conflict", "Binding uses an older Skill policy")
        connection = self._connection()
        now = datetime.now(timezone.utc).isoformat()
        changed = connection.execute(
            """UPDATE agent_skill_policy_syncs SET state='synced',updated_at=?
               WHERE binding_id=? AND workspace_id=? AND policy_revision=?""",
            (now, binding_id, workspace_id, policy["revision"]),
        ).rowcount
        remaining = connection.execute(
            """SELECT 1 FROM agent_skill_policy_syncs s JOIN agent_connections a USING(binding_id)
               WHERE s.workspace_id=? AND s.policy_revision=? AND a.state='active' AND s.state<>'synced' LIMIT 1""",
            (workspace_id, policy["revision"]),
        ).fetchone()
        if not remaining and not policy.get("sync_attempt_id"):
            connection.execute(
                """UPDATE workspace_agent_skill_policies SET sync_state='synced',sync_error_code=NULL,
                   synced_at=?,updated_at=? WHERE workspace_id=? AND revision=?""",
                (now, now, workspace_id, policy["revision"]),
            )
        if changed != 1:
            connection.rollback()
            raise AgentSkillPolicyError("agent_skill_policy_conflict", "Binding Skill policy changed")
        if commit:
            connection.commit()
