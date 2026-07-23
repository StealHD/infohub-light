# Feed Insights Dismissal and Theme Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand obstructing Feed Insights dismissal to every primary-pointer click that has no interactive target, add a soft exit transition, and expose persistent dark/light controls at the application’s top-right.

**Architecture:** Keep Feed Insights geometry and lifecycle inside `HeroWorkbenchShell`, but model exit as an explicit closing phase so the surface remains mounted and inert for the design-system motion duration. Keep palette ownership in the design system by replacing the system-only reader with a versioned `ThemePreference` model; `DesignSystemProvider` remains the single state owner, the HTML bootstrap reads the same persisted preference before React starts, and a shared icon-only toggle is reused by authenticated and login headers. The theme family and the light/dark color mode remain separate so a future theme family can be added without changing the two-mode control.

**Tech Stack:** React 19, TypeScript 6, HeroUI v3, Tailwind CSS v4, Vitest/Testing Library, Playwright, Python test-gate wrapper.

## Global Constraints

- Start from local `main` in the isolated branch `codex/feed-insights-theme-toggle`.
- Preserve the existing graphite-purple dark palette as the default and current night mode.
- Expose only `dark` and `light`; do not add a system or custom-theme choice.
- Keep raw palette values and motion definitions in `frontend/src/design-system/**`.
- Do not add an API, database field, query key, scheduler, source fetch, AI call, or paid-provider call.
- Primary-pointer dismissal applies only while measured Insights geometry overlaps the Feed reading frame.
- Interactive controls and the Insights surface itself never count as ineffective clicks.
- Reduced Motion makes the Insights exit effectively immediate while preserving the final state.

---

### Task 1: Versioned theme preference and single provider

**Files:**
- Create: `frontend/src/design-system/themePreference.ts`
- Modify: `frontend/src/design-system/DesignSystemProvider.tsx`
- Modify: `frontend/src/design-system/DesignSystemProvider.test.tsx`
- Delete: `frontend/src/design-system/systemTheme.ts`
- Modify: `frontend/src/design-system/theme.ts`

**Interfaces:**
- Produces: `ThemeColorMode = 'dark' | 'light'`.
- Produces: `ThemePreference = { themeName: 'graphite-purple'; colorMode: ThemeColorMode }`.
- Produces: `THEME_PREFERENCE_STORAGE_KEY`, `DEFAULT_THEME_PREFERENCE`, `readThemePreference()`, and `writeThemePreference()`.
- Produces: `useThemePreference(): { themeName; colorMode; setColorMode; toggleColorMode }`.

- [x] **Step 1: Write failing preference/provider tests**

```tsx
it('defaults to the existing dark graphite theme and ignores system changes', () => {
  installSystemTheme(false)
  render(<MemoryRouter><DesignSystemProvider><main data-testid="content" /></DesignSystemProvider></MemoryRouter>)
  expect(screen.getByTestId('content').parentElement).toHaveAttribute('data-theme', 'dark')
  expect(document.documentElement).toHaveAttribute('data-theme', 'dark')
})

it('restores a valid persisted light preference on both theme roots', () => {
  window.localStorage.setItem(THEME_PREFERENCE_STORAGE_KEY, JSON.stringify({
    themeName: 'graphite-purple',
    colorMode: 'light',
  }))
  render(<MemoryRouter><DesignSystemProvider><main data-testid="content" /></DesignSystemProvider></MemoryRouter>)
  expect(screen.getByTestId('content').parentElement).toHaveAttribute('data-theme', 'light')
  expect(document.documentElement).toHaveAttribute('data-theme', 'light')
})

it('sanitizes malformed or unsupported preferences back to dark graphite', () => {
  window.localStorage.setItem(THEME_PREFERENCE_STORAGE_KEY, JSON.stringify({
    themeName: 'unsupported',
    colorMode: 'system',
  }))
  expect(readThemePreference()).toEqual(DEFAULT_THEME_PREFERENCE)
})
```

- [x] **Step 2: Run the focused test and confirm RED**

Run: `npm test -- --run src/design-system/DesignSystemProvider.test.tsx`

Expected: FAIL because `themePreference.ts`, `THEME_PREFERENCE_STORAGE_KEY`, and persisted manual color-mode behavior do not exist.

