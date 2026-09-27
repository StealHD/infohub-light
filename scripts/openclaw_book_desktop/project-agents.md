# Desktop book workflow for Inscope personal Agents

Use `book_desktop` for this Skill. It calls the installed production `book_browser.mjs`
and `visual_flow.py` on the VPS desktop Chrome, with the same lease, checkpoints,
task-owned tab and result contract as native main. Each conversation gets a separate
server task; do not use main's task IDs or adopt an unrelated tab.

Choose a short lowercase `task` label (for example `little-prince`) and reuse it for
all calls about this book. Start with `operation: start`, `title`, and the requested
`language`, `format` or `edition`. Omit unspecified constraints. This tool uses
structured arguments; do not run shell commands or read its private task files.

- `ready`: return `resultMarkdown` and current metadata directly; no extra navigation.
- `search`: select a matching candidate from the returned list with `operation: select`,
  the same `task`, returned `targetId` (the helper calls it `target`) and observed `ref`.
- `entry`: call `operation: await` on the same target. A pending observation is not
  a task failure; preserve the task and observe again when appropriate.
- `verification`: follow the visual steps below on that same target.
- Constraint mismatch: `operation: back` on the owned target and choose a matching result.
- `busy`: another task owns the shared desktop. Preserve this task and wait; never
  take over that task, reset the desktop, or switch browser/profile to avoid the lease.
- `lease_lost` or `resume_required`: call `status`, then `start` with the original
  title and constraints to regain the same task's lease. `visual_next` can do this
  before acting when its last observed target still matches; never replay a
  `visual_submit` after an uncertain outcome.
- `service_error`, `missing_task_tab`, `closed`, explicit rejection or uncertain action:
  report the actual observation and preserve the task. Do not reset or resubmit.

## Visual verification

Follow the host's current approval requirements before interacting with a CAPTCHA;
Skill selection alone does not supply missing action-time authorization.

1. Call `operation: visual_next` with the current task and targetId. This runs the
   production helper's observed checkbox, scrolling and lossless reading preparation.
2. If it returns `challenge_id`, call `operation: visual_read` with `challengeId`
   in two separate tool calls. Inspect each returned image independently. Preserve
   case; both readings must contain exactly five ASCII letters/digits and agree.
   Do not guess, pad or keep rereading until they agree. The tool returns the image
   itself; no separate `view_image`, filesystem read or cropping script is needed.
3. Call `operation: visual_submit` once with `challengeId`, `first` and `second`.
   The native helper rechecks current pixels/geometry, types through Computer Use,
   verifies the input and observes the submission outcome. Do not click again.
4. `passed`: call `start` with the original task/title/constraints to continue the
   book workflow. `new_challenge`: use `visual_next` on the same task and target.
   `stopped`, an explicit rejection, uncertain result or `hostReady: false`: report
   that result and preserve the checkpoint. A passed CAPTCHA is not a finished book.

Use `operation: renew` during a long model pause while this task owns the lease.
On terminal failure or user cancellation use `operation: release`; release never
closes another task's tab. Following a disconnect, use `status` before deciding
whether an action may be retried, then resume the original task and constraints.
The shared desktop retains its existing site session; task tabs and state remain
bound to this conversation. Do not copy cookies, rotate hosts/IPs or refresh a wall.

This entry returns matching metadata and observed final links. File transfer and
message delivery remain separate actions requiring the user's explicit request;
do not treat link extraction as proof of a downloaded or sent file.
