# OpenClaw Session Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let test, production, new conversations, and model forks connect to one OpenClaw Gateway without global label collisions, while preserving the paired browser device before session initialization can fail.

**Architecture:** A new pure `openclawSession.ts` module owns readable unique labels and exact conflict recognition. `useOpenClawChat.ts` owns one bounded session-create function used by every creation path, and persists exact-scope device credentials immediately after the Gateway handshake before creating or loading a session.

**Tech Stack:** React 19, TypeScript 6, Web Crypto, OpenClaw Gateway WebSocket v4, IndexedDB, Vitest 4, Testing Library, Docker/Buildx.

## Global Constraints

- New labels are `Inteliscope · <window.location.host|browser> · <16 lowercase hex characters>` and never include a user ID, device ID, token, or session key.
- An explicit `GatewayRequestError` with code `INVALID_REQUEST` and message containing `label already in use` gets exactly one retry with a fresh label; all other errors get zero automatic retries.
- Existing stored session keys remain the sole reconnect authority and never call `sessions.create`.
- Do not call `sessions.list`, reuse/rename/archive/delete an existing label, or clean previously paired devices.
- Keep exact `operator.read + operator.write`; never request `operator.admin` or broaden browser scopes.
- Preserve all existing transcript, model-fork, blank-fallback, new-conversation, tool-status, logout, and forget-device semantics.
- Do not change Service API, Remote MCP, subscription writes, database schema, scheduler, dependencies, or deployment topology.
- Automated and real smoke tests must not send model messages, call paid providers, fetch sources, or start the scheduler.

---

### Task 1: Pure session label and conflict primitives

**Files:**
- Create: `frontend/src/features/openclaw/openclawSession.ts`
- Create: `frontend/src/features/openclaw/openclawSession.test.ts`

**Interfaces:**
- Consumes: `GatewayRequestError` from `openclawGateway.ts`, browser-compatible UUID strings, and the current page host supplied by callers.
- Produces: `createOpenClawSessionLabel(siteHost: string, randomId?: string): string` and `isOpenClawSessionLabelConflict(error: unknown): boolean`.

- [ ] **Step 1: Write the failing primitive tests**

Create `openclawSession.test.ts` with these cases:

```ts
import { describe, expect, it } from 'vitest'

import { GatewayRequestError } from './openclawGateway'
import {
  createOpenClawSessionLabel,
  isOpenClawSessionLabelConflict,
} from './openclawSession'

describe('OpenClaw session identity', () => {
  it('creates readable origin-scoped labels with a 64-bit random suffix', () => {
    expect(createOpenClawSessionLabel(
      'RB.JIEFS.TOP',
      '9f6c1d2e-7a3b-4c5d-8e9f-0123456789ab',
    )).toBe('Inteliscope · rb.jiefs.top · 9f6c1d2e7a3b4c5d')
    expect(createOpenClawSessionLabel(
      'localhost:8080',
      '32e741ac-084f-6d19-8a2b-0123456789ab',
    )).toBe('Inteliscope · localhost:8080 · 32e741ac084f6d19')
  })

  it('falls back to browser and never exceeds the Gateway label limit', () => {
    expect(createOpenClawSessionLabel('', '12345678-90ab-cdef-0123-456789abcdef'))
      .toBe('Inteliscope · browser · 1234567890abcdef')
    expect(createOpenClawSessionLabel('x'.repeat(700), '12345678-90ab-cdef-0123-456789abcdef'))
      .toHaveLength(512)
  })

  it('recognizes only the exact Gateway label collision', () => {
    expect(isOpenClawSessionLabelConflict(new GatewayRequestError({
      code: 'INVALID_REQUEST', message: 'label already in use: Inteliscope',
    }))).toBe(true)
    expect(isOpenClawSessionLabelConflict(new GatewayRequestError({
      code: 'INVALID_REQUEST', message: 'invalid label: empty',
    }))).toBe(false)
    expect(isOpenClawSessionLabelConflict(new GatewayRequestError({
      code: 'PERMISSION_DENIED', message: 'missing scope: operator.write',
    }))).toBe(false)
    expect(isOpenClawSessionLabelConflict(new Error('label already in use: Inteliscope'))).toBe(false)
  })
})
```