- [x] **Step 3: Implement the preference model**

```ts
export type ThemeColorMode = 'dark' | 'light'
export type ThemeName = 'graphite-purple'
export type ThemePreference = {
  themeName: ThemeName
  colorMode: ThemeColorMode
}

export const THEME_PREFERENCE_STORAGE_KEY = 'inteliscope.ui.theme.v1'
export const DEFAULT_THEME_PREFERENCE: ThemePreference = {
  themeName: 'graphite-purple',
  colorMode: 'dark',
}

export function readThemePreference(storage: Storage | undefined = globalThis.window?.localStorage): ThemePreference {
  if (!storage) return DEFAULT_THEME_PREFERENCE
  try {
    const value = JSON.parse(storage.getItem(THEME_PREFERENCE_STORAGE_KEY) || 'null') as Partial<ThemePreference> | null
    if (value?.themeName !== 'graphite-purple' || (value.colorMode !== 'dark' && value.colorMode !== 'light')) {
      return DEFAULT_THEME_PREFERENCE
    }
    return { themeName: value.themeName, colorMode: value.colorMode }
  } catch {
    return DEFAULT_THEME_PREFERENCE
  }
}

export function writeThemePreference(preference: ThemePreference, storage: Storage | undefined = globalThis.window?.localStorage): ThemePreference {
  const value = preference.themeName === 'graphite-purple' && (preference.colorMode === 'dark' || preference.colorMode === 'light')
    ? preference
    : DEFAULT_THEME_PREFERENCE
  try {
    storage?.setItem(THEME_PREFERENCE_STORAGE_KEY, JSON.stringify(value))
  } catch {
    // Preference persistence is best-effort; the in-memory mode still changes.
  }
  return value
}
```

- [x] **Step 4: Make `DesignSystemProvider` own the sanitized preference**

```tsx
type ThemePreferenceContextValue = ThemePreference & {
  setColorMode: (mode: ThemeColorMode) => void
  toggleColorMode: () => void
}

const ThemePreferenceContext = createContext<ThemePreferenceContextValue | null>(null)

export function useThemePreference() {
  const value = useContext(ThemePreferenceContext)
  if (!value) throw new Error('useThemePreference must be used inside DesignSystemProvider')
  return value
}

export function DesignSystemProvider({ children }: { children: ReactNode }) {
  const [preference, setPreference] = useState<ThemePreference>(readThemePreference)
  const setColorMode = useCallback((colorMode: ThemeColorMode) => {
    setPreference((current) => writeThemePreference({ ...current, colorMode }))
  }, [])
  const toggleColorMode = useCallback(() => {
    setPreference((current) => writeThemePreference({
      ...current,
      colorMode: current.colorMode === 'dark' ? 'light' : 'dark',
    }))
  }, [])

  useLayoutEffect(() => acquireThemeRoot(document.documentElement), [])
  useLayoutEffect(() => applyThemeRoot(document.documentElement, preference), [preference])

  return <ThemePreferenceContext.Provider value={{ ...preference, setColorMode, toggleColorMode }}>
    <DesignSystemRouterProvider>
      <div
        className="inteliscope-design-system"
        data-theme={preference.colorMode}
        data-inteliscope-theme={preference.themeName}
        data-ui-system="heroui"
      >
        {children}
        <ToastProvider placement="top" maxVisibleToasts={3} width="min(420px, calc(100vw - 24px))" />
      </div>
    </DesignSystemRouterProvider>
  </ThemePreferenceContext.Provider>
}
```

- [x] **Step 5: Run focused tests and confirm GREEN**

Run: `npm test -- --run src/design-system/DesignSystemProvider.test.tsx`

Expected: PASS with dark default, stored light restoration, malformed-data fallback, and both document/application roots synchronized.

- [x] **Step 6: Commit the preference boundary**

```bash
git add frontend/src/design-system/themePreference.ts frontend/src/design-system/systemTheme.ts frontend/src/design-system/DesignSystemProvider.tsx frontend/src/design-system/DesignSystemProvider.test.tsx frontend/src/design-system/theme.ts
git commit -m "feat(ui): add persistent theme preference"
```

### Task 2: Top-right dark/light icon control and first-paint restoration

