# Inteliscope UI Interaction Constitution

## 1. Authority and scope

This document is the sole source of truth for cross-route production UI interaction stability. It governs React production surfaces, shared design-system patterns, asynchronous actions, state transitions, focus continuity, responsive reflow, and motion accessibility.

Authority is resolved in this order:

1. `AGENTS.md` defines project hard constraints and authorization boundaries.
2. This Constitution defines cross-route interaction behavior.
3. `component-parameters.md` defines component roles, dimensions, spacing, typography, icons, and motion tokens.
4. A route contract may add a narrowly scoped behavior required by that route, but may not silently weaken this Constitution.
5. `acceptance.md` verifies the laws; `frontend/scripts/check-ui-contract.mjs` enforces the statically decidable subset.

External references are non-authoritative evidence. The analyzed UI UX Pro Max revision is fixed at [`40d8b6facf46677f86e8c0e5d4c6f77c137c9888`](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/commit/40d8b6facf46677f86e8c0e5d4c6f77c137c9888); later upstream changes do not alter this contract. A disagreement with current law must be presented to the user with evidence and impact before the law changes.

`MUST`, `MUST NOT`, `SHOULD`, and `MAY` are normative. Rule identifiers are stable review and test references.

## 2. Interaction invariants

### UI-INT-01 — Stable external geometry

- An asynchronous state transition MUST NOT change an action control's outer border-box width or height unless resizing is the explicit user-requested interaction.
- Idle, pending, success, and failure content MUST be planned before the request starts. Text, icon, spinner, and status changes MUST NOT push adjacent controls, labels, cards, or page content.
- A shared async control SHOULD place its idle and pending contents in the same grid track and let both participate in intrinsic size calculation. Only the active layer is perceivable; the inactive layer is visually hidden and removed from the accessibility tree, not removed from size calculation.
- Browser acceptance allows at most 1 CSS px difference per axis between measured idle and pending border boxes to account for fractional layout rounding.
- A progress disclosure, expanding details panel, navigation, or destructive removal MAY intentionally change surrounding geometry. It is not an exception for a button itself to jitter.
- Persistent navigation MUST keep row positions, dimensions and scroll position stable through pointer press, keyboard activation, pending and settled selection. Pending feedback MUST NOT insert temporary in-flow blocks above navigation. Selection alone MUST NOT reorder the visible collection; actual activity, creation, deletion or revealing an off-list item may update membership. Browser acceptance MUST measure both pending and settled geometry, with normal and Reduced Motion, rather than checking only the final screenshot.

### UI-INT-02 — Single in-flight action

- An action MUST become non-repeatable synchronously when it accepts work. The pending latch MUST not wait for the remote query library to render a later state.
- Pending actions MUST expose `aria-busy="true"` and MUST disable the trigger or otherwise make repeat activation impossible for pointer, touch, and keyboard input.
- The latch MUST cover the complete accepted operation, including joined refetches or invalidations that determine completion. It MUST be released after success, handled failure, synchronous throw, or rejected promise.
- Rapid double activation MUST produce at most one accepted mutation or refresh request. Disabling only the visual style is insufficient.

### UI-INT-03 — Stable async copy and feedback

- Loading copy MUST NOT be the mechanism that reserves size after the request begins. If pending copy differs from idle copy, the control MUST reserve the larger state in advance or use a stable minimum inline size owned by the component role.
- A pending control MUST keep an understandable accessible name. A generic spinner with no named operation is not sufficient.
- Persistent validation, degraded capability, and recoverable error feedback stays with the affected field, form, card, dialog, or page region. Terminal global action results use the existing Toast queue and do not enter normal document flow.
- Failure MUST restore the action when retry is safe and provide a specific recovery path. Success MUST not erase the user's current context merely to display confirmation.

### UI-INT-04 — Refresh and retry identity

