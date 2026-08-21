# WORKLOG

<!-- init-pro:compact-worklog schema=1 -->

Entries are maintained by `worklogctl.py`; read-only and no-op tasks are not logged.


```json
{
  "control_topics": [
    "architecture",
    "decisions",
    "interface",
    "phase"
  ],
  "recorded_on": "2026-08-20",
  "result": "从本地 main 基线创建 codex/actorops-v2 worktree，完成 ActorOps v2 Phase 0：盘点现役代码、31 张相关表、Worker/API/UI/测试与删除地图，确定 stable-fetch-first、每订阅能力独立 Adapter、global 26、显式原生降级和有界站立授权的 planned 合同；未修改产品运行逻辑。",
  "status": "completed",
  "task_id": "2026-08-20-actorops-v2-phase0",
  "unresolved": [],
  "validation": [
    "ActorOps/迁移/Worker Discovery/YouTube 后端定向 Pytest 481 项通过；ActorOps 前端 Vitest 9 个文件、35 项通过。",
    "Markdown 控制与产品文档定向 Pytest 12 项通过；init-pro schema 3 结构校验和 git diff --check 通过。"
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
  "recorded_on": "2026-08-20",
  "result": "完成 ActorOps v2 Phase 1：新增无平台分支的 Domain、Adapter Port/Registry、Policy 和事务 Repository；global 26 以七张小表、单调 trigger、fresh bootstrap、v24 摘要 backfill 与显式离线 CLI 落地。existing v24 缺少 26 时 v1 API/Worker readiness 不变，global 25 不读写，v2 Runtime/真实 Adapter/feature flag 仍停用。",
  "status": "completed",
  "task_id": "2026-08-20-actorops-v2-phase1",
  "unresolved": [
    "完整 impacted preflight 的首次与允许的一次重跑均在既有 up-latest 测试的 0.5 秒夹具超时处停止；夹具已改为 2 秒，失败 spec 与整份 31 项 runtime-script 测试随后通过。按完整 gate 最多重跑一次的规则未进行第三次完整运行。"
  ],
  "validation": [
    "ActorOps、迁移、Worker Discovery 与 YouTube 定向 Pytest 503 项通过；Phase 1 新 Domain/Repository/migration 契约包含在内。",
    "前端 Vitest 82 文件/621 项、ESLint、TypeScript、生产构建通过；初始 JavaScript Brotli 236592 bytes。",
    "代码大小、Markdown、产品文档、init-pro schema 3、worklog/JSON 与 git diff 检查通过；最大新生产文件 370 行。"
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
  "recorded_on": "2026-08-20",
  "result": "完成 ActorOps v2 Phase 2：新增默认关闭的稳定获取数据面、X/Instagram/YouTube 独立 Adapter、Active→Standby→LKG、幂等 Attempt、局部 publication fence、YouTube 公共 Atom 降级和 v1/v2 双门兼容入口；全部 Route 保持 disabled，未切真实流量。",
  "status": "completed",
  "task_id": "2026-08-20-actorops-v2-phase2",
  "unresolved": [],
  "validation": [
    "ActorOps v2、迁移/readiness、来源获取、Worker、Feed 与现役 v1 兼容定向测试全部通过；新生产文件均小于 400 行，backend code-size 硬门禁通过。",
    "impacted preflight 17/17 通过：完整受影响后端/前端、产品文档、控制面、构建与静态检查均成功，无 SQLite 连接警告。"
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
  "recorded_on": "2026-08-20",
  "result": "完成 ActorOps v2 Phase 3：新增只读 Reconciler、Apify durable Run ledger 与费用结算；unknown start 仅在精确空窗口证明后终态化，未发布远端成功不推进 Feed/LKG。Worker 普通 Job 先 claim，Provider/v1/v2 对账移至 post-job/idle housekeeping；默认 flag 与 Route disabled 行为保持不变。",
  "status": "completed",
  "task_id": "2026-08-20-actorops-v2-phase3",
  "unresolved": [],
  "validation": [
    "ActorOps v2 Reconciler/ledger/runtime、Worker isolation、v1 pool/restart/readiness/source-acquisition 定向 Pytest 通过。",
    "impacted preflight 17/17 通过；代码大小、Markdown、init-pro schema 3、product-doc review 与 git diff 检查通过。"
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
  "recorded_on": "2026-08-20",
  "result": "完成 ActorOps v2 Phase 4：新增可恢复 Discovery 的安全 checkpoint、exact Build/Schema 验证、确定性优先 Manifest 映射和非关键 AI 补充；新增只读 Apify Catalog 边界和独立 v2 Discovery Worker Job。默认 flag/Route disabled 不变，不启动 Actor、Probe 或费用预留。",
  "status": "completed",
  "task_id": "2026-08-20-actorops-v2-phase4",
  "unresolved": [],
  "validation": [
    "ActorOps v2 Discovery/Catalog/Repository/Adapter、Worker v2 Discovery、Phase 2/3 和 v1 Discovery/Worker 定向 Pytest 通过。",
    "impacted preflight 17/17 命令通过；Markdown、init-pro schema、worklog、JSON 与 diff 校验通过。"
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
  "recorded_on": "2026-08-20",
  "result": "完成 ActorOps v2 Phase 5：新增默认关闭的双 policy Owner/Admin 授权、免费 exact-revision 预检、单 Candidate Probe 账本、每 Route UTC 日/Workspace UTC 月预算、自动补 Standby 与非最后一路原子替换；最后一个 runnable Candidate 保持 assignment 并记录安全保护码。维护 Job 仅在 flag=true 的 post-job/idle housekeeping 低优先级入队，不改 API/UI、Route mode、Feed/LKG 或真实平台流量。",
  "status": "completed",
  "task_id": "2026-08-20-actorops-v2-phase5",
  "unresolved": [],
  "validation": [
    "ActorOps v2 Phase 1–5、Worker maintenance/isolation、v1 Worker/source-acquisition/native-fallback/readiness 定向 Pytest 通过。",
    "唯一 impacted preflight 17/17 通过：完整 Pytest、82 个 Vitest 文件/621 项、lint、TypeScript、前端构建、控制文件、产品文档与代码规模检查均成功，且无 SQLite 连接警告。"
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
  "recorded_on": "2026-08-20",
  "result": "完成 ActorOps v2 Phase 6 的默认关闭代码护栏：离线 Route mode CAS、零值 shadow 选择事件、安全切流状态/备份/验证 CLI、稳定内容身份和 YouTube v2 RSS 兼容桥；未执行真实 migration、shadow/active、远端 Actor、来源获取或 Worker 重启。",
  "status": "partial",
  "task_id": "2026-08-20-actorops-v2-phase6",
  "unresolved": [
    "需在停止本地 API/Worker 后逐平台运行 CLI 状态/快照，取得 YouTube、Instagram、X 各自精确费用上限的明确授权，才能执行真实切流验收。"
  ],
  "validation": [
    "ActorOps v2 cutover、runtime/readiness/reconciliation/Discovery/maintenance、来源接入与 v1 回归定向 Pytest 通过。",
    "唯一完整 impacted preflight 17/17 通过：完整 Pytest、82 个 Vitest 文件/621 项、lint、TypeScript、前端构建、控制文件、产品文档与代码规模检查均成功。"
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
  "result": "修正 ActorOps v2 global 26 migration 对 v1 终态 Attempt 的安全判定：valid_empty、actor_failed 与 target_failed 不再被误认作 inflight，仍由独立费用条件阻断未结实际费用。实际本地 dry-run 因 21 条 Attempt 未结费用、126 条 Run 未结费用、1 个运行 Batch 和活跃 Worker 继续 fail closed；未执行 migration、切流或来源调用。",
  "status": "partial",
  "task_id": "2026-08-21-actorops-v2-migration-settlement",
  "unresolved": [
    "需先由现役 v1 对账安全结算全部 Attempt/Run 费用并收敛 running batch，停止 API/Worker 后才能执行 global 26 migration。"
  ],
  "validation": [
    "新增三种 v1 终态 Attempt 的 migration 回归测试；迁移测试文件 12 项通过。",
    "唯一 impacted preflight 15/15 通过：Python、前端相关检查、产品文档、控制文件与代码规模检查均成功。"
  ]
}
```

