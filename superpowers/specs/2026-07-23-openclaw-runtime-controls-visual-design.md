# OpenClaw Runtime Controls Visual Design

## Goal

Redesign the connected OpenClaw composer runtime controls so model and thinking level read like the compact peer selectors in Codex while remaining usable at the 320 px minimum Agent rail width.

## Current problem

The composer footer compresses model and thinking into one full-width sentence and opens a large compound dialog. The trigger hides the fact that the two values are independently selectable, the dialog adds a second nested model dropdown, and the button group for thinking has more visual weight than the send action.

## Considered approaches

1. **Two peer Select controls in the composer footer — chosen.** Model and thinking remain next to the send button, each value opens only its own menu, and both use the existing HeroUI selection semantics. This is the closest fit to the Codex reference and has the lowest interaction cost.
2. **Restyle the existing combined Popover.** This preserves the current component shape, but still hides two independent settings behind one trigger and retains the nested model control.
3. **Move runtime controls into the Agent header.** This creates more width, but separates per-send settings from the message composer and makes responsive Drawer and Bottom Sheet behavior less coherent.

## Approved design

- Replace the single `OpenClaw 运行设置：<model> · <thinking>` trigger with two adjacent selectors in the composer toolbar.
- The model trigger exposes `OpenClaw 模型：<name>` as its accessible name and shows only the verified active model name. Its upward menu lists model name plus provider and optional context-window metadata.
- The thinking trigger exposes `OpenClaw 思考程度：<label>` and shows `自动` when no explicit level is selected. Its upward menu contains `自动` plus only the active model's returned `thinkingLevels`.
- The model selector owns the flexible `minmax(0, 1fr)` track and truncates long names. The thinking selector owns an intrinsic non-shrinking track. The existing 36 px send/stop track remains unchanged.
- Triggers are borderless, transparent, compact controls with restrained semantic hover/open feedback, small chevrons, and existing focus rings. Menus use existing HeroUI surfaces and selected-item indicators; no new color, radius, shadow, typography, or dependency is introduced.
- While a request is running or runtime state is loading/updating, both selectors are disabled. A model without reasoning levels still exposes `自动` as the only choice and explains that no reasoning level is available.
- Selecting a model still calls the existing verified fork flow. Selecting thinking still changes only the per-request `chat.send.thinking` value. Runtime errors and blank-conversation fallback remain below the toolbar.

## Compatibility and boundaries

- No backend API, Gateway protocol, session persistence, model normalization, retry, permission, database, or deployment behavior changes.
- No global OpenClaw default is changed.
- Existing responsive Agent rail, Drawer, Bottom Sheet, context summary, input keyboard behavior, and send/stop control remain unchanged.
- `UI_CONTRACT.md` changes only from “one compact runtime control” to “two peer compact runtime controls”; D049's runtime safety decision remains authoritative.

## Verification

- Component tests prove separate accessible triggers, independent model/thinking selection, selected-state semantics, non-reasoning fallback, and narrow-toolbar geometry.
- Run the focused OpenClaw conversation test, TypeScript, UI contract check, lint, production build, and the repository full gate.
- Rebuild the local API/Worker from the feature branch only after checking active jobs and automatic schedules, then visually inspect the authenticated Agent panel at desktop and minimum-width layouts for clipping, focus, menu placement, and horizontal overflow.