**Files:**
- Create: `frontend/src/design-system/ThemeModeToggle.tsx`
- Create: `frontend/src/design-system/ThemeModeToggle.test.tsx`
- Modify: `frontend/src/design-system/index.ts`
- Modify: `frontend/src/features/workbench-live/HeroWorkbenchShell.tsx`
- Modify: `frontend/src/features/workbench-live/HeroWorkbenchShell.test.tsx`
- Modify: `frontend/src/features/admin-heroui/HeroLoginPage.tsx`
- Modify: `frontend/index.html`
- Modify: `frontend/src/AppBootstrap.test.tsx`
- Modify: `frontend/e2e/production-workbench.spec.ts`

**Interfaces:**
- Consumes: `useThemePreference()` from Task 1.
- Produces: `ThemeModeToggle`, an icon-only button with action labels `切换到白天模式` and `切换到黑夜模式`.
- Produces: first-paint bootstrap behavior using `inteliscope.ui.theme.v1`.

- [x] **Step 1: Write failing toggle, shell, login, and bootstrap tests**

```tsx
it('toggles from the default night mode to day mode and persists it', async () => {
  const browser = userEvent.setup()
  render(<MemoryRouter><DesignSystemProvider><ThemeModeToggle /></DesignSystemProvider></MemoryRouter>)
  await browser.click(screen.getByRole('button', { name: '切换到白天模式' }))
  expect(document.documentElement).toHaveAttribute('data-theme', 'light')
  expect(JSON.parse(window.localStorage.getItem(THEME_PREFERENCE_STORAGE_KEY) || 'null')).toEqual({
    themeName: 'graphite-purple',
    colorMode: 'light',
  })
  expect(screen.getByRole('button', { name: '切换到黑夜模式' })).toBeInTheDocument()
})

expect(screen.getByRole('heading', { name: '信息流' }).closest('header'))
  .toContainElement(screen.getByRole('button', { name: '切换到白天模式' }))

expect(screen.getByRole('heading', { name: '登录私人信息雷达' }))
  .toBeInTheDocument()
expect(screen.getByRole('button', { name: '切换到白天模式' }))
  .toBeInTheDocument()

expect(html).toContain("'inteliscope.ui.theme.v1'")
expect(html).toContain("colorMode === 'light' || colorMode === 'dark'")
expect(html).not.toContain("matchMedia('(prefers-color-scheme: dark)')")
```

- [x] **Step 2: Run focused tests and confirm RED**

Run: `npm test -- --run src/design-system/ThemeModeToggle.test.tsx src/features/workbench-live/HeroWorkbenchShell.test.tsx src/AppBootstrap.test.tsx src/app/App.test.tsx`

Expected: FAIL because the icon control and persisted pre-React bootstrap are absent.

- [x] **Step 3: Implement the shared icon-only control**

```tsx
export function ThemeModeToggle() {
  const { colorMode, toggleColorMode } = useThemePreference()
  const nextLabel = colorMode === 'dark' ? '白天' : '黑夜'
  return <Button
    size="sm"
    variant="ghost"
    isIconOnly
    data-theme-mode-toggle
    className="h-8 w-[34px] rounded-[var(--inteliscope-radius-control)] text-muted transition-[color,background-color,transform] duration-[var(--inteliscope-motion-standard)] hover:bg-default hover:text-foreground active:scale-95 motion-reduce:transform-none"
    aria-label={`切换到${nextLabel}模式`}
    title={`切换到${nextLabel}模式`}
    onPress={toggleColorMode}
  >
    {colorMode === 'dark'
      ? <Icons.Sun size={18} aria-hidden="true" />
      : <Icons.Moon size={18} aria-hidden="true" />}
  </Button>
}
```

- [x] **Step 4: Place the control at the far right of every authenticated `PageHeader` and the login surface**