- A refresh or retry control MUST keep its original refresh/retry icon and, when its component role has one, its visible label while the request is pending. An existing icon-only role keeps the same accessible name and Tooltip. Pending MUST NOT replace the icon with an unrelated loader glyph or replace any label with wider loading copy.
- During pending, the same icon rotates in place on the same visual track. The icon box, label track, gap, padding, and control geometry remain fixed.
- Explicit refresh/retry controls SHOULD keep the busy feedback perceivable for at least 400 ms after an accepted activation, while never delaying the underlying request. The busy state ends only after the internal latch, the actual request, and any externally owned fetching state have all completed.
- Under `prefers-reduced-motion: reduce`, rotation MUST stop. Disabled and `aria-busy` feedback, the original icon, and the role's visible or accessible label remain, so state meaning never depends on motion.
- An operation whose meaning is stop, cancel, regenerate, rotate a credential, or switch mode is not renamed to refresh merely because it obtains new data.

### UI-INT-05 — Preserve DOM identity and user context

- Saving, refreshing, retrying, polling, invalidating, or receiving a newer generation MUST update the smallest owned region. It MUST NOT remount an entire form, card, dialog, route, or provider to force fresh data.
- A form or single-record card MUST NOT use a `key` derived from data, configuration, version, generation, timestamp, request count, or loading state. Collections continue to use stable business identifiers for item keys.
- The same logical form, card, and action SHOULD remain the same DOM nodes across a successful local async transition. Controlled values may reconcile in place after the server response.
- Focus, selection, scroll position, expanded/collapsed intent, and unsaved input MUST remain stable unless the accepted action necessarily removes the focused object or navigates away.
- Business correctness MUST NOT depend on `animationend` or `transitionend`. Motion completion can clean up a visual layer only when a timeout or immediate Reduced Motion path reaches the same final semantic state.

### UI-INT-06 — Smooth side-panel disclosure

- Docked side panels MUST animate occupied width together with restrained opacity/translation, using the shared disclosure pattern and motion tokens. Overlay Drawers/Sheets use the corresponding shared surface transition.
- Opening, closing and rapid reversal MUST preserve the center conversation DOM, draft and scroll context. Exiting content may remain mounted for the bounded visual transition, but MUST become inert and leave the accessibility tree immediately.
- Closing from within the panel MUST restore the initiating control's focus. Reduced Motion reaches the final state immediately; cleanup MUST have a timer or equivalent fallback rather than depend exclusively on a transition event.

## 3. State vocabulary

### UI-STATE-01 — Local loading

- Initial loading uses the existing fixed-geometry `LoadingState`, `LoadingReveal`, or route-owned skeleton pattern that approximates final geometry. Refreshing existing content keeps readable content mounted and marks only the affected region busy.
- Near-instant work SHOULD avoid a flashing page-level indicator. A user-initiated action still needs immediate local pressed/disabled feedback.
- The project keeps its calm opacity loading language. Do not introduce traveling shimmer or a second skeleton vocabulary.

### UI-STATE-02 — Empty, error, degraded, and read-only

- Empty state explains what is absent and, when the user can act, offers the nearest safe next action through `EmptyState` or the route's existing shared pattern.
- Recoverable error state names the failed region and offers a retry or corrective path. The retry follows UI-INT-02 and UI-INT-04.
- Degraded and read-only states preserve available content, explain the limitation, and disable only unavailable actions. They do not impersonate an empty state or replace the whole page with a generic failure.
- Loading, empty, error, degraded, read-only, and success status MUST use existing semantic colors, icon roles, live-region behavior, and shared components. A route MUST NOT create private status styling.

## 4. Responsive content stability

### UI-LAYOUT-01 — Shrinkable text children

- Any flex or grid child containing unpredictable text, identifiers, URLs, translated copy, or user content MUST be able to shrink with `min-width: 0` or the equivalent layout guarantee.
- Unbroken identifiers and URLs MUST use a deliberate wrapping strategy such as `overflow-wrap: anywhere`. Global `word-break: break-all` on ordinary prose is forbidden.
- Text remains available under narrow widths, zoom, and user text-spacing overrides. Fixed heights MUST NOT clip action labels, errors, safety text, or distinguishing names.

### UI-LAYOUT-02 — Compact collections and truncation

