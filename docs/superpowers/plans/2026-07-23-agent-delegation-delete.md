# Revoked Agent Delegation Single-Record Deletion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user explicitly delete one selected revoked Remote MCP assistant connection without touching any other connection or changing revoke semantics.

**Architecture:** Keep the existing delegation DELETE endpoint idempotently revoke-only. Add a separate user-scoped record deletion endpoint backed by a storage method that distinguishes missing, non-revoked, and deleted states; expose it only on revoked cards through a dedicated confirmation flow.

**Tech Stack:** FastAPI, SQLite, Python/pytest, React 19, TypeScript, TanStack Query, Vitest/Testing Library, Docker Compose.

## Global Constraints

- Delete only the selected delegation owned by the current user.
- Require `revoked_at IS NOT NULL`; active and merely expired records are not deletable.
- Preserve `DELETE /api/me/agent-delegations/{id}` as idempotent revocation.
- Do not modify OpenClaw Gateway browser pairing, Remote MCP authentication, token lifetime, access scopes, active limits, subscriptions, Feed, sources, scheduler, or dependencies.
- Do not start the scheduler, fetch sources, send model messages, or call paid providers during verification.
- Rebuild and recreate the local API and Worker from one immutable image after all tests pass, preserving `.env`, `data`, and `logs`.

---

### Task 1: Add a user-scoped revoked-record deletion API

**Files:**
- Modify: `tests/test_agent_delegations.py`
- Modify: `tests/test_agent_delegation_api.py`
- Modify: `src/storage/service_store.py`
- Modify: `src/api/server.py`

**Interfaces:**
- Produces: `ServiceStore.delete_revoked_agent_delegation(user_id: str, delegation_id: str) -> bool | None` where `True` means deleted, `False` means owned but not revoked, and `None` means no user-owned record.
- Produces: `DELETE /api/me/agent-delegations/{delegation_id}/record` returning `{deleted: true}`, `agent_delegation_not_revoked`, or `not_found`.

- [x] **Step 1: Write failing storage tests**

Add a test that creates two delegations, proves an active target returns `False`, revokes only the target, deletes it with `True`, receives `None` on repeat, and still lists the untouched connection. Also prove another user receives `None` for the target.

```python
assert store.delete_revoked_agent_delegation(user["id"], target["id"]) is False
assert store.delete_revoked_agent_delegation(other["id"], target["id"]) is None
assert store.revoke_agent_delegation(user["id"], target["id"]) is True
assert store.delete_revoked_agent_delegation(user["id"], target["id"]) is True
assert store.delete_revoked_agent_delegation(user["id"], target["id"]) is None
assert [row["id"] for row in store.list_agent_delegations(user["id"])] == [kept["id"]]
```

- [x] **Step 2: Write failing API tests**

Extend the existing revoke test and isolation test:

```python
before_revoke = client.delete(f"/api/me/agent-delegations/{connection_id}/record")
assert before_revoke.status_code == 409
assert before_revoke.json()["error"]["code"] == "agent_delegation_not_revoked"

assert client.delete(f"/api/me/agent-delegations/{connection_id}").status_code == 200
deleted = client.delete(f"/api/me/agent-delegations/{connection_id}/record")
assert deleted.json() == {"ok": True, "data": {"deleted": True}}
assert client.get("/api/me/agent-delegations").json()["data"]["connections"] == []
```

For a delegation owned by another user, assert both revoke and record-delete endpoints return 404.

- [x] **Step 3: Run the tests and confirm RED**

Run:

```bash
uv run pytest tests/test_agent_delegations.py tests/test_agent_delegation_api.py -q
```

Expected: failures because the storage method and `/record` route do not exist.

- [x] **Step 4: Implement the storage method**

Add beside `revoke_agent_delegation`:

```python
def delete_revoked_agent_delegation(
    self, user_id: str, delegation_id: str
) -> bool | None:
    conn = self.connect()
    cursor = conn.execute(
        """
        DELETE FROM agent_delegations
        WHERE id = ? AND user_id = ? AND revoked_at IS NOT NULL
        """,
        (delegation_id, user_id),
    )
    if cursor.rowcount:
        conn.commit()
        return True
    owned = conn.execute(
        "SELECT 1 FROM agent_delegations WHERE id = ? AND user_id = ?",
        (delegation_id, user_id),
    ).fetchone()
    return False if owned is not None else None
```

- [x] **Step 5: Implement the explicit API route**

Register the more specific route alongside the existing delegation routes:

```python
@app.delete("/api/me/agent-delegations/{delegation_id}/record")
async def agent_delegations_record_delete(
    delegation_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    deleted = store.delete_revoked_agent_delegation(user["id"], delegation_id)
    if deleted is None:
        raise ApiError("not_found", "connection not found", status_code=404)
    if deleted is False:
        raise ApiError(
            "agent_delegation_not_revoked",
            "connection must be revoked before deletion",
            status_code=409,
        )
    return ok({"deleted": True})
```

- [x] **Step 6: Run targeted backend tests and commit**

Run the command from Step 3 and expect all tests to pass. Commit the four backend/test files with `feat: delete one revoked agent delegation`.

---

