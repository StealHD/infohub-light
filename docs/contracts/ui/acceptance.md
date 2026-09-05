## 9. Enforcement and acceptance

This file is the sole production UI review checklist. It verifies the laws owned by the UI README, Interaction Constitution, component matrix, and route contracts; it does not redefine them.

Composer shortcuts acceptance additionally covers both Feed and workspace TextAreas: caret-middle insertion, IME, disabled and duplicate Skills, read failure/retry, generation races, source-snapshot exclusion, selection without send, send-time revalidation and retry snapshots. Controlled Gateway browser fixtures must prove no real Gateway writes, new/Worktree cancellation, inline command output without dialogs or nested Skills menus, exact command Send/Enter parity, scoped local results excluded from chat payload/history, inline model/reasoning and Worktree confirmations, route-preserved Skill drafts, 320 px rail and mobile viewport bounds, keyboard focus, Reduced Motion, themes and Axe with the menu open.

### 9.1 Required gate order

Every production UI change must pass, in order:

1. Static UI contract checks, product-documentation merge maintenance, and ESLint import restrictions.
2. TypeScript and affected Vitest specs.
3. Vite production build and artifact scan proving no MUI/Emotion modules, `Mui` class markers, deleted preview routes, or deleted comparison copy.
4. Mapped Playwright at 1440×900, 1024×768, and 390×844, including persisted manual dark/light choices, Reduced Motion, and Axe with zero serious or critical findings.
5. The repository's impacted preflight after the task-scoped diff is reviewed.

### 9.2 Interaction stability checklist

For every changed asynchronous action:

- Measure the same control in idle, immediate pending, settled success, and recoverable failure. Idle/pending border-box width and height differ by no more than 1 CSS px per axis.
- Verify loading text or icon state does not move adjacent controls or change its card/form geometry unless the affected content region is intentionally disclosed.
- Activate twice rapidly with pointer and keyboard. Only one request is accepted; pending is synchronously non-repeatable and exposes `aria-busy`.
- For refresh/retry, confirm the original icon and the role's visible or accessible label stay mounted, the icon rotates in the same box, and Reduced Motion stops rotation without removing busy/disabled feedback.
- Retain references to the logical form, card, and action node before activation. After save/refresh/retry settles, each remains connected and is the same node unless the operation intentionally removed it or navigated away.
- Verify focus, selection, scroll position, expanded state, and unsaved inputs remain stable. Failure restores a safe action and shows a specific local recovery path.
- Confirm neither state correctness nor cleanup depends only on `animationend` or `transitionend`.

### 9.3 Responsive, hierarchy, and state checklist

- Reuse the nearest component role and semantic type/spacing/icon/motion tokens; do not approve a local number merely because it resembles an external reference.
- Exercise Loading, Empty, Error, Degraded, Read-only, and terminal feedback states that the changed surface can reach. They use the existing shared vocabulary, correct live-region semantics, and an actionable recovery path where appropriate.
- Test unpredictable long copy, identifiers, URLs, translated labels, and tag collections. Flex/grid text children shrink, long tokens wrap deliberately, essential content remains available, and no viewport gains horizontal overflow.
- Verify nearby/collision-aware Tooltip geometry, keyboard focus visibility/restoration, independent scrolling, sidebar/Agent track continuity, stable ID-plus-offset anchors where required, explicit Feed top resets after sort changes, and bounded virtualization.
- Verify dark/light at all three viewports. At 200% browser zoom or equivalent narrow reflow, action/error/safety text is not clipped. Reduced Motion reaches the same final semantic state without nonessential motion.
- Run Axe with zero serious or critical findings and complete every changed action with keyboard only.

### 9.4 Route additions

- Any OpenClaw Workspace change verifies `/agent`, `/agent/tasks`, `/agent/artifacts`, `/agent/skills`, and `/agent/automations` at 1440×900, 1024×768, and 390×844 plus 200% zoom. It proves product switching restores the latest allowlisted per-user route, ordinary socket/session/run/draft survive Inscope ↔ OpenClaw and Feed → `/agent`, the 288 px sidebar and on-demand 360 px inspector follow the Drawer/Sheet contract, Tasks/Artifacts do not unmount conversation, current-run session switching is blocked, every unsupported/forbidden/failure state remains local, and no route has horizontal overflow. Admin checks prove authorization appears only on write intent, successful authorization does not replay the write, exact temporary scope, zero persistent secret/chunk/response writes, explicit trust-domain and write confirmation, close/unmount/idle cleanup, and isolation from ordinary chat events. Artifact checks cover preview/download limits, same-origin expiry, UTF-8 failure, and object-URL revoke; Axe has zero serious/critical findings in both themes and Reduced Motion.
- Any source-setup change additionally verifies `/subscriptions` at desktop and 390 px: X/Instagram/YouTube are peer options; unavailable platforms expose no submit action; ready platform forms contain no Apify/Actor/Route/Key/support-check or advanced-JSON text; edit locks preserve metadata fields and focus; the dialog and page have no horizontal overflow.
- Any ActorOps resilience change additionally verifies `/settings/actorops` at desktop and 390 px across `主备配置 / 来源启用 / 运行与告警`: compatibility risk and 1/3 confirmation, source soft preference, 6–168-hour/disabled freshness authorization, manual-cost confirmation, dedicated-Key blocking, persistent failure memory/retry-once, diagnostic filters, long-reason wrapping, dialog focus restoration, and zero horizontal overflow. `/settings/secrets` must show acquisition/validation roles without exposing a Key value.

### 9.5 Static enforcement boundary

The static contract rejects MUI/Emotion imports, production feature-level direct HeroUI imports, nested `DesignSystemProvider` mounts, raw business-page colors, page-level visual constants, business-owned copies of the approved PageFrame widths, and deleted preview technology. Interaction checks are added only when a narrow source rule has positive and negative fixtures and does not reject legitimate list keys, non-button state copy, or non-interactive refetch orchestration. Snapshot or expectation changes require an intentional contract change; they are not an automatic response to a failing visual test.
