# WORKLOG

<!-- init-pro:compact-worklog schema=1 -->

Entries are maintained by `worklogctl.py`; read-only and no-op tasks are not logged.


```json
{
  "control_topics": [
    "interface"
  ],
  "recorded_on": "2026-08-21",
  "result": "Redacted validation-cap migration health-gate failures into a structured blocked status after the local offline attempt exposed pre-existing SQLite corruption.",
  "status": "completed",
  "task_id": "2026-08-21-actorops-validation-cap-safe-block",
  "unresolved": [
    "Latest local service.db integrity check is not clean; the newest verified clean backup predates it and must not be restored without an explicit recovery decision."
  ],
  "validation": [
    "migration health-gate tests",
    "safe local CLI blocked response"
  ]
}
```

```json
{
  "control_topics": [
    "capabilities",
    "decisions",
    "interface"
  ],
  "recorded_on": "2026-08-21",
  "result": "Recovered the local database from a verified temporary copy, then prevented Discovery from reintroducing a final failed exact Actor revision as a new canary candidate.",
  "status": "completed",
  "task_id": "2026-08-21-actorops-exact-revision-discovery",
  "unresolved": [
    "YouTube needs a newly discovered exact revision that passes its own AI-assisted target-identity mapping before a third runnable Actor can be staged."
  ],
  "validation": [
    "database integrity and foreign-key recovery checks",
    "81 targeted ActorOps tests",
    "code-size, product-doc, and Markdown controls"
  ]
}
```

```json
{
  "control_topics": [
    "capabilities"
  ],
  "recorded_on": "2026-08-21",
  "result": "Broadened the three free YouTube Store search queries after exact-revision filtering left no viable new Candidate; static and AI-assisted validation gates remain unchanged.",
  "status": "completed",
  "task_id": "2026-08-21-actorops-youtube-discovery-breadth",
  "unresolved": [
    "The widened discovery must still yield a new exact revision that passes its own target-identity validation before it can join the pool."
  ],
  "validation": [
    "targeted discovery-query and exact-revision tests",
    "code-size, product-doc, and Markdown controls",
    "prior full impacted preflight"
  ]
}
```

