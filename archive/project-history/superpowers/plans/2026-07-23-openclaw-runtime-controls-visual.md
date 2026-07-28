# OpenClaw Runtime Controls Visual Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the connected OpenClaw composer's combined runtime popover with separate Codex-style model and thinking selectors.

**Architecture:** `OpenClawConversation.tsx` keeps ownership of the runtime presentation and calls the existing `ChatController` methods. Two controlled HeroUI `Select` components replace the compound `Popover`; the model selector consumes flexible width and the thinking selector remains intrinsic, while Gateway/session behavior stays in `useOpenClawChat` unchanged.

**Tech Stack:** React 19, TypeScript, HeroUI v3, Tailwind CSS v4, Vitest, Testing Library, Playwright, Docker Compose.

## Global Constraints

- Preserve model switching through the existing verified fork flow and per-request thinking through `chat.setThinking`.
- Preserve the 320–720 px Agent rail, 360 px Drawer, mobile Bottom Sheet, and fixed 36 px send/stop track.
- Use only design-system exports, semantic theme utilities, and existing typography roles.
- Do not add dependencies or change backend API, Gateway protocol, persistence, permissions, database, scheduler, or OpenClaw global defaults.
- Do not overwrite the pre-existing uncommitted `PLAN.md`, `DECISION_LOG.md`, or `WORKLOG.md` changes.

---

### Task 1: Separate runtime selectors

**Files:**
- Modify: `frontend/src/features/openclaw/OpenClawConversation.test.tsx`
- Modify: `frontend/src/features/openclaw/OpenClawConversation.tsx`

**Interfaces:**
- Consumes: `chat.models`, `chat.thinkingOptions`, `chat.runtimeSelection`, `chat.setModel(modelId)`, and `chat.setThinking(level)` from the existing `ChatController`.
- Produces: accessible `OpenClaw 模型：<name>` and `OpenClaw 思考程度：<label>` Select triggers plus `data-testid="openclaw-runtime-controls"`; no new exported TypeScript API.

- [ ] **Step 1: Write the failing independent-selection tests**

Replace the existing combined-control test with this test:

```tsx
it('uses separate model and thinking selectors with verified runtime actions', async () => {
  const browser = userEvent.setup()
  const chat = chatController({
    status: 'connected',
    sessionKey: 'session-1',
    models: [
      { id: 'openai/gpt-5.4', name: 'GPT-5.4', provider: 'openai', contextWindow: 200_000, reasoning: true },
      { id: 'local/quick', name: 'Quick', provider: 'local', contextWindow: 32_000, reasoning: false },
    ],
    thinkingOptions: [{ id: 'low', label: '低' }, { id: 'high', label: '高' }],
    runtimeSelection: { modelId: 'openai/gpt-5.4', thinkingLevel: 'high', defaultModelId: 'openai/gpt-5.4', defaultThinkingLevel: 'low' },
  })
  render(<OpenClawConversation chat={chat as never} value={contextValue()} />)

  expect(screen.queryByRole('button', { name: /OpenClaw 运行设置/ })).not.toBeInTheDocument()
  await browser.click(screen.getByRole('button', { name: 'OpenClaw 模型：GPT-5.4' }))
  expect(screen.getByRole('option', { name: /GPT-5.4/ })).toHaveAttribute('aria-selected', 'true')
  await browser.click(screen.getByRole('option', { name: /Quick/ }))
  expect(chat.setModel).toHaveBeenCalledWith('local/quick')

  await browser.click(screen.getByRole('button', { name: 'OpenClaw 思考程度：高' }))
  expect(screen.getByRole('option', { name: '高' })).toHaveAttribute('aria-selected', 'true')
  await browser.click(screen.getByRole('option', { name: '低' }))
  expect(chat.setThinking).toHaveBeenCalledWith('low')
})
```

Replace the non-reasoning test body after render with:

```tsx
expect(screen.getByRole('button', { name: 'OpenClaw 模型：Quick' })).toBeInTheDocument()
await browser.click(screen.getByRole('button', { name: 'OpenClaw 思考程度：自动' }))
expect(screen.getByRole('option', { name: /自动/ })).toHaveAttribute('aria-selected', 'true')
expect(screen.getByText('此模型未提供推理档位。')).toBeInTheDocument()
expect(screen.queryByRole('option', { name: '速度优先' })).not.toBeInTheDocument()
expect(screen.queryByRole('option', { name: '深度分析' })).not.toBeInTheDocument()
```

