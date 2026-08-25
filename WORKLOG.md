# WORKLOG

<!-- init-pro:compact-worklog schema=1 -->

Entries are maintained by `worklogctl.py`; read-only and no-op tasks are not logged.


```json
{
  "control_topics": [
    "interface"
  ],
  "recorded_on": "2026-08-23",
  "result": "修复生产 X 订阅遗漏最新数据：ActorOps v2 从持久水位追赶抓取窗口，将仅含旧帖的 Actor Dataset 分类为 stale/suspicious 并安全切换候补；明确未启动且共享账本证明零费用的拒绝可收敛并继续候补。",
  "status": "completed",
  "task_id": "2026-08-23-actorops-x-freshness-recovery",
  "unresolved": [
    "生产当前两个 X Candidate 分别为失效 Build 与旧缓存；替换为测试环境已验证 Actor 前，仍需用户单独授权一次受 $0.10 Route cap 约束的付费生产 Probe。"
  ],
  "validation": [
    "ActorOps v2 全套定向后端测试、手册与更新日志 Vitest、代码规模及控制文件校验通过。",
    "impacted preflight 17/17 通过；诊断期间只读取既有 Dataset、Run ledger 与公开 Actor metadata，未创建新 Actor Run 或费用。"
  ]
}
```

```json
{
  "control_topics": [
    "phase"
  ],
  "recorded_on": "2026-08-23",
  "result": "收敛 v2.4.2 发布后 SQLite 锁竞争：全库 integrity/FK/active-job 校验固定在 Worker 停止阶段，容器启动后只以共享 runtime health 验收，避免正常 Job 触发误回滚；同时移除 Test Gate 中 Phase 8 已删除测试的陈旧映射。",
  "status": "completed",
  "task_id": "2026-08-23-v2-4-2-release-cutover-lock-hardening",
  "unresolved": [],
  "validation": [
    "生产 v2.4.2 API/Worker 双 healthy，current、镜像版本、revision、内网 live/ready 与公网 health 一致；离线数据库 integrity=ok、foreign_key_errors=0，0600 部署备份存在。",
    "Release/runtime health 定向测试与 Test Gate 映射自检通过；修复后 impacted preflight 18/18 通过。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "capabilities",
    "context",
    "decisions"
  ],
  "recorded_on": "2026-08-23",
  "result": "Removed mechanical product-documentation and OpenClaw structure-locking test gates; retained behavior coverage and hardened impact-map group-test integrity.",
  "status": "completed",
  "task_id": "2026-08-23-test-constraint-cleanup",
  "unresolved": [],
  "validation": [
    "Focused OpenClaw setup, Test Gate and workflow-contract tests passed.",
    "OpenClaw Hook Vitest and TypeScript checks passed.",
    "Impacted preflight passed 16/16 commands, including full Python, frontend and control checks.",
    "Markdown and project-control validation, JSON checks and diff check passed."
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "interface",
    "phase",
    "ui"
  ],
  "recorded_on": "2026-08-23",
  "result": "OpenClaw and Remote MCP now subscribe to any visible catalog source and can create all current public source types; X and Instagram create atomic pending/disabled ActorOps bindings without fetch, Job, Attempt, AI, notification, or paid Actor work.",
  "status": "completed",
  "task_id": "2026-08-23-openclaw-all-source-subscriptions",
  "unresolved": [
    "No deployment, release, tag, push, real source fetch, Actor call, AI call, notification, or paid operation was performed.",
    "The second aggregate preflight stopped on stale source-guide expectations; after correcting them, the full Python suite and every remaining planned gate command passed independently, and the aggregate was not invoked a third time."
  ],
  "validation": [
    "Full Python suite passed with ResourceWarning promoted to errors.",
    "Frontend passed 83 Vitest files / 611 tests, lint, typecheck, UI and E2E contracts, and production build.",
    "Code-size, Markdown/control, JSON, syntax, product documentation, and diff checks passed.",
    "X/Instagram tests proved pending Binding creation, atomic rollback, deletion lifecycle, Web-only activation/retargeting, and zero fetch/discovery Jobs or Actor Attempts."
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "interface"
  ],
  "recorded_on": "2026-08-24",
  "result": "X profile ActorOps adapter now validates full datasets, removes only structurally proven reply rows, and remaps remaining posts so replies do not consume limits or advance watermarks; existing history remains untouched.",
  "status": "completed",
  "task_id": "2026-08-24-x-profile-reply-filter",
  "unresolved": [],
  "validation": [
    "46 targeted ActorOps adapter, runtime, and maintenance tests passed.",
    "Frontend TypeScript typecheck passed.",
    "Backend code-size policy passed against the task baseline."
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "interface",
    "observability",
    "ui"
  ],
  "recorded_on": "2026-08-24",
  "result": "Added explicit Global 31 ActorOps resilience storage: source-scoped stale-data cross-checking, bounded asynchronous repair coordination, and owner/admin-safe execution timelines with JSONL mirrors.",
  "status": "completed",
  "task_id": "2026-08-24-actorops-resilience-closure",
  "unresolved": [
    "No production migration, source fetch, paid Actor call, AI call, notification, deployment, release, tag, or push was performed."
  ],
  "validation": [
    "Targeted ActorOps resilience, runtime, maintenance, worker and API tests passed (65 tests).",
    "Frontend TypeScript typecheck, observability contract, code-size policy, migration backup/restore tests and control validation passed."
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-24",
  "result": "ActorOps 替换抽屉现展示公开名称、商城地址、评分、收藏、用户数、开发者、维护方、价格和核验状态；缺少公开身份的候选不会被选择，已按用户数降序排列。",
  "status": "completed",
  "task_id": "2026-08-24-actorops-candidate-display",
  "unresolved": [],
  "validation": [
    "Vitest：4 个定向文件、9 项测试通过。",
    "前端 typecheck 与 lint 通过；本地 Docker API/Worker healthy。",
    "impacted preflight 11/11 通过。"
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "phase",
    "ui"
  ],
  "recorded_on": "2026-08-24",
  "result": "Implemented global 31 workspace runtime settings with 21 typed non-secret keys, Owner/Admin Web and isolated Remote MCP proposal/apply flows, hot runtime resolution, OpenClaw guidance, and migration/documentation support; no merge, push, production migration, or deployment was performed.",
  "status": "completed",
  "task_id": "2026-08-24-admin-mcp-system-settings",
  "unresolved": [
    "The merger must run the authoritative final-SHA gate before merge/release; the complete preflight was not run a third time after its second allowed fail-fast cycle."
  ],
  "validation": [
    "System settings, global31 migration, REST/MCP authorization, scheduling, retention, storage governance, OpenClaw and adjacent targeted tests passed.",
    "Frontend lint/typecheck passed; full Vitest passed 84 files and 614 tests; production build and preview artifact check passed.",
    "Two bounded impacted-preflight runs found an observability map omission and a stale delegation error assertion; both were fixed and their failing specs passed. Full Python coverage was then completed in bounded segments, and remaining syntax, JSON, code-size, UI/E2E contract, Markdown/control and diff checks passed."
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "interface"
  ],
  "recorded_on": "2026-08-24",
  "result": "Merged Admin MCP system settings into local main, resolved Global 31 migration-version collision by moving workspace settings to Global 32 with an explicit ActorOps Global 31 prerequisite, and routed ActorOps repair job retention through the typed workspace resolver.",
  "status": "completed",
  "task_id": "2026-08-24-admin-mcp-system-settings-merge-fix",
  "unresolved": [
    "No push, production migration, VPS deployment, source fetch, Actor call, AI call, or notification was performed."
  ],
  "validation": [
    "The previously failing historical-schema initialization test and 30 focused system-settings, migration, REST/MCP and ActorOps resilience tests passed.",
    "A final impacted preflight for the merged main SHA is pending."
  ]
}
```