- [ ] **Step 2: Run the primitive test and verify RED**

Run:

```bash
cd frontend
npm test -- src/features/openclaw/openclawSession.test.ts
```

Expected: FAIL because `./openclawSession` does not exist.

- [ ] **Step 3: Implement the pure primitives**

Create `openclawSession.ts` with:

```ts
import { GatewayRequestError } from './openclawGateway'

const LABEL_PREFIX = 'Inteliscope · '
const RANDOM_HEX_LENGTH = 16
const MAX_LABEL_LENGTH = 512

export function createOpenClawSessionLabel(
  siteHost: string,
  randomId: string = crypto.randomUUID(),
): string {
  const randomHex = randomId.replaceAll('-', '').toLowerCase()
  if (!/^[0-9a-f]{16,}$/u.test(randomHex)) {
    throw new Error('OpenClaw 会话随机标识无效。')
  }
  const suffix = ` · ${randomHex.slice(0, RANDOM_HEX_LENGTH)}`
  const normalizedHost = siteHost.trim().toLowerCase() || 'browser'
  const boundedHost = normalizedHost.slice(0, MAX_LABEL_LENGTH - LABEL_PREFIX.length - suffix.length)
  return `${LABEL_PREFIX}${boundedHost}${suffix}`
}

export function isOpenClawSessionLabelConflict(error: unknown): boolean {
  return error instanceof GatewayRequestError
    && error.code.toUpperCase() === 'INVALID_REQUEST'
    && error.message.toLowerCase().includes('label already in use')
}
```

- [ ] **Step 4: Run focused verification and verify GREEN**

Run:

```bash
cd frontend
npm test -- src/features/openclaw/openclawSession.test.ts
npm run typecheck
```

Expected: all new tests pass and TypeScript exits 0.

- [ ] **Step 5: Commit the primitive module**

```bash
git add frontend/src/features/openclaw/openclawSession.ts frontend/src/features/openclaw/openclawSession.test.ts
git commit -m "test(openclaw): define unique session identity"
```

---

### Task 2: Route every session creation through one bounded entry point

**Files:**
- Modify: `frontend/src/features/openclaw/useOpenClawChat.ts`
- Modify: `frontend/src/features/openclaw/useOpenClawChat.test.ts`

**Interfaces:**
- Consumes: `createOpenClawSessionLabel`, `isOpenClawSessionLabelConflict`, `OpenClawGatewayClient.request`, and existing session-create parameters.
- Produces: internal `createOpenClawSession(client, params): Promise<{ key?: string }>`; all four creation paths use it.

- [ ] **Step 1: Add a failing collision-retry integration test**

Import `GatewayRequestError` as a value, then add this test to `useOpenClawChat.test.ts`:

```ts
it('retries one label collision with a fresh label and keeps all other session parameters', async () => {
  const vault = new OpenClawCredentialVault(new MemoryAdapter())
  await vault.save('user-collision', 'ws://127.0.0.1:18789', {
    identity: { deviceId: 'device-1', publicKey: 'public-1', privateKey: {} as CryptoKey },
    deviceToken: 'device-token', scopes: ['operator.read', 'operator.write'],
  })
  let creates = 0
  const request = vi.fn(async (method: string, params?: Record<string, unknown>) => {
    void params
    if (method === 'sessions.create') {
      creates += 1
      if (creates === 1) throw new GatewayRequestError({
        code: 'INVALID_REQUEST', message: 'label already in use: Inteliscope',
      })
      return { key: 'session-created' }
    }
    if (method === 'tools.effective') return { groups: [] }
    if (method === 'chat.history') return { messages: [] }
    if (method === 'models.list') return models
    if (method === 'agents.list') return agents
    if (method === 'sessions.describe') return session
    throw new Error(`unexpected method ${method}`)
  })
  const clientFactory = vi.fn(() => ({
    connect: vi.fn(async (): Promise<GatewayHello> => ({
      auth: { deviceToken: 'device-token', scopes: ['operator.read', 'operator.write'] },
      snapshot: { sessionDefaults: { defaultAgentId: 'main' } },
    })),
    request,
    close: vi.fn(),
  }))

  const { result } = renderHook(() => useOpenClawChat({
    enabled: true, userId: 'user-collision', defaultGatewayUrl: 'ws://127.0.0.1:18789',
    vault, clientFactory: clientFactory as never,
  }))

  await waitFor(() => expect(result.current.status).toBe('connected'))
  const calls = request.mock.calls.filter(([method]) => method === 'sessions.create')
  expect(calls).toHaveLength(2)
  expect(calls[0][1]).toEqual({
    agentId: 'main',
    label: expect.stringMatching(/^Inteliscope · .+ · [0-9a-f]{16}$/u),
  })
  expect(calls[1][1]).toEqual({
    agentId: 'main',
    label: expect.stringMatching(/^Inteliscope · .+ · [0-9a-f]{16}$/u),
  })
  expect(calls[0][1]?.label).not.toBe(calls[1][1]?.label)
})
```

