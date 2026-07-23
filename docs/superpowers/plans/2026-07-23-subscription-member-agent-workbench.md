# Subscription, Member, and OpenClaw Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify subscription visibility to public/private, move member administration to a HeroUI table with password reset, and make the Feed/OpenClaw workbench behave consistently across Feed and subscription configuration.

**Architecture:** Preserve the existing backend `public | workspace | private` compatibility model while projecting `public + workspace` as public in the React UI. Keep Feed scope preferences client-side and resolve source membership from the authenticated source catalog. Extend the existing OpenClaw session connection with exact-current-session usage telemetry; do not adopt or infer another session. Keep Insights and Agent independently open, dismissing Insights from Feed blank space only when its measured rectangle obstructs Feed content.

**Tech Stack:** React 19, TypeScript, HeroUI v3, TanStack Query, Vitest/Testing Library, OpenClaw Gateway WebSocket RPC, Playwright, Python test gate.

## Global Constraints

- Do not migrate or rewrite existing source rows; legacy `workspace` remains readable and is rendered as public.
- Do not change Service database schema, fetching, scheduler, scoring, or personal-tag behavior.
- Never use `sessions.list` to discover or adopt a historical OpenClaw session; telemetry lookup must exact-match the already-known current session key.
- Do not estimate context usage in the browser. Show usage only when the Gateway marks totals fresh and provides a positive context capacity.
- Preserve owner protection, user isolation, and existing self-password behavior.
- Preserve unrelated dirty control-file edits.

---

### Task 1: Collapse subscription visibility and add Feed public/private quick views

**Files:**
- Modify: `frontend/src/features/subscriptions/subscriptionModel.ts`
- Modify: `frontend/src/features/admin-heroui/HeroSubscriptionsPage.tsx`
- Modify: `frontend/src/features/feed/feedPreference.ts`
- Modify: `frontend/src/features/feed/feedModel.ts`
- Modify: `frontend/src/features/workbench-live/workbenchQuickViews.ts`
- Modify: `frontend/src/features/workbench-live/HeroWorkbenchPage.tsx`
- Modify: matching Vitest files

**Interfaces:**
- Produces: UI visibility `public | private`, where stored `workspace` belongs to UI-public.
- Produces: `FeedPreference.subscriptionScope: 'all' | 'public' | 'private'` with backward-compatible default `all`.
- Produces: quick views `全部`, `当天`, `公共订阅`, `私人订阅`.

- [ ] Add failing model/preference/quick-view tests covering legacy workspace folding and persistence migration.
- [ ] Add failing Feed filtering tests covering canonical and provenance source identifiers.
- [ ] Implement visibility projection helpers and remove team controls from subscription creation/filter/share UI.
- [ ] Implement source-catalog-backed Feed scope filtering and inspectable scope filter controls.
- [ ] Run targeted subscription and Feed Vitest suites.

---

### Task 2: Render member administration with HeroUI Table and password reset

**Files:**
- Modify: `frontend/src/features/admin-heroui/HeroUsersPage.tsx`
- Modify: `frontend/src/app/App.test.tsx`

**Interfaces:**
- Consumes: existing `PATCH /api/users/{id}` optional `password` field.
- Produces: responsive HeroUI member table with identity, role, status, and actions columns.
- Produces: non-owner reset-password dialog with confirmation and minimum-eight-character validation.

- [ ] Add failing application tests for table semantics, owner protection, reset validation, and reset request.
- [ ] Replace free-form member cards with HeroUI Table while preserving role/status mutations.
- [ ] Add isolated reset dialog state and mutation feedback.
- [ ] Run the targeted application tests and TypeScript check.

---

### Task 3: Make Insights and Agent coexist with obstruction-aware dismissal

**Files:**
- Modify: `frontend/src/features/workbench-live/HeroWorkbenchShell.tsx`
- Modify: `frontend/src/features/workbench-live/HeroWorkbenchPage.tsx`
- Modify: `frontend/src/features/workbench-live/HeroWorkbenchShell.test.tsx`

**Interfaces:**
- Produces: independent desktop Insights and fixed Agent visibility.
- Produces: measured `insightsObstructsFeed` state.
- Produces: blank Feed activation that closes Insights only while obstruction exists.

- [ ] Add failing shell tests for simultaneous surfaces and both blank-click branches.
- [ ] Measure actual Feed/Insights rectangles after layout changes.
- [ ] Mark Feed blank/card regions and implement interaction-safe dismissal.
- [ ] Run targeted workbench tests at desktop and compact layout assumptions.

---

### Task 4: Add trustworthy OpenClaw context telemetry and enable Agent on subscriptions

**Files:**
- Modify: `frontend/src/features/openclaw/useOpenClawChat.ts`
- Modify: `frontend/src/features/openclaw/OpenClawConversation.tsx`
- Modify: `frontend/src/features/workbench-live/HeroWorkbenchShell.tsx`
- Modify: `frontend/src/features/admin-heroui/HeroSubscriptionsPage.tsx`
- Modify: matching Vitest files

**Interfaces:**
- Consumes: exact-key `sessions.list`, `sessions.subscribe`, and exact-key `sessions.changed` fields `totalTokens`, `totalTokensFresh`, and `contextTokens`.
- Produces: OpenClaw context popover with model, used/max tokens, percentage, and selected-context `N/8`.
- Produces: Agent rail/drawer on `/subscriptions`; adding run context opens the local composer without navigating to Feed.

- [ ] Add failing projection/event tests for fresh, stale, mismatched, and absent usage.
- [ ] Load and subscribe to exact-current-session usage across connect/switch/new-session flows.
- [ ] Render accessible context usage details with a trustworthy unavailable state.
- [ ] Extend workbench route capability to subscriptions and remove forced Feed navigation.
- [ ] Run targeted OpenClaw, workbench, and subscription tests.

---

### Task 5: Update contracts and complete verification

**Files:**
- Modify: `UI_CONTRACT.md`
- Modify: `API_CONTRACT.md` only if the browser/Gateway protocol contract needs clarification
- Modify: `DECISION_LOG.md`
- Modify: `PLAN.md`
- Modify: `WORKLOG.md`

- [ ] Record the two-scope UI projection, quick-view set, Insights dismissal rule, subscription Agent capability, and exact-session telemetry rule in their authoritative contracts.
- [ ] Append a decision entry and concise worklog without overwriting existing dirty changes.
- [ ] Run targeted frontend tests, typecheck, lint, and build.
- [ ] Run `python scripts/test_gate.py run --mode full` and `git diff --check`.
- [ ] Rebuild the latest local service and visually verify `/feed`, `/subscriptions`, and `/users` in three viewport classes.

