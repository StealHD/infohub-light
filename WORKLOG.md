# WORKLOG

<!-- init-pro:compact-worklog schema=1 -->

Entries are maintained by `worklogctl.py`; read-only and no-op tasks are not logged.


```json
{
  "control_topics": [
    "architecture",
    "interface",
    "phase",
    "ui"
  ],
  "recorded_on": "2026-08-21",
  "result": "ActorOps v2 Phase 7 增加默认关闭的管理兼容门面：既有管理 URL 在 v2 已启用且 readiness 完整时只追加 health、runtime mode、Active/Standby/LKG、降级原因及脱敏维护策略；Owner/Admin 可通过零费用 policy generation CAS 授权维护，Settings 改为读取通用 v2 投影。",
  "status": "partial",
  "task_id": "2026-08-21-actorops-v2-phase7-admin-facade",
  "unresolved": [
    "历史费用隔离、global 26 migration 与三平台真实切流仍需操作者确认，所有 Route 继续 disabled。",
    "候选 Probe/activate/disable 控制须在 Phase 6 运行验收和独立授权后实现。"
  ],
  "validation": [
    "ActorOps v2/API/observability 定向测试通过。",
    "impacted preflight 17/17 通过，覆盖后端、前端、控制面、代码尺寸、产品文档和生产构建。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "decisions",
    "interface",
    "phase"
  ],
  "recorded_on": "2026-08-21",
  "result": "ActorOps v2 修复了旧 terminal Attempt 遗失 cost_final 派生位的离线迁移判定：只有恰好一个已终态且已保存最终实际费用的 remote Run 可作证明。经确认的历史费用 quarantine 后，已在本地离线完成 global 26 只读 backfill；所有 Route 仍为 disabled。",
  "status": "partial",
  "task_id": "2026-08-21-actorops-v2-global26-local-migration",
  "unresolved": [
    "YouTube、Instagram、X 的 shadow/active、20 次自然获取和重启验收仍需逐平台单独费用授权。",
    "ACTOROPS_V2_ENABLED 仍保持 false；Phase 7 候选操作和 Phase 8 v1 退役尚未开始。"
  ],
  "validation": [
    "迁移与历史费用审计定向测试 29 项通过。",
    "impacted preflight 15/15 通过，覆盖后端、前端、控制面、代码尺寸和产品文档。",
    "本地 apply 已通过 marker/shape、integrity_check 与 foreign_key_check；global 25 保持惰性。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "decisions",
    "interface",
    "phase"
  ],
  "recorded_on": "2026-08-21",
  "result": "修复 ActorOps v2 global 26 backfill 只复制旧 ActorOps binding、遗漏既有 Instagram 目录订阅的缺口：新增通用离线 catalog binding bridge 与受控 repair CLI，已在本地库只插入 1 条经 Adapter 重验的 pending v2 binding；不改写订阅、v1 binding、Candidate、LKG、水位、Attempt、费用或 Route mode。切流摘要现在能重验该 bridge 而不把 pending 当作 ready。",
  "status": "completed",
  "task_id": "2026-08-21-actorops-v2-catalog-binding-repair",
  "unresolved": [
    "Instagram Route 仍因未验证 binding 与 active slot 不一致保持 disabled；未执行 shadow、active、真实来源或付费 Actor。"
  ],
  "validation": [
    "新增 migration/repair/global-25 fail-closed/切流摘要契约测试，以及现有 migration、cutover、Adapter、目录来源与 source-acquisition 回归全部通过。",
    "impacted preflight 17/17 通过；本地 API/Worker Docker 健康，ready 返回 ready；repair apply 后 integrity/foreign keys 通过。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "decisions",
    "interface",
    "phase"
  ],
  "recorded_on": "2026-08-21",
  "result": "补齐 ActorOps v2 既有 v1 binding 的离线 readiness CAS：切流摘要只比较当前 runtime 可执行的 exact revision，settled source-canary 证明才可将 pending 提升为 ready；本地 YouTube shadow 选择零 v2 Attempt/POST 后，因 v1 candidate_shortfall 未进入 active 并恢复 disabled。",
  "status": "partial",
  "task_id": "2026-08-21-actorops-v2-youtube-readiness-guard",
  "unresolved": [
    "YouTube v1 Route 仅有 1 条 runnable exact revision，低于现役两个 Candidate 阈值；需要独立受测的 v1 pool 恢复，或显式修订切流决策后才可重开 shadow。"
  ],
  "validation": [
    "定向回归 52 项通过，覆盖 terminal slot 过滤、精确来源证明、CAS/idempotency、global 25 惰性与切流摘要。",
    "最终 impacted preflight 17/17 通过，覆盖完整 Python、前端 lint/typecheck/Vitest/build、控制、产品文档和代码尺寸检查。",
    "本地 Route 已由 shadow CAS 恢复 disabled；状态确认 0 个 v2 Attempt、0 未结费用。"
  ]
}
```