- Compact tags, filters, and editable value collections SHOULD wrap. A bounded single-line collection MAY use an operable `+N` disclosure; it MUST NOT silently hide values.
- Essential headings, action labels, validation errors, safety copy, and record names MUST remain fully accessible. If visual truncation is necessary, a keyboard-, pointer-, and touch-operable path reveals the full value; a hover-only tooltip or HTML `title` is insufficient.
- A compact label SHOULD remain on one line when practical, while its containing row can wrap or stack without horizontal overflow.

### UI-LAYOUT-04 — Control-local containment

- Page-level horizontal overflow checks alone MUST NOT count as containment acceptance. At each supported narrow panel width and zoom/reflow state, verify value, indicator, action and container rectangles independently.
- Selected text MUST have a shrinkable, bounded region separate from the indicator/action region. Long unbroken identifiers MUST NOT paint beneath an arrow, dismiss button, sibling column or panel edge. Reserve indicator space in the shared component, not ad-hoc feature offsets.
- If a compact value is truncated, opening the control with keyboard or touch MUST expose its complete value with wrapping inside the bounded overlay. The indicator remains visible and operable. Closing restores trigger focus.
- Docked inspectors MUST reflow headings, descriptions and selectors according to their own available width, even when the viewport is desktop-wide. Hiding overflow on an ancestor is not a substitute for correcting the child layout.

### UI-LAYOUT-03 — Existing hierarchy and density

- Spacing, density, typography hierarchy, breakpoints, page widths, target sizes, radii, icons, colors, and motion durations MUST come from the existing semantic roles and tokens in `component-parameters.md` and `frontend/src/design-system/**`.
- External reference values do not create local tokens. New reusable values require a contract change, a design-system owner, and a test; a route-specific behavioral measurement must be justified in its route contract.

## 5. Accessibility and motion

### UI-A11Y-01 — Focus and semantics

- Every operable control has a native or equivalent role, an accessible name, keyboard operation, and a visible focus indicator. Visual and DOM order remain coherent.
- Async status uses one contextual live message for the affected operation; competing live regions or bare changing numbers are avoided.
- Sticky headers, overlays, drawers, and docked Agent surfaces MUST NOT fully obscure keyboard focus. Dialog and popover close behavior restores focus to the initiating control when that control still exists.

### UI-A11Y-02 — Reduced Motion

- Every nonessential transition or animation MUST have a Reduced Motion outcome that is effectively immediate or static while preserving the final readable state.
- Motion MUST NOT be the only indication of pending, success, error, selection, expansion, or navigation. No business state waits exclusively for an animation event.
- Existing `animate-spin` usage requires an explicit `motion-reduce:animate-none` counterpart. New motion uses the shared design-system duration tokens rather than literals.

## 6. Enforcement and exceptions

- Static enforcement belongs only in `frontend/scripts/check-ui-contract.mjs`, with positive and negative fixtures in `frontend/src/design-system/uiContract.test.ts`. A checker rule MUST be narrow enough not to reject stable list keys, semantic state copy outside buttons, or legitimate query refetches outside action handlers.
- Geometry, DOM identity, double-activation, focus, and scroll continuity are browser-observable and belong in focused Vitest/Playwright tests described by `acceptance.md`.
- A route exception requires an explicit user-approved contract change that names the rule, affected surface, reason, bounded behavior, accessibility fallback, and verification. An implementation comment or snapshot update is not an exception.
- Until a rule has safe static coverage, it remains binding through component review and browser acceptance. Do not add a broad regex merely to claim enforcement, and do not report compliance while known production violations remain.

## 7. Rule maintenance

- Add a cross-route interaction behavior here.
- Add or change numerical/component parameters only in `component-parameters.md` and the owning design-system implementation.
- Add a page-specific exception or behavior only in that route contract.
- Add verification wording only in `acceptance.md`; add mechanically decidable checks and fixtures to the existing checker/test pair.
- Change this Skill only when discovery, read order, external reference routing, or verification entrypoints change.
- Record the reason, compatibility impact, absorbed evidence, and rejected alternatives in `docs/decisions/` whenever rule meaning changes.