```tsx
actions={<div className="flex items-center gap-1">
  {feedRoute && <Button
    ref={insightsToggleRef}
    size="sm"
    variant="ghost"
    isIconOnly
    data-right-rail-toggle="insights"
    className={`h-8 w-[34px] rounded-[var(--inteliscope-radius-control)] transition-[color,background-color,transform] duration-[var(--inteliscope-motion-standard)] hover:bg-default hover:text-foreground active:scale-95 motion-reduce:transform-none ${insightsOpen ? 'bg-accent/15 text-accent' : 'text-muted'}`}
    aria-label={insightsOpen ? '收起信息概览' : '展开信息概览'}
    aria-expanded={insightsOpen}
    aria-controls="feed-insights-surface"
    isDisabled={openclawChat.isRunning && !dockCapable}
    onPress={toggleInsights}
  ><Icons.ChartNoAxesCombined size={18} aria-hidden="true" /></Button>}
  {agentRoute && <Button
    ref={agentToggleRef}
    size="sm"
    variant="ghost"
    isIconOnly
    data-agent-toggle-visual="quiet-studio"
    data-agent-open={visibleRightRailMode === 'agent' ? 'true' : 'false'}
    className="h-8 w-[34px] rounded-[var(--inteliscope-radius-control)] text-muted transition-[color,background-color,transform] duration-[var(--inteliscope-motion-standard)] hover:bg-default hover:text-foreground active:scale-95 data-[agent-open=true]:bg-accent/15 data-[agent-open=true]:text-accent motion-reduce:transform-none"
    aria-label={visibleRightRailMode === 'agent' ? '收起 Agent 面板' : '展开 Agent 面板'}
    aria-expanded={visibleRightRailMode === 'agent'}
    aria-controls="live-agent-panel"
    isDisabled={openclawChat.isRunning}
    onPress={toggleAgentRail}
  ><Icons.SplitPanel open={visibleRightRailMode === 'agent'} size={18} aria-hidden="true" /></Button>}
  <ThemeModeToggle />
</div>}
```

```tsx
return <main className="relative grid min-h-dvh place-items-center bg-background p-4">
  <div className="absolute right-3 top-3"><ThemeModeToggle /></div>
  <PageFrame width="auth">
    <Card variant="secondary" className="w-full p-6 min-[640px]:p-8" aria-labelledby="hero-login-title">
      <div className="mb-6 flex size-10 items-center justify-center rounded-xl bg-accent text-accent-foreground"><Icons.InteliscopeMark size={21} aria-hidden="true" /></div>
      <h1 id="hero-login-title" className="type-display">登录私人信息雷达</h1>
      <Card.Description className="mt-2">订阅、获取并留存真正需要的信息。</Card.Description>
      <Form onSubmit={submit} className="mt-6 grid gap-4">
        <TextField fullWidth isRequired value={username} onChange={setUsername} name="username">
          <Label>用户名</Label>
          <Input autoComplete="username" />
          <FieldError />
        </TextField>
        <TextField fullWidth isRequired value={password} onChange={setPassword} name="password">
          <Label>密码</Label>
          <Input type="password" autoComplete="current-password" />
          <FieldError />
        </TextField>
        {error && <HeroNotice title={error} />}
        <Button type="submit" fullWidth isPending={pending} isDisabled={pending}>{pending ? '登录中…' : '登录'}</Button>
      </Form>
    </Card>
  </PageFrame>
</main>
```

- [x] **Step 5: Read the stored preference in `index.html` before React starts**

```js
let themePreference = null
try {
  themePreference = JSON.parse(window.localStorage.getItem('inteliscope.ui.theme.v1') || 'null')
} catch {
  themePreference = null
}
const colorMode = themePreference?.colorMode
document.documentElement.dataset.theme = colorMode === 'light' || colorMode === 'dark' ? colorMode : 'dark'
document.documentElement.dataset.inteliscopeTheme = 'graphite-purple'
```

- [x] **Step 6: Replace the system-following Playwright case with manual-mode persistence**

```ts
test('the production theme defaults to night and persists explicit day/night choices', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'A single desktop browser covers the shared theme root.')
  await page.emulateMedia({ colorScheme: 'light' })
  await page.goto('/changelog')
  const root = page.locator('html')
  const app = page.locator('[data-ui-system="heroui"]')
  await expect(root).toHaveAttribute('data-theme', 'dark')
  await expect(app).toHaveAttribute('data-theme', 'dark')

  await page.getByRole('button', { name: '切换到白天模式' }).click()
  await expect(root).toHaveAttribute('data-theme', 'light')
  await page.emulateMedia({ colorScheme: 'dark' })
  await expect(root).toHaveAttribute('data-theme', 'light')
  await page.reload()
  await expect(app).toHaveAttribute('data-theme', 'light')

  await page.getByRole('button', { name: '切换到黑夜模式' }).click()
  await expect(root).toHaveAttribute('data-theme', 'dark')
})
```

