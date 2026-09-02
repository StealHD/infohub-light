---
name: inteliscope-ui
description: Implement or review Inteliscope production React UI, interaction, responsive, accessibility, or design-system changes under the repository UI Contract. Do not use for backend-only work or the fixed-data HeroUI preview unless the request also changes production UI law.
---

# Inteliscope UI

Treat the repository UI Contract as law. External design material is evidence only and never changes the contract by itself.

## Read in this order

1. Read the applicable `AGENTS.md` and `PLAN.md`.
2. Read `docs/contracts/ui/README.md`.
3. Read `docs/contracts/ui/interaction-constitution.md` for cross-route behavior.
4. Read `docs/contracts/ui/component-parameters.md` for roles and numerical parameters.
5. Read only the route contract linked by the UI README for the affected surface.
6. Read `docs/contracts/ui/acceptance.md` before choosing tests or declaring completion.

Then inspect the nearest production component, its tests, `frontend/src/design-system/**`, and `frontend/scripts/check-ui-contract.mjs`. Reuse an existing role before adding a parameter or pattern. Production feature code imports UI primitives through the design-system boundary.

## Make changes

- Preserve interaction stability, DOM identity, pending-state exclusion, recovery, focus, responsive reflow, and Reduced Motion as defined by the Interaction Constitution.
- Put reusable behavior in `frontend/src/design-system/**`; do not create a route-local substitute for a shared role.
- Put interaction law in the Constitution, component geometry in the component matrix, and a route exception in its route contract. Put verification steps in acceptance and executable checks in the existing checker with positive and negative fixtures.
- Do not duplicate a rule across documents. Cross-reference its rule identifier or authoritative section.
- If existing law appears incorrect, do not silently override it. Show the user the current rule, concrete conflict or failure, expected impact, and proposed replacement; wait for the user's decision before changing the law.

## External reference boundary

The optional upstream textbook is [UI UX Pro Max Skill at commit `40d8b6f`](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/commit/40d8b6facf46677f86e8c0e5d4c6f77c137c9888). Consult that fixed revision only when the user asks for UI research or the current contract has a genuine gap. Do not copy its catalogs, tokens, templates, breakpoints, dependencies, or style presets into this repository. Upstream updates require a new explicit review and decision.

## Verify

During implementation, run the smallest relevant Vitest or Playwright spec plus:

```bash
cd frontend && npm run check:ui
cd frontend && npm run typecheck
```

At task completion, follow the repository snapshot and impacted-preflight policy. UI contract changes also require the control-plane validators in `AGENTS.md`. When this Skill changes, validate it with the bundled `skill-creator/scripts/quick_validate.py`.