In the narrow-layout test, replace the combined-trigger assertion with:

```tsx
expect(screen.getByTestId('openclaw-runtime-controls')).toHaveClass('grid', 'grid-cols-[minmax(0,1fr)_auto]')
expect(screen.getByRole('button', { name: 'OpenClaw 模型：A deliberately long model name' })).toHaveClass('w-full', 'min-w-0')
expect(screen.getByRole('button', { name: 'OpenClaw 思考程度：深度分析' })).toHaveClass('shrink-0')
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
cd frontend && npm run test -- --run src/features/openclaw/OpenClawConversation.test.tsx
```

Expected: failure because the current UI exposes only the combined `OpenClaw 运行设置` trigger.

- [ ] **Step 3: Implement the two controlled Selects**

Add `Select` to the design-system imports, remove `ComboBox`, and replace `RuntimeControls` with:

```tsx
const AUTO_THINKING_KEY = '__auto__'

function RuntimeControls({ chat }: { chat: ChatController }) {
  const currentModel = chat.models.find((model) => model.id === chat.runtimeSelection.modelId)
  const currentThinking = chat.thinkingOptions.find((option) => option.id === chat.runtimeSelection.thinkingLevel)
  const controlsDisabled = chat.isRunning || chat.runtimeUpdating || chat.runtimeLoading
  const modelDisabled = controlsDisabled || !chat.models.length
  const thinkingDisabled = controlsDisabled || !currentModel
  const modelLabel = currentModel?.name ?? (chat.runtimeLoading ? '正在读取模型…' : 'OpenClaw 当前设置')
  const thinkingLabel = currentThinking?.label ?? '自动'
  const thinkingItems: Array<{ id: string; label: string; description?: string }> = [
    {
      id: AUTO_THINKING_KEY,
      label: '自动',
      description: currentModel?.reasoning === false ? '此模型未提供推理档位。' : '使用 OpenClaw 默认设置',
    },
    ...(currentModel?.reasoning === false
      ? []
      : chat.thinkingOptions.map((option) => ({ ...option, description: undefined }))),
  ]

  return <div
    data-testid="openclaw-runtime-controls"
    className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-0.5 overflow-hidden"
  >
    <Select
      aria-label={`OpenClaw 模型：${modelLabel}`}
      selectedKey={chat.runtimeSelection.modelId ?? undefined}
      onSelectionChange={(key: Key | null) => {
        if (key === null || String(key) === chat.runtimeSelection.modelId) return
        void chat.setModel(String(key))
      }}
      isDisabled={modelDisabled}
      className="min-w-0 overflow-hidden"
    >
      <Select.Trigger
        aria-label={`OpenClaw 模型：${modelLabel}`}
        className={`type-control flex min-h-8 w-full min-w-0 max-w-full items-center gap-1 overflow-hidden rounded-lg border-0 bg-transparent px-1.5 shadow-none focus-visible:outline-2 focus-visible:outline-focus ${modelDisabled ? 'text-muted' : 'text-foreground hover:bg-default'}`}
      >
        <span className="min-w-0 truncate">{modelLabel}</span>
        <Select.Indicator><Icons.ChevronDown size={12} className="shrink-0 text-muted" aria-hidden="true" /></Select.Indicator>
      </Select.Trigger>
      <Select.Popover placement="top start" offset={8} className="z-50 w-[min(320px,calc(100vw-24px))]">
        <ListBox items={chat.models} aria-label="OpenClaw 模型">
          {(model) => <ListBox.Item id={model.id} textValue={model.name} className="min-w-0">
            <span className="type-control block min-w-0 truncate">{model.name}</span>
            <span className="type-meta block min-w-0 truncate text-muted">{model.provider}{formatContextWindow(model.contextWindow) ? ` · ${formatContextWindow(model.contextWindow)}` : ''}</span>
          </ListBox.Item>}
        </ListBox>
      </Select.Popover>
    </Select>

    <Select
      aria-label={`OpenClaw 思考程度：${thinkingLabel}`}
      selectedKey={chat.runtimeSelection.thinkingLevel ?? AUTO_THINKING_KEY}
      onSelectionChange={(key: Key | null) => {
        if (key === null) return
        const next = String(key) === AUTO_THINKING_KEY ? null : String(key)
        if (next === chat.runtimeSelection.thinkingLevel) return
        void chat.setThinking(next)
      }}
      isDisabled={thinkingDisabled}
      className="shrink-0"
    >
      <Select.Trigger
        aria-label={`OpenClaw 思考程度：${thinkingLabel}`}
        className={`type-control flex min-h-8 shrink-0 items-center gap-1 rounded-lg border-0 bg-transparent px-1.5 shadow-none focus-visible:outline-2 focus-visible:outline-focus ${thinkingDisabled ? 'text-muted' : 'text-foreground hover:bg-default'}`}
      >
        <span>{thinkingLabel}</span>
        <Select.Indicator><Icons.ChevronDown size={12} className="shrink-0 text-muted" aria-hidden="true" /></Select.Indicator>
      </Select.Trigger>
      <Select.Popover placement="top end" offset={8} className="z-50 w-[min(220px,calc(100vw-24px))]">
        <ListBox items={thinkingItems} aria-label="OpenClaw 思考程度">
          {(option) => <ListBox.Item id={option.id} textValue={option.label} className="min-w-0">
            <span className="type-control block">{option.label}</span>
            {option.description && <span className="type-meta block text-muted">{option.description}</span>}
          </ListBox.Item>}
        </ListBox>
      </Select.Popover>
    </Select>
  </div>
}
```