```json
{
  "control_topics": [
    "interface"
  ],
  "recorded_on": "2026-08-21",
  "result": "Actor Canary 计划层已复用执行前的精确 Revision 授权检查；已终态失败且仍为 open 的 Build/Manifest 会在生成计划时直接排除，避免创建后被 Worker 以 approval_revoked 取消。",
  "status": "completed",
  "task_id": "2026-08-21-actorops-exact-revision-plan-guard",
  "unresolved": [
    "当前本地 YouTube 候选中没有新的可授权 exact revision；已停止进一步付费测试，待新的免费 Discovery 产生未失败的候选后再串行验证。"
  ],
  "validation": [
    "新增计划/执行一致性回归，并与候选授权、Pool staging/management 共 47 项 Pytest 通过。",
    "代码大小策略、产品文档定向门禁、impact map JSON 与 git diff --check 通过。"
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
  "recorded_on": "2026-08-21",
  "result": "Canary 在某个 exact Actor/Build 的输出合同不匹配时，现可将仅含字段路径与 JSON 类型的内存摘要交给全局 AI 提出该 Revision 专属输出指针；同一真实返回仍须通过来源身份、内容、URL 和时间的确定性校验，成功才固化新的不可变 Manifest。",
  "status": "completed",
  "task_id": "2026-08-21-actorops-per-revision-ai-output-mapping",
  "unresolved": [
    "本地 YouTube 仍缺少一条从未失败的可授权 exact revision；下一步只运行一次扩展免费 Discovery，再按单 Actor 串行验证。"
  ],
  "validation": [
    "新增无值请求、candidate-local Manifest 与未观察 pointer 拒绝测试；Canary、批次记账、Worker 和 Pool 授权共 46 项 Pytest 通过。",
    "代码大小、产品文档、Markdown/项目控制、impact map JSON 与 diff 检查通过。"
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
  "result": "Raised the explicit ActorOps Route and Candidate-validation ceiling from $0.10 to $0.20 after a real content-valid Canary exceeded the former hard cap. Defaults remain $0.02; CAS, one-shot approval, final-cost accounting and over-cap rejection remain enforced.",
  "status": "completed",
  "task_id": "2026-08-21-actorops-authorized-cost-cap",
  "unresolved": [],
  "validation": [
    "ActorOps pool, staging, runtime, canary, settlement and API pytest suite passed (98 tests).",
    "Code-size, product-doc, Markdown-control, init-pro structural, JSON and git diff checks passed."
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
  "result": "Added explicit global 27 offline migration for authorized Actor validation caps: exact ledger CHECK upgrades to per-candidate $0.20 and batch $0.60, with pre-network fail-closed gating on un-migrated stores.",
  "status": "completed",
  "task_id": "2026-08-21-actorops-validation-cap-v27",
  "unresolved": [],
  "validation": [
    "100 targeted ActorOps tests",
    "schema migration dry-run",
    "impacted control preflight",
    "control validators"
  ]
}
```

```json
{
  "control_topics": [
    "decisions",
    "interface"
  ],
  "recorded_on": "2026-08-21",
  "result": "Hardened the validation-cap migration to verify SQLite integrity and foreign keys before backup or writes, after finding pre-existing local database corruption during the authorized offline attempt.",
  "status": "completed",
  "task_id": "2026-08-21-actorops-validation-cap-prehealth",
  "unresolved": [
    "Local service.db requires separate offline recovery before paid Actor validation can resume."
  ],
  "validation": [
    "101 targeted ActorOps tests",
    "migration health-gate test",
    "code-size and diff checks"
  ]
}
```

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