```json
{
  "control_topics": [
    "capabilities"
  ],
  "recorded_on": "2026-08-21",
  "result": "Classified demo-only Actor output as a placeholder and skipped source/profile metadata rows so a later valid content row maps under its exact Actor revision; confirmed the repaired mapper against the prior bounded source Dataset without persisting raw rows.",
  "status": "completed",
  "task_id": "2026-08-21-actorops-content-row-mapping",
  "unresolved": [
    "A separate media-array contract is still required for Instagram carousel images; current shared ContentItem carries one thumbnail/image URL."
  ],
  "validation": [
    "targeted ActorOps mapper/canary tests",
    "offline bounded remote-Dataset replay",
    "impacted preflight passed (17/17)"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "phase"
  ],
  "recorded_on": "2026-08-21",
  "result": "修复 v2 ready catalog binding 未注入运行时 profile_id、导致 Instagram 绕过 v2 的缺口；在本地开启 v2 后顺序执行 X、YouTube、Instagram 三条真实 source_fetch。X 产生 advanced 并写入 LKG/水位；YouTube 与 Instagram standby 为 valid_empty；Instagram primary 明确以 candidate contract invalid 失败后按既定顺序切换 standby。全部 v2 Attempt 已结算，无未结费用。",
  "status": "partial",
  "task_id": "2026-08-21-actorops-v2-live-runtime-bridge",
  "unresolved": [
    "Phase 6 的每平台 20 次成功自然获取、三次静止 Worker 重启和最终 active/rollback 决策尚未执行。",
    "Instagram primary 的精确 Actor 合同已保留失败事实；后续仅在 Build 或 Manifest 变化后重新筛选。"
  ],
  "validation": [
    "真实本地 v2 执行：X USD 0.032164 advanced；YouTube USD 0.042110 valid_empty；Instagram primary USD 0.005189 contract invalid、standby USD 0.014000 valid_empty；均为 cost_final=true。",
    "唯一 impacted preflight 17/17 通过（426 秒），包括完整 Python、前端、控制文件、产品文档、代码规模和构建检查。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture"
  ],
  "recorded_on": "2026-08-21",
  "result": "修复 ActorOps v2 对账与运行时并发竞态：远端 Run 已成功但本地仍在映射或通过 Feed publication fence 的 60 秒窗口仅保持 pending，避免对账器把活跃 Attempt 错记为未发布失败；超过窗口仍保留原有只读失败结算。",
  "status": "completed",
  "task_id": "2026-08-21-actorops-v2-reconciliation-handoff",
  "unresolved": [
    "Phase 6 的平台自然获取验收仍需在此修复部署后继续；本地测试中已被旧竞态结算的单条 Attempt 保留为审计事实，不会重开。"
  ],
  "validation": [
    "新增 fresh remote-success 对账竞态回归；ActorOps reconciliation/runtime/catalog 21 项通过。",
    "唯一 impacted preflight 15/15 通过：完整 Python、前端、控制文件、产品文档、代码规模与构建检查均成功。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "capabilities",
    "phase"
  ],
  "recorded_on": "2026-08-21",
  "result": "Reworked the local ActorOps v2 route console into readable product cards with zero-cost Active/Standby switching and exact-evidence binding verification; resolved the local X pending binding to ready without a fetch or Actor run.",
  "status": "completed",
  "task_id": "2026-08-21-actorops-v2-readable-route-controls",
  "unresolved": [
    "Candidate Probe/activate/disable controls and Phase 6 platform observation remain outside this UI/control slice."
  ],
  "validation": [
    "25 targeted Python ActorOps/catalog tests passed.",
    "20 targeted frontend route-control/incident tests passed; TypeScript and lint passed.",
    "Local Docker API/Worker health passed; local X binding repair now reports 2 ready X bindings."
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "interface",
    "observability",
    "phase",
    "ui"
  ],
  "recorded_on": "2026-08-22",
  "result": "完成 ActorOps v2 Phase 7.1：global 28 商城快照与显式替换流程、费用上限管理及紧凑 Store Chip/替换 Drawer 已落地。真实本地 Instagram 替换实测通过后保留审计并恢复原主用；新增收尾修复使 fresh bootstrap 同时断言 global 26/28、所有管理写接口有安全事件映射，Worker 的 v2 Job 注册保持在专用小模块。",
  "status": "completed",
  "task_id": "2026-08-22-actorops-v2-phase7-1-release-finish",
  "unresolved": [
    "本地服务暂保留 ACTOROPS_V2_ENABLED=true 供操作者进行 UI 手工验收；仓库与示例配置默认仍为 false。",
    "未发布 VPS、未创建 Release Tag。"
  ],
  "validation": [
    "本地 global 28 migration、6 个现役主备商城元数据刷新、一次 Instagram 串行 Probe、费用结算与无网络 apply/恢复均已完成；普通 GitHub 来源 Job 成功，证明 Worker 隔离。",
    "完整 impacted preflight 17/17 通过：全量 Python、前端 Vitest/build/lint/typecheck、浏览器契约、尺寸、可观测性、产品文档、控制与 diff 检查均通过。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-22",
  "result": "修复 ActorOps v2 Route 列表在窄内容列仍误用四列布局、导致主用/备用中文逐字换行的问题；槽位标签改为 Chip 外部固定列，Actor 名称独立截断，费用操作改为明确的“调整”。",
  "status": "completed",
  "task_id": "2026-08-22-actorops-v2-route-list-layout-fix",
  "unresolved": [],
  "validation": [
    "ActorOps v2 定向 Vitest 4 项、TypeScript 与 lint 通过。",
    "impacted preflight 12/12 通过；本地 Docker API/Worker health 通过。",
    "按 918×889 复验：Route 内容列和三条路线均无横向溢出，主用/备用槽位保持单行高度。"
  ]
}
```