```json
{
  "control_topics": [
    "decisions",
    "instructions",
    "ui"
  ],
  "recorded_on": "2026-08-24",
  "result": "固化全站组件参数矩阵与默认 UI 继承规则；HeroUI Pro 仅作层级参考，生产继续使用 HeroUI v3 OSS 和本地设计系统。",
  "status": "completed",
  "task_id": "2026-08-24-ui-component-parameter-contract",
  "unresolved": [],
  "validation": [
    "UI contract、TypeScript、ESLint、完整前端 Vitest、生产构建和 impacted preflight 通过。",
    "Subscriptions 与 Login 的暗色/亮色、桌面/平板/手机既有 Playwright 快照全部通过，未更新基线。"
  ]
}
```

```json
{
  "control_topics": [
    "decisions",
    "ui"
  ],
  "recorded_on": "2026-08-24",
  "result": "Addressed the annotated UI consistency issues: fixed the desktop sidebar account footer track, standardized the notification-service form dialog, compacted Apify Key cards and status placement, and rebuilt ActorOps routes as independent cards.",
  "status": "completed",
  "task_id": "2026-08-24-ui-annotation-remediation",
  "unresolved": [],
  "validation": [
    "Targeted Vitest passed (83 tests across notification, ActorOps, workbench, UI contract and Apify scenarios).",
    "UI contract, TypeScript, ESLint and production build passed.",
    "Targeted Playwright passed for ActorOps three-viewport visual baseline, notification/key surfaces and desktop workbench shell."
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-24",
  "result": "Refined the refresh Bootstrap sidebar skeleton to mirror the loaded 52px brand header, grouped navigation and fixed 64px account footer; collapsed refresh now uses light icon silhouettes and expanded refresh adds text silhouettes without adding product colors.",
  "status": "completed",
  "task_id": "2026-08-24-bootstrap-sidebar-skeleton",
  "unresolved": [],
  "validation": [
    "Dedicated desktop refresh-sidebar visual regression passed with fixed light theme and Reduced Motion.",
    "Existing hard-refresh handoff regression, UI contract, TypeScript, ESLint and production build passed."
  ]
}
```

