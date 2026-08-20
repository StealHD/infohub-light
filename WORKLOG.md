# WORKLOG

<!-- init-pro:compact-worklog schema=1 -->

Entries are maintained by `worklogctl.py`; read-only and no-op tasks are not logged.


```json
{
  "control_topics": [
    "interface"
  ],
  "recorded_on": "2026-08-17",
  "result": "修复 YouTube pending_validation binding 在启动 Actor 前直接失败的问题：未完成来源 Canary 时仍走免费 Atom/RSS，认证后才 Actor-first。",
  "status": "completed",
  "task_id": "2026-08-17-youtube-pending-binding-fallback",
  "unresolved": [],
  "validation": [
    "YouTube fallback、来源采集、Worker 与 Actor runtime 定向 Pytest 61 项通过。",
    "产品文档与代码规模检查通过；8080 将在提交后重建。"
  ]
}
```

```json
{
  "control_topics": [
    "interface"
  ],
  "recorded_on": "2026-08-17",
  "result": "修复 ActorOps 候选与执行链路：候选选择区只显示已完成 Canary、费用对账和来源验证的固定 Build；未实测但免费合格的候选由服务端受控试跑。来源返回旧内容仅记录该来源目标退化，不再全局熔断 Actor；新增/替换 Canary 始终携带冻结的目标槽位，避免计划重算冲突。",
  "status": "completed",
  "task_id": "2026-08-17-actorops-certified-candidates",
  "unresolved": [],
  "validation": [
    "完整 impacted preflight 通过：完整 Pytest、79 个 Vitest 文件（684 项）、TypeScript、ESLint、生产前端构建、控制文件、产品文档与代码规模检查均通过。",
    "本地容器重建后将进行无费用执行快照和受控 Canary 验收；Canary 是否成功取决于第三方 Actor 的实际返回与账单对账。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "interface"
  ],
  "recorded_on": "2026-08-17",
  "result": "修复 ActorOps 免费 Discovery 只读取容器环境变量、而 Canary 从 SecretStore 读取 Apify Key 的断链；Discovery 现在复用运行时 SecretStore，重建后可继续按 Route 类型免费发现候选。同步更新候选实测规则说明与变更日志。",
  "status": "completed",
  "task_id": "2026-08-17-actorops-discovery-secretstore",
  "unresolved": [
    "本轮 X 的三个不同发布者候选均经受控 Canary 确认未返回可订阅动态，已终态排除；当前没有可安全加入 backup_2 的外部 Actor。"
  ],
  "validation": [
    "新增 SecretStore 凭据解析单测；Actor Discovery 定向回归 53 项通过。",
    "受影响 preflight 全部命令通过：全量受影响 Python、前端 lint/typecheck/Vitest、产品文档、代码规模与 E2E 合同检查。",
    "待提交后重建 8080，并验证 API/Worker 健康、前端资产和 Discovery 的 SecretStore 凭据读取。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "interface"
  ],
  "recorded_on": "2026-08-18",
  "result": "修复 X 免费 Discovery 的终态候选计数：它现在复用候选选择器的资格判定，固定 Build 若有确定性 Canary 失败或已在当前主备池运行，会作为已排除计为 0，不再显示为可验证后又在下一步拒绝。",
  "status": "completed",
  "task_id": "2026-08-18-actorops-x-candidate-count",
  "unresolved": [
    "当前 X 没有可安全加入 backup_2 的新 Build；已证伪的候选不会再触发付费验证。"
  ],
  "validation": [
    "X 候选计数、Discovery 与兼容 Canary 定向 Pytest 69 项通过。",
    "受影响 preflight 15/15 命令通过；待本地 8080 重建后进行实际免费 Discovery 验收。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "interface"
  ],
  "recorded_on": "2026-08-18",
  "result": "完成本地 X ActorOps 的端到端受控验收：免费 Discovery 仅保留一个安全候选，Canary 通过 Route 与两个启用来源验证后以原子方式补入 backup_2；随后真实来源更新成功，旧的 runnable Revision 失败不再复现。",
  "status": "completed",
  "task_id": "2026-08-18-actorops-x-runtime-canary",
  "unresolved": [
    "当前来源持久化 fetch_limit 为 20；若 UI 仍显示 10，需要另行修复表单显示与保存值的同步。",
    "YouTube 的外部 RSS/Atom 可靠性未包含在本次 X 验收内。"
  ],
  "validation": [
    "付费 Canary：Route 与 2 个已启用 X 来源均为 valid_nonempty，实际结算 $0.0133746，低于 $0.30 上限。",
    "真实 source_fetch 成功：抓取 20 条，入库 13 条，新增 8 条，并生成用户快照。",
    "本地 8080 API/Worker 健康，运行 e0a4149b603d；此前定向 Pytest 69 项与受影响 preflight 15/15 通过。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "interface"
  ],
  "recorded_on": "2026-08-18",
  "result": "修复跨平台 Actor Canary 边界：X 专用兼容流程已禁止用于非 X Route；YouTube 旧占位输出仅可在通过免费 Build/输入/价格/权限检查后，对固定公开频道执行一次受控 Canary，并从匹配的真实视频行生成无值、不可变 Manifest。自动计划只使用当前或安全回退 Discovery Run，并按公开评分/使用量选择，单槽替换只验证目标新槽。",
  "status": "completed",
  "task_id": "2026-08-18-youtube-observed-canary-routing",
  "unresolved": [],
  "validation": [
    "完整 impacted preflight 17/17 通过：全量 Pytest、Python 编译、前端 lint/typecheck/Vitest/build、控制文件、产品文档、代码规模与 E2E 合同检查。",
    "对运行数据库只读演算：YouTube replace plan 正确排序 grow_media、scrapesmith、scrapestorm，单候选总批准上限 $0.04；尚未执行外部付费 Canary。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "interface"
  ],
  "recorded_on": "2026-08-18",
  "result": "修复 ActorOps 槽位实测计划的 Run 一致性：添加/替换槽位始终以当前槽位候选投影的 run_id 与 goal 生成 Canary 计划，不再误用旧工作流；同时禁止 YouTube/Instagram 将旧 legacy shortfall 投影为仅限 X 的 compatibility_single 流程。",
  "status": "completed",
  "task_id": "2026-08-18-actorops-slot-plan-consistency",
  "unresolved": [],
  "validation": [
    "YouTube/X ActorOps 定向 Pytest 41 项通过。",
    "ActorOps 前端 Vitest 74 项、TypeScript typecheck 与 ESLint 通过。",
    "后端与前端冻结文件代码规模检查、git diff --check 通过；待提交后重建 8080 验收当前遗留兼容阶段清理与实际 Canary 计划。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-18",
  "result": "ActorOps 浏览器候选目录仅发布已完成 Route、全部启用来源实测和费用对账的 Actor；选择只做零费用原子启用或替换。",
  "status": "completed",
  "task_id": "2026-08-18-actorops-verified-catalog",
  "unresolved": [],
  "validation": [
    "定向 Pytest 63 通过，前端 typecheck 与定向 Vitest 7 通过。",
    "影响范围 preflight 17/17 通过，覆盖后端、前端、可观测性、控制面、文档和尺寸门禁。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-18",
  "result": "统一 ActorOps 三平台能力矩阵：X、Instagram、YouTube 均使用显式主抓取契约与 2 个不同发布者的最低健康池；YouTube 不再以 Atom/RSS fallback 或单 Actor 作为标准运行态。恢复流程会把 Worker 重启中断的 Run、验证、批次项、阶段与 Job 一起投影为可对账阻断，并仅以 GET 方式对已存在远端 Run 对账后继续原批准批次。",
  "status": "completed",
  "task_id": "2026-08-18-actorops-unified-primary-recovery",
  "unresolved": [
    "本地 YouTube 已存在的远端 Canary Run 会在新 Worker 启动后仅做状态/费用对账；若远端仍未终态，系统保持阻断且不新发付费 Run。"
  ],
  "validation": [
    "完整 impacted preflight 17/17 通过，包含全量 Pytest、前端 typecheck/Vitest/build、E2E 合同、控制与产品文档检查。",
    "新增重启恢复回归覆盖：未知启动会同时阻断 Validation、Batch item、Batch、Stage 和 Job；YouTube 旧 1/3 fallback 配置会收敛到注册的 primary 2/3 策略。"
  ]
}
```

```json
{
  "control_topics": [
    "capabilities",
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-18",
  "result": "为输出 Schema 不透明但免费安全条件已通过的 YouTube channel/items Actor 增加受控观察路径：先以真实目标进行一次受控 Canary，只有返回内容、身份和费用均完成核验后才生成可选的固定 Revision；同一 Build/Schema/价格的确定性付费失败会在免费发现阶段拦截。",
  "status": "completed",
  "task_id": "2026-08-18-youtube-observed-candidate-certification",
  "unresolved": [],
  "validation": [
    "发现、Canary、池变更相关 Pytest 111 项通过。",
    "前端类型、lint 与已验证候选筛选 Vitest 通过。"
  ]
}
```

```json
{
  "control_topics": [
    "capabilities",
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-18",
  "result": "允许历史遗留的单条已验证 Actor 池按第一个空槽受控补足第二条；补位仍须完成 Canary、费用对账和来源验证，当前池不会提前切换。",
  "status": "completed",
  "task_id": "2026-08-18-partial-pool-recovery",
  "unresolved": [],
  "validation": [
    "Pool management、staging 与 API 回归 69 项通过。",
    "前端 typecheck、lint、产品文档与代码规模检查通过。"
  ]
}
```

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
