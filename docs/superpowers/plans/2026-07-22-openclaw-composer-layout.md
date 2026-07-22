# OpenClaw Composer Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the connected OpenClaw composer so its input and controls keep stable geometry in the existing narrow Web Agent rail.

**Architecture:** `ConnectedConversation` remains the single owner of sending and draft state. Only its composer markup changes: the surface becomes an explicit input row plus a two-column toolbar, while `RuntimeControls` becomes a width-owned, truncating grid child.

**Tech Stack:** React 19, TypeScript, HeroUI v3, Tailwind CSS v4, Vitest, Testing Library, Docker Compose.

## Global Constraints

- Preserve the existing 320–720px resizable Agent rail and 360px Drawer.
- Preserve Enter-to-send, Shift+Enter newline, context summary, send/stop behavior, and runtime selection semantics.
- The message field has a 96px minimum height.
- The toolbar uses `grid-cols-[minmax(0,1fr)_36px]`; the action column never shrinks.
- Do not change backend APIs, query keys, Gateway calls, session persistence, or dependencies.

---

### Task 1: Stable connected composer geometry

**Files:**
- Modify: `frontend/src/features/openclaw/OpenClawConversation.test.tsx`
- Modify: `frontend/src/features/openclaw/OpenClawConversation.tsx`
- Modify: `WORKLOG.md`

**Interfaces:**
- Consumes: the existing `OpenClawConversation({ chat, value })` component and `ChatController`/`WorkbenchAgentContextValue` contracts.
- Produces: stable `data-testid="openclaw-composer"` and `data-testid="openclaw-composer-toolbar"` layout markers; no new exported TypeScript API.

- [x] **Step 1: Write the failing layout contract test**

Add a connected-state test with a deliberately long runtime label and assert the desired geometry:

```tsx
it('keeps the connected composer input and actions in stable grid tracks', () => {
  const chat = chatController({
    status: 'connected',
    sessionKey: 'session-1',
    models: [{ id: 'provider/long-model', name: 'A deliberately long model name', provider: 'provider', reasoning: true }],
    thinkingOptions: [{ id: 'high', label: '深度分析' }],
    runtimeSelection: { modelId: 'provider/long-model', thinkingLevel: 'high', defaultModelId: null, defaultThinkingLevel: null },
  })
  render(<OpenClawConversation chat={chat as never} value={contextValue()} />)

  expect(screen.getByTestId('openclaw-composer')).toHaveClass('grid', 'grid-rows-[minmax(96px,auto)_36px]', 'gap-2')
  expect(screen.getByLabelText('发送给 OpenClaw 的问题')).toHaveClass('min-h-24')
  expect(screen.getByTestId('openclaw-composer-toolbar')).toHaveClass('grid', 'grid-cols-[minmax(0,1fr)_36px]')
  expect(screen.getByTestId('openclaw-composer-toolbar')).not.toHaveClass('mt-2')
  expect(screen.getByRole('button', { name: '发送给 OpenClaw' })).toHaveClass('size-9', 'shrink-0')
  expect(screen.getByRole('button', { name: 'OpenClaw 运行设置：A deliberately long model name · 深度分析' })).toHaveClass('w-full')
})
```

- [x] **Step 2: Run the test and verify RED**

Run:

```bash
cd frontend && npm run test -- --run src/features/openclaw/OpenClawConversation.test.tsx
```

Expected: the new test fails because `openclaw-composer` and `openclaw-composer-toolbar` do not exist and the current footer still uses `flex`.

- [x] **Step 3: Implement the minimal two-row composer**

Apply these exact class and test-marker changes; all component bodies and event handlers remain unchanged:

```diff
- className={`type-control flex min-w-0 max-w-full flex-1 items-center gap-1 rounded-lg px-1.5 py-1 focus-visible:outline-2 focus-visible:outline-focus ${controlsDisabled || !chat.models.length ? 'cursor-default text-muted' : 'text-foreground hover:bg-default'}`}
+ className={`type-control flex w-full min-w-0 max-w-full items-center gap-1 overflow-hidden rounded-lg px-1.5 py-1 focus-visible:outline-2 focus-visible:outline-focus ${controlsDisabled || !chat.models.length ? 'cursor-default text-muted' : 'text-foreground hover:bg-default'}`}

- <div className="min-w-0 rounded-2xl border border-separator bg-surface-secondary p-2 shadow-sm focus-within:border-border">
+ <div data-testid="openclaw-composer" className="grid min-w-0 grid-rows-[minmax(96px,auto)_36px] gap-2 rounded-2xl border border-separator bg-surface-secondary p-2 shadow-sm focus-within:border-border">

- className="type-body min-w-0 max-w-full [overflow-wrap:anywhere]"
+ className="type-body min-h-24 min-w-0 max-w-full [overflow-wrap:anywhere]"

- <div className="mt-2 flex min-w-0 items-end gap-1.5 px-1 pb-0.5">
+ <div data-testid="openclaw-composer-toolbar" className="grid min-w-0 grid-cols-[minmax(0,1fr)_36px] items-end gap-1.5 px-1 pb-0.5">
```

Keep runtime messages immediately after the toolbar inside the composer surface and let them span naturally below the fixed tracks.

- [x] **Step 4: Run focused verification and verify GREEN**

Run:

```bash
cd frontend && npm run test -- --run src/features/openclaw/OpenClawConversation.test.tsx
npm run typecheck
npm run build
```

Expected: all OpenClaw conversation tests pass; TypeScript and the production build exit 0.

- [ ] **Step 5: Build and verify localhost**

Build a revision-tagged Docker image from the worktree, switch only the local Compose API/Worker to it, wait for both services to become healthy, reload `http://127.0.0.1:8080/feed`, and verify the Agent panel has `scrollWidth === clientWidth` at the visible viewport.

- [ ] **Step 6: Record evidence and commit**

Append focused test/build/container/browser evidence to `WORKLOG.md`, run `git diff --check`, and commit the product/test/docs changes with:

```bash
git commit -m "fix(ui): stabilize OpenClaw composer layout"
```