- [ ] **Step 2: Update existing create-path expectations and add new-conversation coverage**

Replace fixed-label assertions in the model-fork and blank-fallback tests with:

```ts
label: expect.stringMatching(/^Inteliscope · .+ · [0-9a-f]{16}$/u),
```

Add this new-conversation test:

```ts
it('creates a uniquely labelled new conversation without changing runtime semantics', async () => {
  const vault = new OpenClawCredentialVault(new MemoryAdapter())
  await vault.save('user-new', 'ws://127.0.0.1:18789', {
    identity: { deviceId: 'device-1', publicKey: 'public-1', privateKey: {} as CryptoKey },
    deviceToken: 'device-token', scopes: ['operator.read', 'operator.write'], sessionKey: 'session-1',
  })
  const request = vi.fn(async (method: string) => {
    if (method === 'tools.effective') return { groups: [] }
    if (method === 'chat.history') return { messages: [] }
    if (method === 'models.list') return models
    if (method === 'agents.list') return agents
    if (method === 'sessions.describe') return session
    if (method === 'sessions.create') return { key: 'session-2' }
    throw new Error(`unexpected method ${method}`)
  })
  const clientFactory = vi.fn(() => ({
    connect: vi.fn(async (): Promise<GatewayHello> => ({
      auth: { deviceToken: 'device-token', scopes: ['operator.read', 'operator.write'] },
      snapshot: { sessionDefaults: { defaultAgentId: 'main' } },
    })),
    request,
    close: vi.fn(),
  }))
  const { result } = renderHook(() => useOpenClawChat({
    enabled: true, userId: 'user-new', defaultGatewayUrl: 'ws://127.0.0.1:18789',
    vault, clientFactory: clientFactory as never,
  }))

  await waitFor(() => expect(result.current.status).toBe('connected'))
  await act(async () => { await result.current.newConversation() })

  expect(request).toHaveBeenCalledWith('sessions.create', {
    agentId: 'main',
    label: expect.stringMatching(/^Inteliscope · .+ · [0-9a-f]{16}$/u),
  })
  expect(result.current.sessionKey).toBe('session-2')
})
```

- [ ] **Step 3: Run the hook test and verify RED**

Run:

```bash
cd frontend
npm test -- src/features/openclaw/useOpenClawChat.test.ts
```

Expected: the collision test fails after one request and existing assertions report the fixed `Inteliscope` label.

- [ ] **Step 4: Add the unified bounded session-create function**

Import the Task 1 primitives and add this file-level helper before `useOpenClawChat`:

```ts
type OpenClawSessionCreateParams = {
  agentId: string
  parentSessionKey?: string
  fork?: true
  model?: string
}

async function createOpenClawSession(
  client: OpenClawGatewayClient,
  params: OpenClawSessionCreateParams,
): Promise<{ key?: string }> {
  const create = () => client.request<{ key?: string }>('sessions.create', {
    ...params,
    label: createOpenClawSessionLabel(window.location.host),
  })
  try {
    return await create()
  } catch (error) {
    if (!isOpenClawSessionLabelConflict(error)) throw error
    return create()
  }
}
```