Keep `Input`, `Label`, `Popover`, and `useState` because the setup and context surfaces still use them.

- [ ] **Step 4: Run focused verification and verify GREEN**

Run:

```bash
cd frontend
npm run test -- --run src/features/openclaw/OpenClawConversation.test.tsx
npm run typecheck
npm run check:ui
npm run lint
npm run build
```

Expected: all commands exit 0 and the OpenClaw component tests pass.

### Task 2: Record the UI contract and acceptance evidence

**Files:**
- Modify: `UI_CONTRACT.md`
- Modify: `DECISION_LOG.md`
- Modify: `WORKLOG.md`

**Interfaces:**
- Consumes: D049 runtime safety rules and the UI contract's connected composer section.
- Produces: one authoritative visual rule for two peer controls and one decision entry explaining the presentation-only change.

- [ ] **Step 1: Update the authoritative UI rule**

Replace the sentence beginning “One compact runtime control displays the model” with:

```md
Two peer compact runtime controls separately display the model verified from `sessions.describe` and the active thinking level, never optimistic browser values. The model control owns the flexible truncated track, the thinking control remains intrinsically sized, and each opens only its own upward selection menu while the fixed send/stop action remains visible at the 320 px rail minimum.
```

- [ ] **Step 2: Add the decision rationale and worklog evidence**

Append this decision heading and fields after D051:

```md
### D052 OpenClaw 运行参数采用 Codex 式并列选择器

- 决策日期：2026-07-23
- 当前状态：本地实现
- 决策内容：连接态 composer 将模型与思考程度拆为两个同级紧凑 Select；模型占弹性截断轨，思考占固有宽度，两者各自向上打开单一职责菜单，发送/停止动作继续固定为 36 px。
- 原因：原单一全宽触发器把两个独立参数压成一句文字，并在复合弹层中嵌套模型选择和思考按钮组，信息层级、操作成本与 Codex 参考均不理想。
- 影响范围：仅 `OpenClawConversation` 的运行参数呈现、可访问名称、组件回归与 UI 合同。
- 兼容/回退：模型仍经 verified fork 切换，思考仍只按请求传递；无 API、Gateway、持久化、权限、数据库或 OpenClaw 全局默认变化。回退该前端组件即可恢复旧复合弹层。
```

Append the actual focused test/build/browser results to `WORKLOG.md` after verification without disturbing existing entries.

- [ ] **Step 3: Run repository verification**

Run:

```bash
python3 scripts/test_gate.py run --mode full
python3 -m json.tool project-defaults.yaml >/dev/null
git diff --check
```

Expected: full gate reports 22/22 passed, JSON validation exits 0, and diff check exits 0.

- [ ] **Step 4: Rebuild and visually verify localhost**

Inspect active jobs and automatic schedules first. If safe, run `./scripts/up-latest.sh`, wait for API and Worker health, open `http://127.0.0.1:8080/feed`, and verify desktop plus minimum-width Agent layouts have separate selectors, correctly placed upward menus, visible focus, and no horizontal overflow.

- [ ] **Step 5: Review the final branch diff**

Confirm the diff contains only the runtime-control presentation, focused tests, design/plan, required control-plane records, and worklog. Do not stage or overwrite unrelated pre-existing control-file changes.
