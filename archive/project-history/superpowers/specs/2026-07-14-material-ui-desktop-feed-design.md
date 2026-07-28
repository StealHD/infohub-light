# Material UI Desktop Feed Design

Implementation status: phase-one Shell and shared Feed workspace are locally implemented and automated verification is complete. Phase-two subscription/settings migration remains blocked on explicit visual approval of the four Feed baselines.

## Outcome

Rebuild the default React Service UI shell and the shared `/feed`, `/later`, and `/history` workspace with Material UI. The approved direction is **Material You Intelligence Cabin**: green tonal surfaces, rounded panels, a collapsible navigation rail, balanced list density, and a decision-brief reader.

The previous editorial mockup and the other Material UI explorations remain stored under `.superpowers/brainstorm/9290-1783993554/content/`. They are references only. `material-ui-directions.html` contains the chosen A direction; `desktop-feed-final.html` preserves the earlier editorial integration.

## Architecture

- Add Material UI v9, Emotion, Material icons, Fontsource Noto Sans SC, and Axe Playwright support.
- Add a single UI provider and theme with CSS variables prefixed `--inteliscope-*`.
- Own theme and reusable presentation under `frontend/src/ui/**`; feature components consume approved internal exports rather than creating new visual primitives.
- Keep TanStack Query keys, service APIs, permission checks, routes, optimistic updates, and legacy UI fallback unchanged.
- Keep subscription, settings, and login page bodies on their current styles during this phase.

## Shell behavior

- Default collapsed 72 px Drawer, expandable to 240 px.
- Persist `collapsed|expanded` per user in browser local storage.
- Use permanent layout expansion at desktop widths and temporary overlay expansion from 900–1199 px.
- Preserve the current mobile bottom navigation at 767 px and below.
- Present acquisition progress and failures with Snackbar + Alert without hiding retry or failed-source navigation.

## Feed behavior

- Keep `mode` and `item` URL semantics.
- Use Tabs for Feed modes; show unread-first and active filters; place the remaining filters in an immediate-apply Popover.
- Target 6–8 visible rows at 1440×900.
- Show a single summary in the reader and remove the duplicate AI-summary section.
- Keep open-original, read-later, and save visible; move mark-read, copy-summary, and dismiss into a More menu.
- Preserve viewer read-only behavior and current optimistic cache rollback.
- Add explicit Skeleton, retry Alert, empty/reset, and missing-data states.

## Acceptance

- No backend, database, API payload, query-key, or permission changes.
- No horizontal overflow at supported viewports.
- Sidebar state remains isolated by user and survives reloads.
- At least six list items are visible at 1440×900.
- Reader summary appears once.
- Keyboard navigation, focus return, reduced motion, and Axe serious/critical checks pass.
- Existing mobile list/detail flow continues to pass.