Replace all four direct `sessions.create` calls with `createOpenClawSession(client, params)` and remove every application-level `label: 'Inteliscope'`. Preserve `agentId`, `parentSessionKey`, `fork`, and `model` exactly.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```bash
cd frontend
npm test -- src/features/openclaw/openclawSession.test.ts src/features/openclaw/useOpenClawChat.test.ts
npm run typecheck
```

Expected: unique-label, retry, first-create, model-fork, blank-fallback, and new-conversation tests pass; TypeScript exits 0.

- [ ] **Step 6: Commit unified session creation**

```bash
git add frontend/src/features/openclaw/useOpenClawChat.ts frontend/src/features/openclaw/useOpenClawChat.test.ts
git commit -m "fix(openclaw): isolate every browser session"
```

---

### Task 3: Persist pairing before session initialization and classify repeated conflicts

**Files:**
- Modify: `frontend/src/features/openclaw/useOpenClawChat.ts`
- Modify: `frontend/src/features/openclaw/useOpenClawChat.test.ts`

**Interfaces:**
- Consumes: the existing `OpenClawCredentialVault.save` optional `sessionKey`, exact scopes returned by `GatewayHello`, and Task 2 session creator.
- Produces: one paired credential write before first session creation, a second write immediately after a new session key, and `OpenClawSetupIssue.kind = 'session'` for an exhausted label collision.

- [ ] **Step 1: Make credential writes observable in tests**

Extend the test-only `MemoryAdapter` without changing its adapter contract:

```ts
class MemoryAdapter implements OpenClawCredentialAdapter {
  values = new Map<string, StoredOpenClawCredential>()
  puts: StoredOpenClawCredential[] = []
  get = async (key: string) => this.values.get(key) ?? null
  put = async (value: StoredOpenClawCredential) => {
    this.puts.push(value)
    this.values.set(value.id, value)
  }
  delete = async (key: string) => { this.values.delete(key) }
}
```

- [ ] **Step 2: Add the failing pairing-persistence regression test**

Add this test with an initially empty adapter. The first connection exhausts both allowed labels; the second connection succeeds without another bootstrap token:

```ts
it('retains an exact-scope pairing when session setup fails and reuses it on retry', async () => {
  const adapter = new MemoryAdapter()
  const vault = new OpenClawCredentialVault(adapter)
  let creates = 0
  const request = vi.fn(async (method: string) => {
    if (method === 'sessions.create') {
      creates += 1
      if (creates <= 2) throw new GatewayRequestError({
        code: 'INVALID_REQUEST', message: 'label already in use: Inteliscope',
      })
      return { key: 'session-recovered' }
    }
    if (method === 'tools.effective') return { groups: [] }
    if (method === 'chat.history') return { messages: [] }
    if (method === 'models.list') return models
    if (method === 'agents.list') return agents
    if (method === 'sessions.describe') return session
    throw new Error(`unexpected method ${method}`)
  })
  const clientFactory = vi.fn((options: { bootstrapToken?: string; deviceToken?: string }) => ({
    connect: vi.fn(async (): Promise<GatewayHello> => ({
      auth: { deviceToken: 'paired-device-token', scopes: ['operator.read', 'operator.write'] },
      snapshot: { sessionDefaults: { defaultAgentId: 'main' } },
    })),
    request,
    close: vi.fn(),
    options,
  }))
  const { result } = renderHook(() => useOpenClawChat({
    enabled: true, userId: 'user-pairing', defaultGatewayUrl: 'ws://127.0.0.1:18789',
    vault, clientFactory: clientFactory as never,
  }))

  let firstSuccess = true
  await act(async () => { firstSuccess = await result.current.connect('bootstrap-token') })
  expect(firstSuccess).toBe(false)
  expect(result.current.issue).toEqual(expect.objectContaining({
    kind: 'session',
    message: 'OpenClaw 会话名称冲突，请重新连接。',
  }))
  expect(adapter.puts[0]).toMatchObject({
    deviceToken: 'paired-device-token',
    scopes: ['operator.read', 'operator.write'],
  })
  expect(adapter.puts[0].sessionKey).toBeUndefined()

  let secondSuccess = false
  await act(async () => { secondSuccess = await result.current.connect() })
  expect(clientFactory.mock.calls[0][0]).toMatchObject({ bootstrapToken: 'bootstrap-token' })
  expect(clientFactory.mock.calls[1][0]).toMatchObject({
    bootstrapToken: undefined,
    deviceToken: 'paired-device-token',
  })
  expect(secondSuccess).toBe(true)
  expect(adapter.puts.at(-1)).toMatchObject({ sessionKey: 'session-recovered' })
})
```

