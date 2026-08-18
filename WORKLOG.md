# WORKLOG

<!-- init-pro:compact-worklog schema=1 -->

Entries are maintained by `worklogctl.py`; read-only and no-op tasks are not logged.


```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-15",
  "result": "将 ActorOps 移动端深色发布截图更新为 Linux 实际基线，并移除 Insights 关闭动画卸载窗口中的易失 inert 读取。",
  "status": "completed",
  "task_id": "2026-08-15-release-v2.3.3-linux-e2e-followup",
  "unresolved": [],
  "validation": [
    "GitHub Linux UI E2E 工件确认两个测试根因：深色基线过期和关闭动画竞态。",
    "本地发布构建下 Insights 与 ActorOps visual 定向回归 3 通过、1 按桌面限定跳过。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-15",
  "result": "移除 Insights 关闭动画中已卸载面板的两个瞬态 aria 属性断言，仅保留用户可观察的关闭完成状态，并继续收紧旧测试文件规模上限。",
  "status": "completed",
  "task_id": "2026-08-15-release-v2.3.3-linux-e2e-race-removal",
  "unresolved": [],
  "validation": [
    "GitHub Linux CI 工件定位为关闭动画竞态；不是产品接口或布局回归。",
    "生产构建下同一 Insights 几何流程连续 5 次通过；代码规模检查通过，旧文件由 1801 降至 1799 行。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture"
  ],
  "recorded_on": "2026-08-15",
  "result": "以冻结历史单体、任务基线净增长比较、新文件/函数硬上限和风险映射选测替代精确行数债务，并让本地与 VPS 共用可等待 Docker starting 的发布健康检查与一致性回滚。",
  "status": "completed",
  "task_id": "2026-08-15-lightweight-code-test-gates",
  "unresolved": [],
  "validation": [
    "定向规模、影响选择、E2E 合同、共享健康、发布与产品文档测试全部通过。",
    "staged preflight 18/18、完整 Test Gate 19/19 通过，均无 SQLite 资源告警；未运行付费 Actor、AI、真实通知或来源抓取。"
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-15",
  "result": "统一来源单次获取条数：RSS、YouTube、GitHub、Reddit、Telegram 与受控社交来源均可设置 1–100 条；X 的 ActorOps 执行不再固定为 1 条。",
  "status": "partial",
  "task_id": "2026-08-15-source-fetch-limit-settings",
  "unresolved": [
    "完整受影响预检在修复前的远程 MCP 设置指引回归处中断；该用例已单独通过，但未第三次运行完整预检，以遵守完整门禁重跑上限。"
  ],
  "validation": [
    "来源注册、RSS、YouTube、GitHub、ActorOps、MCP 设置指引与订阅服务的定向 Pytest 均通过。",
    "YouTube 来源表单 Vitest、前端 lint 和 typecheck 通过；Python 语法、代码大小、产品文档与控制文件检查通过。"
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-15",
  "result": "平台连接暂不可用时，既有 X、Instagram、YouTube 来源的账号目标与启用状态继续锁定，但可修改每次获取条数和分析模式；无字段定义的历史社交来源仍只允许元数据编辑。",
  "status": "completed",
  "task_id": "fix-platform-fetch-limit-editing",
  "unresolved": [],
  "validation": [
    "App 与来源表单 Vitest 共 123 项通过；ESLint 与 TypeScript 通过。",
    "影响范围 preflight、控制文件与代码规模检查通过。"
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-15",
  "result": "来源与订阅设置的提交、测试、获取和关闭操作收敛为同一底部操作行并统一紧凑高度；取消订阅改为独立确认弹窗，保留焦点回归与待处理锁定。",
  "status": "completed",
  "task_id": "subscription-dialog-footer-polish",
  "unresolved": [],
  "validation": [
    "订阅表单与 App Vitest 共 123 项通过；最终受影响预检 12/12 通过。",
    "前端生产构建、UI 合同、ESLint、TypeScript、代码规模与产品文档检查通过。"
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
  "recorded_on": "2026-08-15",
  "result": "完成 v2.3.4 的发布准备与发布链路审查：统一各来源单次获取条数、恢复平台暂不可用时的可编辑限额，并收敛来源/订阅设置操作区和取消订阅确认交互。",
  "status": "completed",
  "task_id": "2026-08-15-release-v2.3.4",
  "unresolved": [],
  "validation": [
    "相对 v2.3.3 的完整 preflight 18/18 通过，覆盖后端、前端、产品文档、控制文件、代码规模及发布约束。",
    "发布脚本审查确认使用本地 linux/amd64 构建、VPS docker load、精确 main CI/Tag smoke、API/Worker/前端 revision 健康验证与可验证回滚。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture"
  ],
  "recorded_on": "2026-08-15",
  "result": "修复 v2.3.4 发布门禁在浅克隆 CI 中无法解析代码规模初始基线的问题：所有 Test Gate Job 统一完整历史检出，使策略祖先验证在 impact、后端、前端、E2E 和 tag smoke 路径一致可用。",
  "status": "completed",
  "task_id": "2026-08-15-release-v2.3.4-ci-history",
  "unresolved": [],
  "validation": [
    "发布工作流回归断言与代码规模策略定向 Pytest 14 项通过。",
    "相对 v2.3.3 的完整 preflight 18/18 通过，包含后端、前端、产品文档、控制文件和代码规模检查。"
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
  "result": "YouTube 已改为来源 Canary 成功后的认证 Actor 主抓取，Atom 仅在该次 Actor 失败时降级；X 与通用 Actor 统一按发布时间倒序返回，并保留 Actor 水位证明。",
  "status": "completed",
  "task_id": "2026-08-17-stable-actor-subscriptions",
  "unresolved": [],
  "validation": [
    "Pytest 39 项定向回归通过，覆盖 YouTube 来源绑定、Actor 主抓取、失败阻断、X/通用最新排序与缓存上下文。",
    "代码规模、控制文件、产品文档、TypeScript 与 ESLint 检查通过；受影响完整 preflight 首轮发现旧订阅事务约束，修复后对应失败用例通过。"
  ]
}
```

```json
{
  "control_topics": [
    "interface"
  ],
  "recorded_on": "2026-08-17",
  "result": "修复已验证来源的目标级备用暂停误触发全 Route shortfall；X 可继续使用已实测成功主槽，YouTube 只接受能以 UC Channel ID 输入并证明频道身份的 Actor 合同。",
  "status": "completed",
  "task_id": "2026-08-17-source-bound-actor-runtime",
  "unresolved": [
    "完整受影响预检在未改动的 Remote MCP 用例出现一次偶发失败，单独重跑通过；未重复整套预检。"
  ],
  "validation": [
    "X 两个真实 source binding 本地冻结验证：受影响来源保留主 Actor，另一来源保留主备。",
    "ActorOps/来源采集/Worker 定向 Pytest 182 项、TypeScript、ESLint、控制文件和产品文档检查通过。"
  ]
}
```

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