```json
{
  "control_topics": [
    "decisions",
    "ui"
  ],
  "recorded_on": "2026-08-24",
  "result": "统一通知新增与编辑表单的渠道、服务商及 Webhook 类型选择为共享 HeroSelect，并用 UI 合约拒绝业务代码原生 select。",
  "status": "completed",
  "task_id": "2026-08-24-notification-select-contract",
  "unresolved": [],
  "validation": [
    "HeroNotificationTargets 与 uiContract Vitest 50 项通过",
    "通知服务 390/580/768/1440 Playwright 通过",
    "check:ui、typecheck、lint、build 通过"
  ]
}
```

```json
{
  "control_topics": [
    "decisions",
    "ui"
  ],
  "recorded_on": "2026-08-24",
  "result": "Refined the desktop sidebar gutter and rebuilt ActorOps as URL-driven Route/Log tabs with compact route cards, actionable incident guidance, and safe operation records.",
  "status": "completed",
  "task_id": "2026-08-24-actorops-sidebar-log-tabs",
  "unresolved": [
    "Local Docker rebuild could not pull ghcr.io/astral-sh/uv because the external registry TLS certificate did not validate; the existing runtime was not replaced."
  ],
  "validation": [
    "Targeted Vitest passed (95 tests).",
    "ActorOps Playwright passed across desktop, tablet and mobile, including direct 390/768/1440 Tab checks.",
    "UI contract, TypeScript, ESLint, production build and frontend code-size policy passed."
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-24",
  "result": "Rebuilt the wide-desktop sidebar as fixed 72px/232px canvas layers with opacity handoff, one persistent toggle, a stable 48px account trigger, and real-overflow-only navigation scrolling; intermediate-width label reflow and footer jumping are removed.",
  "status": "completed",
  "task_id": "2026-08-24-desktop-sidebar-fixed-canvas-motion",
  "unresolved": [],
  "validation": [
    "Sidebar Vitest and UI-contract tests passed (77 assertions).",
    "Dedicated desktop Playwright sampled the full expand/collapse motion, rapid reversal, Reduced Motion, 1359px fallback, and low-height overflow.",
    "Local Docker rebuild completed with healthy API/Worker; final impacted preflight passed 16/16."
  ]
}
```