### Task 2: Add one-row deletion to the assistant connections UI

**Files:**
- Modify: `frontend/src/api/service.ts`
- Modify: `frontend/src/features/admin-heroui/HeroAgentsPage.tsx`
- Modify: `frontend/src/features/admin-heroui/HeroAgentsPage.test.tsx`

**Interfaces:**
- Consumes: `DELETE /api/me/agent-delegations/{id}/record`.
- Produces: `ServiceApi.deleteAgentDelegationRecord(delegationId: string) -> Promise<{deleted: boolean}>`.
- Produces: a revoked-card `删除 <name>` action and a `删除已吊销连接` confirmation dialog.

- [x] **Step 1: Write a failing UI test**

Add `deleteAgentDelegationRecord` to the test API mock, render one active and one revoked connection, and assert:

```tsx
expect(screen.getByRole('button', { name: '吊销 Active Mac' })).toBeEnabled()
expect(screen.queryByRole('button', { name: '删除 Active Mac' })).not.toBeInTheDocument()
await browser.click(screen.getByRole('button', { name: '删除 Revoked Mac' }))
const dialog = screen.getByRole('dialog', { name: '删除已吊销连接' })
await browser.click(within(dialog).getByRole('button', { name: '确认删除' }))
expect(api.deleteAgentDelegationRecord).toHaveBeenCalledWith('agent-revoked')
expect(api.revokeAgentDelegation).not.toHaveBeenCalledWith('agent-revoked')
```

Assert cancel performs no request and the confirmation copy states that only this record is deleted.

- [x] **Step 2: Run the UI test and confirm RED**

Run:

```bash
cd frontend
npm test -- --run src/features/admin-heroui/HeroAgentsPage.test.tsx
```

Expected: failure because the API method and delete action do not exist.

- [x] **Step 3: Add the API client method**

```ts
deleteAgentDelegationRecord: (delegationId: string) => client.delete<{ deleted: boolean }>(
  `${resource('/api/me/agent-delegations', delegationId)}/record`,
),
```

- [x] **Step 4: Add isolated delete state and mutation**

Add `deleteTarget` state and a mutation separate from `revoke`:

```tsx
const [deleteTarget, setDeleteTarget] = useState<AgentDelegation | null>(null)
const deleteRecord = useMutation({
  mutationFn: () => api.deleteAgentDelegationRecord(deleteTarget!.id),
  onSuccess: () => {
    setDeleteTarget(null)
    setNotice('已删除连接记录。')
    setError('')
    refresh()
  },
  onError: (caught) => setError(caught instanceof ApiError ? caught.message : '删除失败。'),
})
```

Render `删除` only for `status === 'revoked'`; retain the existing revoke control otherwise. Add a locked confirmation modal with copy `只会删除这一条已吊销连接记录，不会影响其他连接。删除后无法恢复。`.

- [x] **Step 5: Run targeted frontend checks and commit**

Run:

```bash
cd frontend
npm test -- --run src/features/admin-heroui/HeroAgentsPage.test.tsx
npm run typecheck
npm run lint
```

Expected: tests pass, TypeScript passes, and lint has zero errors. Commit the three frontend/test files with `feat: delete revoked connection from agents page`.

---

### Task 3: Update contracts, verify, and launch the immutable local image

**Files:**
- Modify: `API_CONTRACT.md`
- Modify: `UI_CONTRACT.md`
- Modify: `DECISION_LOG.md`
- Modify: `WORKLOG.md`

**Interfaces:**
- Records the additive `/record` endpoint, revoked-only invariant, self-scope, confirmation behavior, cascade consequence, verification, image, backup, and rollback point.

- [x] **Step 1: Update authoritative contracts and decision**

Update API contract item 21 to distinguish revoke from record deletion. Add the revoked-only UI action to the assistant-page contract. Append D051 explaining why a separate endpoint preserves revoke idempotency and prevents retry-driven deletion.

- [x] **Step 2: Run complete verification**

Run:

```bash
cd frontend && npm test && npm run typecheck && npm run lint && npm run build
cd .. && python3 scripts/test_gate.py run --mode full
git diff --check
```

Expected: all tests and checks pass; existing lint warnings may remain but lint has zero errors.

- [x] **Step 3: Commit contracts and implementation plan status**

Commit authoritative docs after tests pass with `docs: define revoked connection deletion`.

- [x] **Step 4: Inspect runtime safety and back up SQLite**

Confirm no active jobs or automatic scheduler can trigger paid work, verify `PRAGMA integrity_check`, and create a 0600 SQLite backup under `data/backups/` before recreating containers.

- [x] **Step 5: Build and switch local API/Worker**

Build one immutable image tagged with the implementation commit and explicit version/revision/built-at values. From the primary project root, run Compose with `--no-build --force-recreate horizon-api horizon-worker`, preserving the existing `.env`, `data`, and `logs` bind mounts.

- [x] **Step 6: Verify the running result and record worklog**

Require API and Worker `healthy`, restart count 0, live revision equal to the image revision, ready status true, SQLite integrity `ok`, unchanged feature flags, and a running JavaScript bundle containing `删除已吊销连接`. Append the concise `WORKLOG.md` entry and commit it.
