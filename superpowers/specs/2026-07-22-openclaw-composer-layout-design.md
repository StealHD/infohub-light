# OpenClaw Composer Layout Design

## Goal

Keep the connected OpenClaw composer visually calm and usable inside the existing 320–720px Agent rail without widening the rail or reducing Feed space.

## Root cause

The message field already owns a full row, but the footer is a single flexible row containing a dynamic model/thinking label and a fixed 36px send/stop action. At the 320–360px rail widths used by the Web workbench, flex negotiation makes the runtime control look compressed and visually crowds the input surface even though horizontal overflow is hidden.

## Approved design

- Keep the Agent rail widths, responsive Drawer behavior, context summary, keyboard send behavior, and Gateway semantics unchanged.
- Give the connected composer an explicit two-row grid: a full-width message field followed by a fixed-height action toolbar.
- Give the toolbar two explicit columns: `minmax(0, 1fr)` for runtime settings and `36px` for send/stop. The runtime label truncates inside its own column; the action never shrinks or moves.
- Give the message field a stable 96px minimum height so its writing area does not visually collapse when surrounding labels or errors change.
- Preserve runtime errors and model-switch fallback below the toolbar; they may wrap vertically but never change toolbar columns.
- Do not move runtime settings into the header, widen the rail, add dependencies, change API contracts, or alter OpenClaw session behavior.

## Verification

- Add a focused DOM contract test that fails against the current flex footer and proves the new two-row/two-column geometry.
- Run the OpenClaw conversation test file, TypeScript, production build, and a local Docker build.
- Reload localhost:8080 and verify the Agent surface has no horizontal overflow at the current narrow viewport; retain the live page for user review.