```json
{
  "control_topics": [
    "decisions",
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-24",
  "result": "新增 RSSHub 固定访问密钥专用接口和设置页写入、轮换、安全移除流程，环境托管保持只读；Actor 商城信息浮层支持跨标签/浮层悬停、键盘与触控交互。",
  "status": "completed",
  "task_id": "2026-08-24-rsshub-access-key-and-actor-popover",
  "unresolved": [],
  "validation": [
    "定向 API、Vitest 与 Playwright 通过（RSSHub 390/768/1440、Actor 浮层）。",
    "当前 worktree 本地 Docker 重建完成，API/Worker 均 healthy。",
    "impacted preflight passed 16/16：完整 Python、Vitest、UI 契约、lint、typecheck、build 与控制校验通过。"
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-25",
  "result": "修复 v2.5.1 发布 Gate 发现的侧栏命中区与断言漂移：768–1359px 的导航触发器不再复用桌面绝对定位，SplitPanel 装饰层不拦截指针，OpenClaw 三类配置卡与固定宽度侧栏的测试边界同步。",
  "status": "completed",
  "task_id": "2026-08-25-release-v2-5-1-ui-gate-remediation",
  "unresolved": [],
  "validation": [
    "定向 release Playwright：7 passed、2 intentional skipped",
    "HeroWorkbenchShell Vitest：30 passed",
    "完整 release UI Gate：6/6 commands passed"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-25",
  "result": "修复 ActorOps 公开商城 Actor 标签的指针抖动：将指针语义固定在 HeroUI Popover 的完整触发器上，去除仅内部 Chip 为手型导致的命中边界切换；本地运行时已更新。",
  "status": "completed",
  "task_id": "2026-08-25-actorops-marketplace-cursor-stability",
  "unresolved": [],
  "validation": [
    "ActorOpsV2ActorChip Vitest 3 项通过。",
    "UI contract、TypeScript、ESLint 与 impacted preflight 11/11 通过。",
    "本地 API/Worker 均 healthy，runtime health 确认 revision cd37ed599b28-dirty。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-25",
  "result": "纠正 ActorOps 商城 hover 抖动根因：HeroUI 默认模态 Popover 的全屏 underlay 会让静止指针下的 Trigger 退出命中并反复开关；商城预览改为非模态，Trigger 与交互浮层可同时命中。",
  "status": "completed",
  "task_id": "2026-08-25-actorops-marketplace-hover-stability",
  "unresolved": [],
  "validation": [
    "ActorOpsV2ActorChip Vitest 3 项、UI contract、TypeScript 与 ESLint 通过。",
    "本地容器重建后 API/Worker healthy。",
    "当前 ActorOps 页面同坐标连续 12 帧均为 pointer、triggerHit=true、popoverCount=1、underlayCount=0；移开后 240ms 正常关闭。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "decisions",
    "interface"
  ],
  "recorded_on": "2026-08-25",
  "result": "修复 Apify 专用 validation Key 的历史 unknown-start 错误阻塞生产 Key 排空：生产 drain 仅统计 acquisition 角色 Run，专用 validation 保留独立锁定并仅以原 Key 的账户时间窗 GET 证据收口；Worker 在 claim 前有界对账且失败不阻塞普通 Job。",
  "status": "completed",
  "task_id": "2026-08-25-apify-validation-drain-isolation",
  "unresolved": [
    "本地部署启动时 Worker 领取既有任务并登记了一个新的 acquisition 远端 Run，已立即停止 Worker 防止继续调用；该 Run 的远端读取或终止需要 acquisition Key 的单独授权。"
  ],
  "validation": [
    "32 项 Apify Key-pool 定向回归与 10 项 Worker 相关测试通过。",
    "snapshot impacted preflight、Markdown/control、worklog、JSON 与 diff 检查通过。",
    "从目标 worktree 部署后，池由 draining/generation 1940 恢复为 ready/generation 1941，备用 acquisition Key 已 active；历史 validation unknown-start 由空窗口证据终结为 start_rejected、$0、charge_final。",
    "部署前创建主运行库 0600 SQLite 备份。"
  ]
}
```