```json
{
  "control_topics": [
    "interface"
  ],
  "recorded_on": "2026-08-22",
  "result": "Fixed platform-source settings so changing only fetch_limit or analysis_mode does not re-run legacy Actor Route certification; only a target change remains binding-gated.",
  "status": "completed",
  "task_id": "2026-08-22-source-settings-nonidentity-update",
  "unresolved": [],
  "validation": [
    "Focused API test module: 33 passed.",
    "Impacted preflight passed 15/15, including full backend, frontend checks, controls, code size and product-doc review."
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "phase"
  ],
  "recorded_on": "2026-08-22",
  "result": "ActorOps v1 最终退役 Phase 0 已冻结执行基线并建立只减不增的运行时边界：当前 API、Service、Worker、SQL 与前端 v1 引用均进入显式 allowlist，后续提交不能新增或迁移这些依赖。",
  "status": "completed",
  "task_id": "2026-08-22-actorops-v1-retirement-boundary",
  "unresolved": [
    "后续 Phase 将逐项清空在线 allowlist；历史 migration、审计与共享 Run/Key Pool/alerts 仍按计划保留。"
  ],
  "validation": [
    "边界扫描直接测试 2 项通过。",
    "impacted preflight 17/17 通过，覆盖完整 Python、前端、控制面、产品文档和代码尺寸检查。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "interface",
    "phase"
  ],
  "recorded_on": "2026-08-22",
  "result": "Phase 1 完成 global 29、确定性 Attempt 身份、Dataset GET 重放、费用单调持久化及 Reconciler observed 语义。",
  "status": "completed",
  "task_id": "2026-08-22-actorops-v2-attempt-recovery",
  "unresolved": [
    "后续 Phase 2–8 继续收缩 v1 在线 allowlist。"
  ],
  "validation": [
    "ActorOps v2 与迁移直接测试 160 项通过。",
    "impacted preflight 17/17 通过。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "interface",
    "phase"
  ],
  "recorded_on": "2026-08-22",
  "result": "Phase 2 完成 ActorOpsBindingService、纯 v2 Binding verify 与平台来源 CRUD/调度/共享获取/单源和 Feed 执行接管；X、Instagram、YouTube 不再以 v1 Binding 或 Route 作为现役来源授权事实。",
  "status": "completed",
  "task_id": "2026-08-22-actorops-v2-source-binding-lifecycle",
  "unresolved": [
    "Phase 3–8 继续退役旧 Admin API、Worker/housekeeping、前端 v1 控制面与剩余 allowlist。",
    "两次 impacted preflight 分别在两个已修复的过期 v1 语义测试处中止；依门禁上限未执行第三次，完整剩余 Python 与前端/控制组件已直接复验通过。"
  ],
  "validation": [
    "Phase 2 定向后端回归 362 项通过；preflight 第二次中断点后的剩余 Python 测试集合 100% 通过，两个过期测试修正后各自模块通过。",
    "前端 lint、typecheck、UI contract、84 个 Vitest 文件/625 项测试、production build 与 E2E contract 通过。",
    "代码规模、产品文档、Markdown/control、JSON、syntax 与 git diff 检查通过；未调用真实 Actor、AI 或付费来源。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "interface",
    "phase"
  ],
  "recorded_on": "2026-08-22",
  "result": "完成 ActorOps v2 单轨退役 Phase 3：新增直接 v2 Admin 读模型，Route list/detail、候选、Binding、Attempt、Discovery、Maintenance、Replacement 与安全商城元数据不再拼接或读取 v1；ApiContext 移除 v1 ActorOps Factory，Operation Events 仅查询脱敏 actorops_v2_* Operation Log。",
  "status": "completed",
  "task_id": "2026-08-22-actorops-v2-admin-service",
  "unresolved": [
    "旧 Pool/Canary/Freshness 兼容接口、Worker 与前端控制面按 Phase 4–8 继续退役；未部署、未调用真实 Actor、AI 或付费来源。"
  ],
  "validation": [
    "v1 表 SQLite authorizer deny 下的 v2 Admin list/detail、migration-required 与 unavailable、Operation Log 脱敏和 feature-flag 无语义回退测试通过。",
    "定向 ActorOps/API/来源生命周期/Operation Log 回归、v2 Repository/Runtime/Reconciliation/Maintenance 回归、前端 typecheck/lint、控制与产品文档校验均通过。",
    "最终 impacted preflight 15/15 通过（snapshot: /tmp/actorops-phase3-impact.json）。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "interface",
    "phase"
  ],
  "recorded_on": "2026-08-22",
  "result": "完成 ActorOps v2 单轨退役 Phase 4：设置页永久移除 Hero/v1 fallback，前端只调用 schema-2 v2 Route、详情、Replacement、共享 alerts 与脱敏 Operation Events；旧 Pool/Canary/Freshness 组件、types、query keys、服务和浏览器流程已删除，v1 前端 allowlist 收敛为空。",
  "status": "completed",
  "task_id": "2026-08-22-actorops-v2-control-plane",
  "unresolved": [
    "Phase 5–8 继续以 410 退役 v1 API、隔离 v1 Worker Job、安装最终单轨 schema/离线退役工具并删除剩余 v1 Runtime；未部署、未调用真实 Actor、AI 或付费来源。"
  ],
  "validation": [
    "v2 UI 定向 Vitest、lint、typecheck、production build 与桌面/平板/390px Playwright 均通过；E2E 断言不请求 retired Pool/Canary/Freshness URL。",
    "完整 impacted preflight 16/16 通过（snapshot: /tmp/actorops-phase4-impact.json），包含全域 Python、76 个 Vitest 文件/595 项、E2E contract、代码规模、文档与控制检查。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "capabilities",
    "interface"
  ],
  "recorded_on": "2026-08-22",
  "result": "ActorOps Phase 5 retired v1 Admin Pool/Canary/Freshness/Discovery/X profile routes behind authenticated stable 410 responses, while retained compatibility URLs now operate directly on v2 Discovery, Candidate, Route cap and Binding state. Removed online v1 projections and factories, and moved historical projections into a test-only fixture.",
  "status": "completed",
  "task_id": "2026-08-22-actorops-v2-phase5-api-retirement",
  "unresolved": [
    "v1 Worker job isolation, the final single-track schema and offline retirement tooling remain Phase 6–8 work."
  ],
  "validation": [
    "Added authorizer-denied v1-table regression coverage for all retired endpoints and v2 aliases.",
    "Impacted preflight passed: 17/17 commands, including full Python suite, frontend lint, typecheck, Vitest and build.",
    "Markdown/project controls, code-size, observability, product-doc and diff checks passed."
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-22",
  "result": "Canonicalized v2 Actor Dataset rows by native identity and newest-first order before applying each source fetch limit, preventing duplicate X items from displacing newer content.",
  "status": "completed",
  "task_id": "actorops-x-output-canonicalization",
  "unresolved": [
    "Phase 6 Worker v1 Job isolation remains a separate next change.",
    "No VPS deployment, remote Actor call, AI call, paid source call, tag, or push was performed."
  ],
  "validation": [
    "Red test: test_manifest_deduplicates_unsorted_rows_and_keeps_latest_limited_items failed before implementation and passed after it.",
    "Direct ActorOps manifest, runtime, adapter, source acquisition, legacy runtime, cutover, YouTube probe, and Apify social tests passed.",
    "Impacted preflight passed 17/17, including full Python, Vitest, frontend build, control, documentation, and frozen-file checks."
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "interface",
    "phase"
  ],
  "recorded_on": "2026-08-23",
  "result": "ActorOps Worker now claims and executes only v2 control Jobs; never-started v1 Jobs are atomically retired while ambiguous historical Jobs remain isolated without new remote work.",
  "status": "completed",
  "task_id": "2026-08-23-actorops-v2-worker-single-track",
  "unresolved": [],
  "validation": [
    "Targeted Worker, queue, migration, authorizer and retirement-boundary tests passed.",
    "Impacted preflight passed 17/17, including full Python, frontend and control checks."
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "interface",
    "phase"
  ],
  "recorded_on": "2026-08-23",
  "result": "新增 ActorOps v1 离线退役工具：脱敏 status、停机/心跳安全 snapshot 收据、仅取消未启动 Job 的 fail-closed apply 和 hash/shape/integrity verify；未知启动、未结费用与非终态事实保持阻断。",
  "status": "completed",
  "task_id": "2026-08-23-actorops-v1-offline-retirement",
  "unresolved": [
    "global 30 单轨 schema、flag/shadow/source_v1_generation 删除及最终 v1 Runtime 清理仍属 Phase 7B–8。"
  ],
  "validation": [
    "18 targeted ActorOps retirement and adjacent auto-pool tests",
    "frontend TypeScript typecheck",
    "impacted preflight passed (17/17; full Python, lint, Vitest and build)"
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
  "result": "Installed the global 30 ActorOps v2 single-track migration: final Route/Binding rebuild, disabled catalog seed, and offline backup/verification workflow without real database apply or network calls.",
  "status": "completed",
  "task_id": "2026-08-23-actorops-global30-single-track",
  "unresolved": [
    "Phase 7B2 still removes ACTOROPS_V2_ENABLED startup compatibility and its configuration/tests.",
    "Phase 8 still removes remaining zero-online-import v1 runtime and empties the authorizer allowlist."
  ],
  "validation": [
    "234 targeted ActorOps regression tests",
    "impacted preflight passed (17/17), including full Python and frontend checks",
    "code-size, product-doc, Markdown/control, JSON, and diff checks"
  ]
}
```
