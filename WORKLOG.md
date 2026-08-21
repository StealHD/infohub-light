# WORKLOG

<!-- init-pro:compact-worklog schema=1 -->

Entries are maintained by `worklogctl.py`; read-only and no-op tasks are not logged.


```json
{
  "control_topics": [
    "capabilities",
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-19",
  "result": "已登记的 X、Instagram 与 YouTube ActorOps Route 以“每次获取条数”直接请求最新 N 条，不再把 Feed 的短显示窗口当作 Actor 抓取窗口；未知平台组合在创建 Actor 客户端前拒绝。YouTube 与此前失败的 X 来源均完成本地真实任务验收并返回 valid_nonempty。",
  "status": "completed",
  "task_id": "2026-08-19-actorops-latest-items-runtime",
  "unresolved": [],
  "validation": [
    "完整 impacted preflight 17/17 通过（完整 Python、Vitest、类型检查、构建与产品文档）。",
    "本地 8080 revision 5301e4b4e070 健康；YouTube 获取 2 条/新增 1 条，X 获取 20 条/新增 1 条，最终 Actor 尝试均为 valid_nonempty。"
  ]
}
```

```json
{
  "control_topics": [
    "phase"
  ],
  "recorded_on": "2026-08-20",
  "result": "将当前 ActorOps 候选恢复与一键自动槽位替换候选版准备为 v2.3.5-beta.1；本次只发布 GitHub beta Tag/Release，明确不切换 VPS 生产运行面。",
  "status": "completed",
  "task_id": "2026-08-20-release-v2.3.5-beta.1",
  "unresolved": [],
  "validation": [
    "beta Tag 仅在精确 main SHA 的 GitHub Test Gate 成功后创建，并继续通过 Release Tag 隔离 API smoke。",
    "VPS 保持 v2.3.4/cdced69ed4ef，API/Worker healthy；本次不构建、不上传、不切换生产镜像。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "capabilities",
    "interface",
    "phase",
    "ui"
  ],
  "recorded_on": "2026-08-20",
  "result": "ActorOps 退役未发布的自动付费/自动生效 auto-pool，新增替换回归一次免费 Discovery、付费确认 1/2 与生效确认 2/2；所有 Route 单 Run 上限统一为 $0.10，global 23/24 门禁和 global 25 惰性兼容完成收口。",
  "status": "partial",
  "task_id": "actorops-safe-retirement-dual-confirmation",
  "unresolved": [
    "真实库仍有 1 个历史 auto-pool Batch、2 个费用节点和 1 个无关 acquisition Run 未终态；两次显式精确 GET 对账均返回 unresolved。Worker 保持停止，未执行 retirement apply 或本地重启。"
  ],
  "validation": [
    "最终 impacted preflight 17/17 通过，覆盖完整后端/前端、控制面、代码大小、产品文档、构建与静态检查。",
    "ActorOps 后端定向回归、34 个前端 ActorOps Vitest、TypeScript、ESLint、UI contract、生产构建及双确认 Playwright 通过；未调用 Actor POST、AI 或通知。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "interface"
  ],
  "recorded_on": "2026-08-20",
  "result": "离线精确 GET 对账已将历史 auto-pool 批次和费用全部终态化；按标准脚本重建本地 API 与 Worker，运行修订为 dce4ded63143-dirty。",
  "status": "completed",
  "task_id": "actorops-retirement-reconcile-and-local-rebuild",
  "unresolved": [
    "仍有 1 个非 auto 的 acquisition Run 在途，由重建后的 Worker 按既有安全路径继续处理。"
  ],
  "validation": [
    "auto-pool retire/reconcile 定向 Pytest 10 项通过。",
    "retirement inspect 显示 0 个非终态 auto Batch、0 笔未结 auto 费用、0 个 unknown-start；API/Worker 均 healthy，ready 返回 ready。"
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-20",
  "result": "修复 ActorOps 在 Worker 重启后对已登记远端 Run 不做状态读取而长期阻塞的问题：未知启动继续禁止同任务切备或重跑，Worker 只读核对原 Run，终态入账后由既有恢复链路解除屏障；主备用 UI 现在会正确显示不可运行槽位。",
  "status": "completed",
  "task_id": "2026-08-20-actorops-registered-run-recovery",
  "unresolved": [],
  "validation": [
    "完整 impacted preflight 17/17 通过：全量 Pytest、82 个 Vitest 文件/621 项、lint、TypeScript、前端构建、控制与产品文档门禁均通过。",
    "ActorOps 映射 Playwright（actorops-pool-management 与 production-admin）66 项通过；ActorOps 桌面明暗视觉基线已同步。"
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