- [x] **Step 7: Run focused tests and confirm GREEN**

Run: `npm test -- --run src/design-system/ThemeModeToggle.test.tsx src/features/workbench-live/HeroWorkbenchShell.test.tsx src/AppBootstrap.test.tsx src/app/App.test.tsx`

Expected: PASS with the icon in the top-right header/login positions, a dark default, persisted light restoration, and no live system override.

- [x] **Step 8: Commit the control**

```bash
git add frontend/index.html frontend/src/AppBootstrap.test.tsx frontend/src/design-system frontend/src/features/workbench-live/HeroWorkbenchShell.tsx frontend/src/features/workbench-live/HeroWorkbenchShell.test.tsx frontend/src/features/admin-heroui/HeroLoginPage.tsx frontend/e2e/production-workbench.spec.ts
git commit -m "feat(ui): add day and night mode toggle"
```

### Task 3: Broad ineffective-click dismissal and soft Insights exit

**Files:**
- Modify: `frontend/src/features/workbench-live/HeroWorkbenchShell.tsx`
- Modify: `frontend/src/features/workbench-live/HeroWorkbenchShell.test.tsx`
- Modify: `frontend/src/design-system/theme.css`
- Modify: `frontend/src/design-system/patterns.test.tsx`
- Modify: `frontend/e2e/production-workbench.spec.ts`

**Interfaces:**
- Changes: `InsightsSurfaceState` becomes `'closed' | 'auto' | 'manual' | 'closing'`.
- Produces: shell-wide `onPointerDown` dismissal for a primary pointer on a non-interactive target while Insights overlaps the reading frame.
- Produces: `quiet-surface-exit` design-system motion lasting `--inteliscope-motion-deliberate`.

- [x] **Step 1: Write failing shell lifecycle tests**

```tsx
it('softly dismisses obstructing Insights from any ineffective shell click', async () => {
  const originalRect = HTMLElement.prototype.getBoundingClientRect
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    if (this.matches('[data-page-frame="reading"]')) {
      return { left: 100, right: 1000, top: 60, bottom: 850, width: 900, height: 790, x: 100, y: 60, toJSON: () => ({}) }
    }
    if (this.getAttribute('aria-label') === '信息概览') {
      return { left: 900, right: 1252, top: 60, bottom: 700, width: 352, height: 640, x: 900, y: 60, toJSON: () => ({}) }
    }
    return originalRect.call(this)
  })
  const browser = userEvent.setup()
  render(<Shell user={{ id: 'obstructed-insights', username: 'blocked', role: 'member', enabled: true }} />)
  await browser.click(screen.getByRole('button', { name: '展开信息概览' }))
  await waitFor(() => expect(screen.getByTestId('live-workbench-shell'))
    .toHaveAttribute('data-insights-obstructs-feed', 'true'))

  await browser.click(screen.getByRole('heading', { name: '信息流' }))
  const surface = document.getElementById('feed-insights-surface')
  expect(surface).toHaveAttribute('data-insights-surface', 'closing')
  expect(surface).toHaveAttribute('aria-hidden', 'true')
  expect(surface).toHaveAttribute('inert')
  expect(surface).toHaveClass('quiet-surface-exit')
  await waitFor(() => expect(document.getElementById('feed-insights-surface')).toBeNull(), { timeout: 600 })
  vi.restoreAllMocks()
})

it('preserves obstructing Insights when an actual control is activated', async () => {
  await browser.click(screen.getByRole('button', { name: '展开 Agent 面板' }))
  expect(screen.getByRole('complementary', { name: '信息概览' })).toBeInTheDocument()
})
```

- [x] **Step 2: Run the shell test and confirm RED**

Run: `npm test -- --run src/features/workbench-live/HeroWorkbenchShell.test.tsx`

Expected: FAIL because pointer handling is limited to `[data-feed-blank-region]` and closing unmounts Insights immediately.