- [ ] **Step 3: Run the regression and verify RED**

Run:

```bash
cd frontend
npm test -- src/features/openclaw/useOpenClawChat.test.ts
```

Expected: no credential was written after the failed first connection, the second connection requires a token, and the issue kind is not `session`.

- [ ] **Step 4: Reorder credential persistence and add the session issue**

Extend `OpenClawSetupIssue.kind` with `'session'`. In `setupIssue`, before the generic fingerprint branches, add:

```ts
if (isOpenClawSessionLabelConflict(error)) {
  return { kind: 'session', message: 'OpenClaw 会话名称冲突，请重新连接。', requestId }
}
```

After `client.connect()` and the generation check, replace the current post-session credential save with this order:

```ts
const deviceToken = hello.auth?.deviceToken || stored?.deviceToken
if (!deviceToken) throw new Error('OpenClaw 没有返回浏览器设备 token。')
const credential = {
  identity,
  deviceToken,
  scopes: hello.auth?.scopes ?? stored?.scopes ?? [],
}
await vault.save(options.userId, parsed.gatewayUrl, {
  ...credential,
  sessionKey: stored?.sessionKey,
})

const agentId = hello.snapshot?.sessionDefaults?.defaultAgentId
if (!agentId) throw new Error('OpenClaw Gateway 没有返回默认 Agent。')
agentIdRef.current = agentId
let key = stored?.sessionKey
if (!key) {
  const created = await createOpenClawSession(client, { agentId })
  key = created.key
  if (!key) throw new Error('OpenClaw 无法创建 Inteliscope 对话。')
  await vault.save(options.userId, parsed.gatewayUrl, { ...credential, sessionKey: key })
}
```

Keep session state/transcript initialization after the final session key exists. Remove the old single credential save below transcript initialization. An existing stored session key therefore receives one refreshed credential write; a new session receives one device-only write and one session-key write.

- [ ] **Step 5: Run focused verification and verify GREEN**

Run:

```bash
cd frontend
npm test -- src/features/openclaw/openclawSession.test.ts src/features/openclaw/useOpenClawChat.test.ts src/features/openclaw/openclawCredentialVault.test.ts
npm run typecheck
```

Expected: all OpenClaw session and credential tests pass, repeated conflicts surface `kind: session`, and the recovered connection uses the stored device token.

- [ ] **Step 6: Commit staged pairing persistence**

```bash
git add frontend/src/features/openclaw/useOpenClawChat.ts frontend/src/features/openclaw/useOpenClawChat.test.ts
git commit -m "fix(openclaw): retain pairing before session setup"
```

---

### Task 4: Update authority documents and complete the code gate

**Files:**
- Modify: `UI_CONTRACT.md`
- Modify: `DECISION_LOG.md`
- Modify: `WORKLOG.md`
- Modify: `docs/superpowers/plans/2026-07-22-openclaw-session-isolation.md`

**Interfaces:**
- Consumes: the implemented label, retry, credential, and reconnect behavior from Tasks 1–3.
- Produces: authoritative UI behavior, decision D048, compact execution evidence, and a checked implementation plan.

- [ ] **Step 1: Update the UI authority**

Replace the fixed-session sentence in `UI_CONTRACT.md` with language that states:

