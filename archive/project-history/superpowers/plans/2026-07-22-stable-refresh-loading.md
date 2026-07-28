# Stable Refresh Loading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make refresh show the existing application shell immediately, use dimensionally stable Feed and Agent skeletons, and reveal only loaded content without replaying a page entrance.

**Architecture:** A route-aware static boot shell is painted from `index.html` before React and handed off without opacity animation after authentication settles. Initial Feed and Agent queries use workbench-specific fixed geometry inside a shared local reveal primitive; navigation, header, grid columns, and background never participate in the data transition.

**Tech Stack:** React 19, TypeScript, HeroUI v3, Tailwind CSS v4, TanStack Query/Virtual, Vitest, Playwright.

## Global Constraints

- Preserve the 52px header, 820px reading width, 72px/232px navigation widths, and 360px desktop Agent column.
- Skeleton breathing uses a restrained 1400ms pulse with no shimmer.
- Skeleton exit is 120ms; content reveal is 200ms from `translateY(4px)`.
- Reduced Motion removes breathing, fading, and displacement without hiding loading state.
- Background refetches retain current content and do not replay skeletons or reveals.
- Do not change backend APIs, query keys, authentication semantics, or Feed payloads.

---

### Task 1: Stable first-paint shell

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/AppBootstrap.test.tsx`
- Modify: `frontend/src/app/App.tsx`
- Create: `frontend/src/app/bootstrapShell.ts`
- Create: `frontend/src/app/bootstrapShell.test.ts`
- Create: `frontend/src/design-system/bootstrap.css`

- [ ] Write failing tests for the route-aware boot markup, safe snapshot persistence, logout cleanup, and settled-React release boundary.
- [ ] Run the targeted Vitest tests and confirm failures describe the missing boot shell behavior.
- [ ] Add the critical shell markup/CSS and snapshot helpers; synchronously import the production bootstrap and release the static overlay in a layout effect only after a settled route is committed.
- [ ] Run the targeted tests and confirm the first-paint behavior passes.

### Task 2: Fixed workbench skeletons and reveal primitive

**Files:**
- Modify: `frontend/src/design-system/patterns.tsx`
- Modify: `frontend/src/design-system/patterns.test.tsx`
- Modify: `frontend/src/design-system/theme.css`
- Modify: `frontend/src/design-system/index.ts`
- Create: `frontend/src/features/workbench-live/WorkbenchLoadingState.tsx`
- Create: `frontend/src/features/workbench-live/WorkbenchLoadingState.test.tsx`
- Modify: `frontend/src/features/workbench-live/HeroWorkbenchPage.tsx`
- Modify: `frontend/src/features/workbench-live/HeroWorkbenchShell.tsx`
- Modify: `frontend/src/features/workbench-live/VirtualFeed.tsx`

- [ ] Write failing tests for five 156px Feed rows, fixed Agent placeholders, a nonzero ViewBar count placeholder, calm 1400ms pulse, and the 120ms/200ms/4px local reveal contract.
- [ ] Run the targeted Vitest tests and verify they fail for missing components and motion markers.
- [ ] Implement `LoadingReveal`, calm Skeleton styling, workbench-specific skeletons, and shared layout estimates.
- [ ] Replace only initial Feed/Agent loading branches; keep cached/background-refresh content mounted.
- [ ] Run the targeted tests and confirm the local state transitions pass.

### Task 3: Browser acceptance and contract

**Files:**
- Modify: `frontend/e2e/design-system-contract.spec.ts`
- Modify: `frontend/e2e/production-workbench.spec.ts`
- Modify: `UI_CONTRACT.md`
- Modify: `DECISION_LOG.md`
- Modify: `WORKLOG.md`

- [ ] Add delayed-auth and delayed-data Playwright coverage for immediate shell geometry, width stability within 1px, exact animation timings, no root animation, and Reduced Motion.
- [ ] Run the focused Playwright tests at 1440x900, 1024x768, and 390x844.
- [ ] Record the visual contract and decision without changing API or architecture ownership.
- [ ] Run UI contract, lint, typecheck, Vitest, production build, and the repository full gate.
- [ ] Append the compact worklog evidence and commit the implementation in reviewable units.