- [x] **Step 3: Add the explicit closing lifecycle**

```tsx
export type InsightsSurfaceState = 'closed' | 'auto' | 'manual' | 'closing'
const insightsClosingTimer = useRef<number | undefined>(undefined)
const insightsOpen = feedRoute && (insightsSurface === 'auto' || insightsSurface === 'manual')
const insightsPresent = feedRoute && insightsSurface !== 'closed'
const insightsClosing = insightsSurface === 'closing'

const closeInsights = useCallback((restoreFocus = true) => {
  if (insightsSurface === 'closed' || insightsSurface === 'closing') return
  suppressAutomaticInsights()
  window.clearTimeout(insightsClosingTimer.current)
  setInsightsSurface('closing')
  insightsClosingTimer.current = window.setTimeout(() => {
    insightsClosingTimer.current = undefined
    setInsightsSurface('closed')
  }, deliberateLayoutMotionMs)
  if (restoreFocus) window.requestAnimationFrame(() => insightsToggleRef.current?.focus())
}, [insightsSurface, suppressAutomaticInsights])
```

Render the desktop surface while `insightsPresent`, and make the closing phase inert:

```tsx
<aside
  aria-hidden={insightsClosing}
  inert={insightsClosing}
  data-insights-surface={insightsSurface}
  className={`${insightsClosing ? 'quiet-surface-exit pointer-events-none' : 'quiet-surface-enter'} ...`}
>
```

- [x] **Step 4: Move dismissal to the shell and filter only actual interactions**

```tsx
const interactivePointerTarget = [
  'a[href]',
  'button',
  'input',
  'textarea',
  'select',
  'label',
  'summary',
  '[role="button"]',
  '[role="link"]',
  '[role="menuitem"]',
  '[role="option"]',
  '[role="tab"]',
  '[role="checkbox"]',
  '[role="radio"]',
  '[role="switch"]',
  '[contenteditable="true"]',
].join(',')

const handleIneffectivePrimaryPointerDown = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
  if (!feedRoute || !insightsOpen || !insightsObstructsFeed || event.button !== 0 || event.defaultPrevented) return
  const target = event.target
  if (!(target instanceof Element) || insightsRef.current?.contains(target)) return
  if (target.closest(interactivePointerTarget)) return
  closeInsights(false)
}, [closeInsights, feedRoute, insightsObstructsFeed, insightsOpen])
```

Attach this handler to the root workbench shell and remove the main-only `[data-feed-blank-region]` pointer handler.

- [x] **Step 5: Add the exit animation and Reduced Motion coverage**

```css
@keyframes quiet-surface-exit {
  from {
    opacity: 1;
    transform: translateX(0) scale(1);
  }
  to {
    opacity: 0;
    transform: translateX(8px) scale(0.995);
  }
}

.inteliscope-design-system .quiet-surface-exit {
  animation: quiet-surface-exit var(--inteliscope-motion-deliberate) ease-in both;
}
```

Add `.quiet-surface-exit` beside `.quiet-surface-enter` in the Reduced Motion selector.

- [x] **Step 6: Add a desktop Playwright assertion for the wider trigger and exit phase**

```ts
await page.getByRole('button', { name: '展开信息概览' }).click()
await expect(shell).toHaveAttribute('data-insights-obstructs-feed', 'true')
const insights = page.locator('#feed-insights-surface')
await page.getByRole('heading', { name: '信息流' }).click()
await expect(insights).toHaveAttribute('data-insights-surface', 'closing')
expect(await insights.evaluate((element) => getComputedStyle(element).animationName)).toBe('quiet-surface-exit')
await expect(insights).toHaveCount(0)
```

- [x] **Step 7: Run focused tests and confirm GREEN**

Run: `npm test -- --run src/features/workbench-live/HeroWorkbenchShell.test.tsx src/design-system/patterns.test.tsx`

Expected: PASS with shell-wide ineffective-click dismissal, interactive-target protection, the explicit closing phase, and Reduced Motion coverage.

- [x] **Step 8: Commit the Insights interaction**

```bash
git add frontend/src/features/workbench-live/HeroWorkbenchShell.tsx frontend/src/features/workbench-live/HeroWorkbenchShell.test.tsx frontend/src/design-system/theme.css frontend/src/design-system/patterns.test.tsx frontend/e2e/production-workbench.spec.ts
git commit -m "feat(ui): soften obstructing insights dismissal"
```