```md
A tab owns at most one Gateway WebSocket and one dedicated session key. Existing keys reconnect without creating or listing sessions; every new initial, blank, forked, or user-requested conversation uses `Inteliscope · <site host> · <16 hex>` with one fresh-label retry on an explicit collision, so test and production origins can share one Gateway without sharing history.
```

Extend the credential paragraph with:

```md
After exact-scope negotiation the paired identity/device token is saved before session initialization, and a newly created session key is saved immediately before tools/history/runtime loading. The browser never uses `sessions.list` to guess an old label and never automatically deletes, archives, renames, or adopts an existing session.
```

- [ ] **Step 2: Append decision D048**

Append this decision:

```md
### D048 OpenClaw 浏览器会话采用来源化唯一标签与分阶段配对持久化

- 决策日期：2026-07-22
- 当前状态：实现与门禁完成；双环境发布验证待执行
- 决策内容：已有 session key 继续作为按 Inteliscope 用户和规范化 Gateway URL 隔离的唯一重连权威；首次、空白、模型分支和用户新建会话统一使用 `Inteliscope · <site host> · <16 hex>`。只有 OpenClaw 明确返回 `INVALID_REQUEST: label already in use` 时生成新标签重试一次。Gateway 完成精确 `operator.read + operator.write` 协商后，浏览器先保存 identity/device token，再创建会话并立即保存 session key。
- 原因：OpenClaw 2026.7.1 全局要求标签唯一，固定 `Inteliscope` 会让测试与生产以及后续新对话互相阻断；只在建会话成功后保存配对还会让每次失败遗留不可复用设备。来源化随机标签消除共享状态，分阶段保存使配对与会话初始化故障隔离。
- 安全/兼容：不调用 `sessions.list` 猜测旧会话，不跨来源复用、删除、归档、重命名或接管旧会话，不申请 `operator.admin`。旧 session key 与 transcript 保持兼容；本决策细化 D035、D042–D044，不改变 Remote MCP、Service API、数据库、模型选择、消息投影或清理合同。
```

Use D048 because D047 is already reserved by the authorized production Remote MCP/subscription-write activation in the primary worktree.

- [ ] **Step 3: Run complete frontend and project verification**

Run:

```bash
cd frontend
npm test
npm run lint
npm run typecheck
npm run build
cd ..
.venv/bin/python scripts/test_gate.py run --mode full
.venv/bin/python -m json.tool project-defaults.yaml >/dev/null
git diff --check
```

Expected: Vitest, ESLint, TypeScript, production build, all 22 full-gate commands, JSON validation, and whitespace validation pass.

- [ ] **Step 4: Append final implementation evidence and check the plan**

Append one concise `WORKLOG.md` entry with RED→GREEN evidence, focused/full counts, scope/non-goals, and the fact that no session/device was deleted. Change every completed checkbox in this plan from `[ ]` to `[x]`.

- [ ] **Step 5: Commit code authority and evidence**

```bash
git add UI_CONTRACT.md DECISION_LOG.md WORKLOG.md docs/superpowers/plans/2026-07-22-openclaw-session-isolation.md
git commit -m "docs: record OpenClaw session isolation"
```

---

### Task 5: Build one revision and roll it through test and production

**Files:**
- Runtime only: local Docker image/containers and `/opt/inteliscope/releases/<release-id>` on `vps-tokyo`.
- Modify after evidence: `DECISION_LOG.md`, `WORKLOG.md`.

**Interfaces:**
- Consumes: a clean committed branch, the existing local `data/service.db`/`.env`, production `/opt/inteliscope/{data,logs,.env}`, and the current OpenClaw Gateway on `127.0.0.1:13789`.
- Produces: ARM64 localhost and AMD64 production images from the same Git revision, preserved databases, and simultaneous test/production Gateway connections.

- [ ] **Step 1: Run the formal release gate from the clean branch**

```bash
.venv/bin/python scripts/test_gate.py run --mode release
git status --short
```

Expected: all 24 release commands pass and `git status --short` prints nothing.

- [ ] **Step 2: Build and activate the branch image on localhost without replacing data**