```json
{
  "control_topics": [
    "phase"
  ],
  "recorded_on": "2026-08-21",
  "result": "执行 ActorOps v2 Phase 6 YouTube 本地迁移前检查：停止 API/Worker、跨 heartbeat 安全窗后运行一次有界既有 terminal Run 对账和本地费用投影。抽样 Provider GET 返回 404，历史远端费用无法证明；global 26 继续因 21 条 Attempt 未结费用、126 条 Run 未结费用和 1 个 running Batch fail closed。未执行 migration、shadow/active、Actor POST、来源获取或 VPS 发布；已恢复现役 v1 API/Worker healthy。",
  "status": "blocked",
  "task_id": "2026-08-21-actorops-v2-youtube-cutover-preflight",
  "unresolved": [
    "需要 Provider 可验证的历史 Run 费用结算或经人工审计的恢复路径；不得把 404 的历史 Run 费用伪造为零。"
  ],
  "validation": [
    "本地 API/Worker 均恢复 Docker healthy，ready 端点成功。",
    "迁移 dry-run 证明 global 25 未读取，且阻断计数保持精确。"
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
  "result": "实现 Phase 6R 历史 Actor 费用审计与隔离：新增仅 GET、最多 20 条的安全证据 CLI；200 才精确结算，404 保留最坏预留并写 quarantine code，未知/认证/限流/非终态继续阻断；迁移仅对精确终态隔离事实解除费用 blocker。未对本地运行数据库执行 scan、snapshot、apply 或 global 26 migration。",
  "status": "partial",
  "task_id": "2026-08-21-actorops-v2-legacy-cost-isolation",
  "unresolved": [
    "需要在已提交 revision 上运行真实只读 scan，取得 evidence hash 与最坏费用上限后，等待单独确认才可 snapshot/quarantine apply。"
  ],
  "validation": [
    "ActorOps v2 legacy audit、migration 与 cutover 定向测试 33 项通过。",
    "impacted preflight 静态门禁 7/7 通过；Markdown、schema-v3 controls、worklog 与 diff 检查通过。"
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
  "result": "在提交 3e7db56 上对本地运行数据库执行一次只读 legacy cost scan：最多 20 条已知 terminal Run 的 authenticated GET 均返回 404，未写数据库、未创建 evidence/backup 文件、未执行 quarantine apply、global 26 migration、shadow、active 或来源获取。",
  "status": "blocked",
  "task_id": "2026-08-21-actorops-v2-legacy-cost-scan",
  "unresolved": [
    "必须先取得对 evidence hash a69e48e944bae5322ad3c80f88e8d5092a0b1b8b35f8ff39d7993fb27d0b07cf 和 USD 1.24 的明确确认，才可停服务、跨 heartbeat、snapshot/quarantine 这一批；之后仍需分批扫描/确认剩余 106 条 Run。"
  ],
  "validation": [
    "scan evidence_hash=a69e48e944bae5322ad3c80f88e8d5092a0b1b8b35f8ff39d7993fb27d0b07cf；safe counts 为 quarantine_run=20、quarantine_attempt=17、quarantine_batch=1，remaining_remote_runs=106。",
    "本批 historical unknown upper bound 为 USD 1.24；该值是未结预留的保守上限，不是已结算或可用余额。"
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
  "result": "Phase 6R.1 adds a private resumable legacy-cost evidence session: scan reuses one salt, covers at most 20 new terminal Runs per page, retries blocked observations only explicitly, and snapshot validates the complete session without network before creating a private backup/receipt; quarantine requires that receipt and applies all facts in one CAS transaction.",
  "status": "partial",
  "task_id": "2026-08-21-actorops-v2-legacy-cost-evidence-session",
  "unresolved": [
    "Run the full read-only seven-page session against the local runtime database; obtain an exact evidence hash and conservative upper bound, then wait for explicit confirmation before snapshot/quarantine/global 26 migration."
  ],
  "validation": [
    "36 focused ActorOps v2 audit/migration/cutover tests passed.",
    "Impacted preflight passed 15/15: full Python domain, syntax, code size, product-doc review, frontend lint/typecheck/related Vitest and controls."
  ]
}
```