### Task 4: Control-plane record and completion verification

**Files:**
- Modify: `UI_CONTRACT.md`
- Modify: `DECISION_LOG.md`
- Modify: `PLAN.md`
- Modify: `WORKLOG.md`
- Modify: `docs/superpowers/plans/2026-07-23-feed-insights-theme-toggle.md`

**Interfaces:**
- Replaces: D048’s system-only/no-override theme decision.
- Produces: D053 recording the browser-persisted manual dark/light mode and theme-family separation.
- Refines: the Insights click-away contract from Feed blank space to any non-interactive shell target.

- [x] **Step 1: Update the UI source of truth**

Replace the system-only theme paragraph with the following behavior:

```md
Production exposes exactly two application color modes: dark and light. Dark is the default and preserves the current graphite appearance. A shared icon-only control at the top-right changes the browser-persisted mode; the HTML bootstrap restores the same sanitized preference before React starts, so reload does not flash the other mode. The mode is separate from the `graphite-purple` theme-family identifier so a future family can be added without changing this two-mode control.
```

Refine the Insights paragraph so an overlapping surface closes from any primary-pointer press whose target is outside Insights and has no interactive semantics. Require a 220 ms design-system exit that remains mounted, hidden, and inert until completion.

- [x] **Step 2: Add D053 and PLAN item 61 without duplicating the detailed UI rules**

Record why D048 is superseded: explicit user choice now wins over OS preference; dark remains the compatibility default; storage is browser-local and contains no account or server data; theme family and mode are separate.

- [x] **Step 3: Run all frontend acceptance in contract order**

Run:

```bash
npm run check:ui
npm run typecheck
npm test -- --run
npm run build
npm run lint
npx playwright test e2e/production-workbench.spec.ts
```

Expected: UI contract, TypeScript, all Vitest tests, production build/artifact scan, ESLint, and the 1440×900/1024×768/390×844 Playwright matrix pass. ESLint may report only existing Fast Refresh warnings and must report zero errors.

Result: UI contract、TypeScript、45 files / 365 Vitest tests、production build/artifact scan 与 ESLint（0 error、7 条既有 Fast Refresh warning）通过。新增主题/概览 Playwright 用例 2/2 通过；完整三视口套件为 33 passed、6 skipped、3 failed，三条失败均为既有 Feed 排序滚动断言，且在 detached `main@f38553b` 上同样 3/3 稳定失败，判定为基线缺陷而非本次回归。

- [x] **Step 4: Run repository completion gates**

Run:

```bash
python3 -m json.tool project-defaults.yaml >/dev/null
git diff --check
../../.venv/bin/python scripts/test_gate.py run --mode full
```

Expected: JSON and whitespace validation pass; full gate reports 22 commands passed, zero failed/error, `ui_impacted=true`, and no mapping miss.

Result: 配置 JSON 与 whitespace 校验通过；显式 full gate 为 22/22、0 failed/error、118.26 秒、无 mapping miss。功能提交已在运行门禁前落盘，因此 gate 的工作区差异摘要为 `changed_files=[]` / `ui_impacted=false`，但显式 full 模式仍执行了全部 22 条命令。

- [x] **Step 5: Append the mandatory concise WORKLOG entry**

Record the branch/base, changed interaction and theme behavior, focused/full/browser evidence, and that no API, database, scheduler, fetch, AI, paid provider, deployment, or runtime container was touched.

- [x] **Step 6: Self-review and commit the control-plane record**

Run:

```bash
rg -n "T[B]D|T[O]DO|implement la[t]er|appropriate error handl[i]ng|similar to T[a]sk" docs/superpowers/plans/2026-07-23-feed-insights-theme-toggle.md
git diff --stat
git status --short
```

Expected: no placeholders, only planned UI/test/control files changed, and generated build/test output remains ignored.

Then:

```bash
git add UI_CONTRACT.md DECISION_LOG.md PLAN.md WORKLOG.md docs/superpowers/plans/2026-07-23-feed-insights-theme-toggle.md
git commit -m "docs: record theme and insights interaction"
```