Set `revision` from `git rev-parse --short=12 HEAD`, `built_at` from UTC, and image `inteliscope-service:local-${revision}-openclaw-session`. Build from this worktree with `docker build --pull --no-cache` and the three immutable build arguments. Before cutover, query the primary checkout database for `PRAGMA integrity_check`, foreign-key violations, and queued/running jobs; create a timestamped database backup under the primary checkout `data/backups/`. From the primary checkout, recreate only `horizon-api` and `horizon-worker` with explicit `INTELISCOPE_IMAGE`, version, revision, and built-at overrides so its existing `.env`, `data`, and `logs` mounts remain authoritative.

Verify both containers use the same image ID, are healthy with zero restarts, `/api/health/live` returns the new revision, `/api/health/ready` is ready, seven public routes return 200, a protected API returns 401 without auth, database integrity remains `ok`, active jobs remain zero, and no scheduler container is running.

- [ ] **Step 3: Build and transfer the matching AMD64 image**

Use:

```bash
revision="$(git rev-parse --short=12 HEAD)"
built_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
release_id="v1.7.1-${revision}-openclaw-session"
image="inteliscope-service:${release_id}"
archive="/tmp/${release_id}-linux-amd64.tar"
source_archive="/tmp/${release_id}-source.tar.gz"
docker buildx build --platform linux/amd64 --pull --no-cache \
  --build-arg INTELISCOPE_VERSION=1.7.1 \
  --build-arg INTELISCOPE_BUILD_REVISION="$revision" \
  --build-arg INTELISCOPE_BUILT_AT="$built_at" \
  --tag "$image" --output "type=docker,dest=$archive" .
git archive --format=tar.gz --output="$source_archive" HEAD
shasum -a 256 "$archive" "$source_archive"
scp "$archive" "$source_archive" vps-tokyo:/tmp/
```

On `vps-tokyo`, compare SHA-256 values, `docker load` the image, extract the clean source archive to the new release directory, remove any extracted `data/logs/.env`, and link the release to `/opt/inteliscope/{data,logs,.env}`. Create a 0600 backup of the production database and `.env`; do not replace or restore the database.

- [ ] **Step 4: Stage and promote with bounded health checks**

Start an isolated API-only staging project on `127.0.0.1:18080` with a copied production database, copied environment with secure-cookie/readiness overrides, and the new immutable image. Verify live/ready, seven routes, unauthenticated 401, database integrity/foreign keys/active jobs, Browser Chat=true, Remote MCP=true, subscription writes=true, scheduler absent, and zero severe startup log matches. Remove staging containers, copied database, and temporary environment after verification.

Resolve the current production release and image first. Update only immutable image/version/revision/built-at values in `/opt/inteliscope/.env`, keep all feature flags and secrets unchanged, and recreate production API/Worker using the new release. Poll health by condition for up to 180 seconds; verify the same post-cutover invariants, then atomically update `/opt/inteliscope/current`. On any failed invariant, restore the environment backup, recreate the previous release/image, and verify health before returning an error.

- [ ] **Step 5: Verify the real Gateway behavior without a model call**

Connect localhost and `https://rb.jiefs.top` to `ws://127.0.0.1:13789` using their own browser pairings. Verify the Gateway log records distinct labels with `localhost:8080` and `rb.jiefs.top`, both connections retain exact `operator.read + operator.write`, `tools.effective` sees Inteliscope after connection, and no new `label already in use: Inteliscope` appears. Do not send a chat message or delete/archive any old session/device.

- [ ] **Step 6: Record rollout evidence and commit only the worklog delta**

Change D048 status to `实现、门禁与双环境发布验证完成`. Append local image ID, production release/image ID, backup paths, health/database/Gateway evidence, rollback point, and any remaining one-time browser pairing action to `WORKLOG.md`. Run `git diff --check`, then commit:

```bash
git add DECISION_LOG.md WORKLOG.md docs/superpowers/plans/2026-07-22-openclaw-session-isolation.md
git commit -m "ops: record OpenClaw session rollout"
```
