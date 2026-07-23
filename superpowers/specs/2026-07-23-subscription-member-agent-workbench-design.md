# Subscription, Member, and OpenClaw Workbench Design

## Goal

Simplify the visible subscription model to public/private, make member administration a responsive HeroUI table with password reset, replace obsolete Feed quick views with real subscription-scope views, and make Insights plus OpenClaw useful together on Feed and subscriptions.

## Product decisions

### Public and private subscriptions

The Service API and database keep `public | workspace | private` for compatibility. Production UI exposes only two user-facing groups:

- `public` and legacy `workspace` are presented and filtered as `公共订阅`.
- `private` is presented and filtered as `私人订阅`.

New administrator-created sources offer only `private` and `public`. Sharing a private source promotes it directly to `public`. Existing `workspace` rows remain readable and editable and are not migrated or rewritten.

### Feed quick views

The expanded and overlay navigation exposes exactly `全部`, `当天`, `公共订阅`, and `私人订阅`. It removes `未读`, `AI`, `朋友动态`, and `产品机会`.

Feed preference gains an additive `subscriptionScope: all | public | private`. The public view includes items whose canonical or provenance source IDs map to a `public` or `workspace` catalog source. The private view includes items mapped to a `private` source. `全部` and `当天` clear this scope. Manual source/channel/topic filters remain available and clear or coexist predictably through the existing preference model.

### Member administration

The create-member form stays above the list. The list becomes a HeroUI `Table` with columns for member identity, role, account status, and actions. The table is horizontally scrollable on narrow screens without creating page-level overflow.

Owner rows remain protected. Owner/Admin can change non-owner roles, enable or disable non-owner accounts, and open a reset-password dialog. Reset requires a new password and confirmation, enforces the existing 8-character minimum, and sends `PATCH /api/users/{id}` with `password`. Passwords are never shown again or persisted in client state after completion.

### Insights and Agent coexistence

On dock-capable desktop, a fixed Agent rail and the floating Insights card may be open at the same time. Insights stays offset from the current Agent width. The shell measures the Insights card against the reading frame and records whether the card obstructs Feed content.

When obstruction exists, a pointer activation on a non-interactive blank Feed region closes Insights while leaving Agent open. Card content, controls, links, dialogs, selections, and scroll interactions never trigger this dismissal. When no obstruction exists, blank-region activation leaves Insights open. Tablet overlays and mobile bottom sheets remain mutually exclusive.

### OpenClaw context usage

The Agent header gains a `上下文用量` control that opens a compact information popover. It shows:

- active model;
- trustworthy used tokens and context capacity;
- percentage pressure with a semantic progress presentation;
- current Inteliscope attachments as `N / 8`.

The browser uses its already-known Inteliscope session key. After session activation it performs one exact-key `sessions.list` read, calls `sessions.subscribe`, and merges matching `sessions.changed` events. It never adopts or guesses another session. `totalTokens` is shown only when positive and not explicitly stale (`totalTokensFresh !== false`); `contextTokens` must also be positive. Missing, stale, malformed, or mismatched data renders `暂无可信用量` rather than a client estimate. Disconnect, device forgetting, new conversation, and session switch clear or replace the usage snapshot.

### Agent on subscriptions

`/subscriptions` is Agent-capable but not Insights-capable. Its PageHeader exposes the same Agent toggle and uses the same dock/Drawer/bottom-sheet behavior as reading routes. Subscription run-record context opens Agent in place; it no longer navigates to `/feed`. The shared context draft remains isolated by Inteliscope user and browser tab.

## Architecture

- `subscriptionModel.ts` owns the public/private presentation mapping and scope predicates.
- `feedPreference.ts`, `workbenchQuickViews.ts`, and `HeroWorkbenchPage.tsx` own persisted Feed scope selection and item filtering.
- `HeroUsersPage.tsx` owns the member table and reset dialog while reusing the existing Service API.
- `HeroWorkbenchShell.tsx` owns route capability, panel coexistence, obstruction measurement, and safe blank-region dismissal.
- `useOpenClawChat.ts` owns session-usage acquisition and normalization; `OpenClawConversation.tsx` only renders the usage popover.

No new backend endpoint, database migration, model call, source fetch, scheduler action, or production rollout is part of this change.

## Error and accessibility behavior

- Catalog-loading failure never applies an incorrect public/private filter; the Feed shows an explicit degraded state for the requested scope.
- Password mismatch is local and focus remains in the dialog; API failure preserves the dialog input for correction; success clears and closes it.
- Table columns use semantic headers and action labels name the target member.
- The context-usage control exposes text equivalents for every value and remains useful without color.
- Popovers and dialogs restore focus to their trigger. Escape behavior and active-generation pinning remain unchanged.
- Reduced Motion, narrow viewport overflow, and existing user-isolation rules continue to apply.

## Verification

1. Unit tests cover public/private source mapping, persisted scope sanitization, quick-view detection, provenance filtering, and OpenClaw usage normalization.
2. React tests cover the exact quick-view labels, HeroUI table semantics, password reset payload/validation, subscription-page Agent behavior, context-usage states, and conditional blank-click dismissal.
3. UI contract and TypeScript checks pass.
4. The full repository gate passes.
5. Playwright verifies `/feed`, `/subscriptions`, and `/users` at 1440×900, 1024×768, and 390×844 with no serious accessibility findings or horizontal page overflow.