```json
{
  "control_topics": [
    "phase"
  ],
  "recorded_on": "2026-08-21",
  "result": "Completed the full resumable read-only legacy Actor Run audit against the local runtime database: 126 terminal Runs are covered in one private 0600 evidence session across seven normal pages plus one explicit retry page. The session records 124 historical 404 quarantines, 2 exact provider costs totaling USD 0.01705, 17 orphan Attempt quarantines and 1 eligible legacy Batch quarantine; no service.db facts, routes, migration markers, sources or Actors were written or started.",
  "status": "blocked",
  "task_id": "2026-08-21-actorops-v2-legacy-cost-full-audit",
  "unresolved": [
    "Evidence hash 700c332c3f9e2952aa3cc0eb80d1713c062b98ca889dbb84d755e5827af7b7db has conservative unknown upper bound USD 1.28. Explicit confirmation of this exact value is required before stopping services, snapshot/quarantine apply and the same-window global 26 migration."
  ],
  "validation": [
    "Evidence session: scan_pages=8, remaining_remote_runs=0, mode=0600; provider_cost=2, quarantine_run=124, quarantine_attempt=17, quarantine_batch=1.",
    "Audit and migration status remain blocked at run_costs=126, attempt_costs=21 and batches=1, proving the read-only scan did not mutate legacy facts; global 25 remains ignored."
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
