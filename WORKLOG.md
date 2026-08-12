# WORKLOG

<!-- init-pro:compact-worklog schema=1 -->

Entries are maintained by `worklogctl.py`; read-only and no-op tasks are not logged.


```json
{
  "control_topics": [
    "decisions",
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-10",
  "result": "ActorOps legacy 升级始终把当前 ScrapeBadger、Dami 和 Xquik 排在候选最前，安全新版自动选中，未通过项显示状态；重复免费检查被服务端合并，顶部与页签外层方框阴影已移除。",
  "status": "completed",
  "task_id": "2026-08-10-actorops-current-actors-visible-deduplicate",
  "unresolved": [],
  "validation": [
    "ActorOps 候选、API 与 Discovery 后端回归 97/97 通过，覆盖当前三 Actor 排序、ranking 运行态与重复 Job 零调用 supersede。",
    "ActorOps 与 Changelog 前端 Vitest 61/61 及 TypeScript 类型检查通过。",
    "完整 Test Gate 24/24 命令通过（244.49 秒）。"
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-11",
  "result": "ActorOps 三个任务页签使用浅色强调底轨区分未选项，保留已选白色胶囊，不恢复外框或阴影。",
  "status": "completed",
  "task_id": "2026-08-11-actorops-tab-accent-rail",
  "unresolved": [],
  "validation": [
    "ActorOps 与 Changelog 前端 Vitest 61/61 及 TypeScript 类型检查通过。",
    "完整 Test Gate 24/24 命令通过（259.62 秒）。"
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
  "recorded_on": "2026-08-11",
  "result": "将 codex/actorops-guided-flow-20260809 合入本地 main；保留既有登录、专题、成员更新，并将 ActorOps 决策登记为 D140–D143，避免决策编号冲突。",
  "status": "completed",
  "task_id": "2026-08-11-merge-actorops-guided-flow-main",
  "unresolved": [],
  "validation": [
    "合并后完整 Test Gate 24/24 命令通过（265.70 秒）。",
    "已执行 diff --check；冲突仅涉及决策索引、更新记录和 Changelog 测试，均保留两侧内容。"
  ]
}
```

```json
{
  "control_topics": [
    "interface"
  ],
  "recorded_on": "2026-08-11",
  "result": "将包含 ActorOps schema 20–22 显式迁移的合并版本递增为 v2.2.14，避免复用已存在的 v2.2.13 Tag。",
  "status": "completed",
  "task_id": "2026-08-11-release-v2.2.14-actorops",
  "unresolved": [],
  "validation": [
    "发布前将重新运行精确 main SHA 的完整 Test Gate；线上迁移与切换按带 0600 备份的显式流程执行。"
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-11",
  "result": "修复 v2.2.14 发布 E2E：补齐 Linux 视觉基线和 ActorOps 安全候选 fixture，修正信息流新内容按钮层级与阅读锚点断言，并提高 Agent 抽屉中性状态的深色对比度。",
  "status": "completed",
  "task_id": "2026-08-11-release-e2e-stabilization",
  "unresolved": [],
  "validation": [
    "完整发布 E2E 162/162 通过。",
    "最终完整 Test Gate 24/24 命令通过（270.09 秒）。"
  ]
}
```

```json
{
  "control_topics": [
    "capabilities",
    "decisions",
    "interface",
    "phase",
    "ui"
  ],
  "recorded_on": "2026-08-11",
  "result": "基于当前 main 串行重建并集成 Legacy 退役改动，保留成员管理、来源总结和 ActorOps schema 20–22，将唯一运行面决策登记为 D144，并在完整验证后 fast-forward 本地 main。",
  "status": "completed",
  "task_id": "2026-08-11-integrate-retire-legacy-surfaces-main",
  "unresolved": [],
  "validation": [
    "现役认证、配置、Feed、API、Store、Worker、来源总结、ActorOps、通知、冷归档和 Remote MCP 定向回归通过。",
    "前端 check:ui、lint、typecheck、666 项 Vitest、production build 与 release Playwright（107 通过、55 按配置跳过）通过。",
    "组合结果 Test Gate full 与 release、Compose/API-only smoke、控制文件校验、负向引用和 diff 检查通过。"
  ]
}
```

```json
{
  "control_topics": [
    "context",
    "decisions",
    "instructions",
    "phase"
  ],
  "recorded_on": "2026-08-11",
  "result": "将 preflight 验证与发布身份加固合入本地 main；解决 D144 编号冲突，将流程决策登记为 D145，保留 main 的唯一运行面决策与紧凑 Worklog 历史。",
  "status": "completed",
  "task_id": "2026-08-11-merge-preflight-gate-main",
  "unresolved": [],
  "validation": [
    "合并范围 preflight 8/8 命令通过（37.64 秒），无 mapping miss。",
    "合并后本地 main 完整 Test Gate 15/15 命令通过（276.95 秒）。",
    "未安装或分发 Git hook，未推送、未打 Tag、未部署。"
  ]
}
```

```json
{
  "control_topics": [],
  "recorded_on": "2026-08-11",
  "result": "从本地 main revision a878b715c2b1 切换 8080 API 与 Worker，并安全清理旧本地构建镜像与过期构建缓存；未启动 scheduler。",
  "status": "completed",
  "task_id": "2026-08-11-main-local-runtime-cutover-preflight-gate",
  "unresolved": [],
  "validation": [
    "./scripts/up-latest.sh 在 main Worktree 构建并仅重建 horizon-api 与 horizon-worker；运行前确认活跃 fetch job=0、Feed schedule=0、无新增数据库迁移且无 scheduler 容器。",
    "API 与 Worker 均为 healthy；/api/health/live 返回 revision=a878b715c2b1，/api/health/ready 返回 worker_status=ready；前端资源 index-CgdKDeP4.js 已服务。",
    "当前仅保留 inteliscope-service:local-a878b715c2b1；旧 local 镜像标签 2 个已删除。"
  ]
}
```

```json
{
  "control_topics": [
    "interface"
  ],
  "recorded_on": "2026-08-11",
  "result": "将本地 main 的项目版本升级为 v2.3.1；手册和更新日志完成发布审阅并保留无用户可见条目的记录。",
  "status": "completed",
  "task_id": "2026-08-11-release-v2.3.1-git-publish",
  "unresolved": [],
  "validation": [
    "版本变更 preflight 13/13 通过（287.965 秒），产品文档门禁、后端完整回归、前端检查、构建与控制检查全部通过。",
    "正式 release gate 及 main 与 v2.3.1 推送将在该提交上执行；用户明确不部署 VPS。"
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-11",
  "result": "为订阅来源卡的非零今日、近 N 天和历史统计补齐对应快捷查询：今日与近 N 天直达带来源及时间范围的 Feed，历史保留现有历史查询。",
  "status": "completed",
  "task_id": "2026-08-11-subscription-stats-quick-query",
  "unresolved": [],
  "validation": [
    "订阅页、Feed 深链、手册和更新日志定向测试及 TypeScript/ESLint/UI 合同检查通过。",
    "完整 Test Gate 15/15 命令通过（285 秒）。",
    "./scripts/up-latest.sh 完成；API/Worker healthy、readiness 为 ready，8080 实际订阅页确认今日与近 7 天链接。"
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-11",
  "result": "合并助手连接创建流程的一次性 MCP token 复制体验：令牌单行省略并完整复制，环境写入与 OpenClaw 配置命令均使用右上角图标复制。",
  "status": "completed",
  "task_id": "2026-08-11-merge-openclaw-copy-ui",
  "unresolved": [],
  "validation": [
    "任务分支定向 Vitest 16/16、preflight 11/11 与完整 Test Gate 15/15 通过。",
    "合并后的产品更新日志同时保留订阅统计快捷查询和助手连接复制说明。"
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
  "recorded_on": "2026-08-11",
  "result": "将新增来源重构为平台导向的 X 账号、Instagram 账号与 YouTube 频道；Web 隐藏 Apify、Actor 和 Route 实现字段，服务端自动路由并保持旧来源兼容。X 兼容池升级只扩大当前三 Actor 的免费召回到 30，保留跨 Run 安全 Revision，价格、Schema、输入、Manifest、发布者和 Canary 底线不变，三路不足时关闭失败。",
  "status": "completed",
  "task_id": "2026-08-11-platform-source-setup-x-recall",
  "unresolved": [
    "付费 Route Canary 与最终 3/3 原子切换仍需用户分别明确确认。"
  ],
  "validation": [
    "后端定向回归 227/227、前端完整 Vitest 669/669 通过。",
    "影响 preflight 13/13 通过（247.445 秒），mapping_miss=false。",
    "完整 Test Gate 15/15 通过（247.778 秒），mapping_miss=false。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "decisions",
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-12",
  "result": "实现 ActorOps 功能优先兼容模式、来源内容水位与软切备、可配置专用 Key 新鲜度校验、失败指纹记忆和统一安全诊断时间线；YouTube fallback 一路即可运行且不再自动追逐第三槽。",
  "status": "completed",
  "task_id": "2026-08-12-actorops-compatibility-freshness-diagnostics",
  "unresolved": [
    "global schema 23 离线迁移与本地 8080 切换按计划在本提交后执行。",
    "未指定 validation Key，未授权自动新鲜度，也未运行兼容 Canary 或任何付费 Actor；这些动作保留给用户逐项确认。"
  ],
  "validation": [
    "ActorOps 后端发现、兼容、运行、水位、新鲜度、Key、API 与迁移定向回归通过。",
    "前端完整 Vitest 74 文件/676 测试此前通过；最终 ActorOps 62/62、TypeScript 与 ESLint 零错误通过。",
    "任务级 preflight 13/13、完整 Test Gate 15/15 通过（352.94 秒），mapping_miss=false。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-12",
  "result": "ActorOps 免费候选搜索改为有界进度与明确终态：提交后自动刷新并锁定重复操作，YouTube 可选第三路不足时说明现有 Atom Feed/fallback 不受影响；目标身份不匹配改为人类可读原因与恢复建议。",
  "status": "completed",
  "task_id": "2026-08-12-actorops-search-terminal-ui",
  "unresolved": [
    "8080 重建与真实浏览器验收将在完整门禁和任务提交后执行。"
  ],
  "validation": [
    "前端 ActorOps 定向 Vitest 66/66、TypeScript 类型检查与 ESLint 通过（仅仓库既有 Fast Refresh 警告）。"
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-12",
  "result": "修复 X 严格升级只保留 1 个合格 Actor 时无法进入下一步：compatibility_single 现跨免费检查复用同 Route 每个 Candidate 的最新安全 Revision，空搜索不再清掉已合格候选。",
  "status": "completed",
  "task_id": "2026-08-12-actorops-x-single-candidate-continuation",
  "unresolved": [
    "按用户要求，完整 Test Gate 留到最终合并代码时执行。"
  ],
  "validation": [
    "ActorOps compatibility 与 pool staging 定向后端回归 32/32 通过。",
    "待完成 preflight、8080 重建与浏览器只读验收。"
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-12",
  "result": "补齐 X 历史严格 Stage 的兼容降级：upgrade_legacy 处于 replan_required 且严格候选不足时，只要存在单个兼容候选就投影降低要求入口，并保留安全失败摘要。",
  "status": "completed",
  "task_id": "2026-08-12-actorops-x-replan-compatibility-entry",
  "unresolved": [
    "按用户要求，完整 Test Gate 留到最终合并代码时执行。"
  ],
  "validation": [
    "ActorOps compatibility 与 pool staging 定向后端回归 33/33 通过。",
    "真实 service.db 只读诊断确认严格 1/3、兼容列表 6 个可选，未触发搜索、Actor 或付费动作。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "decisions",
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-12",
  "result": "将平台导向新增来源、ActorOps 功能优先兼容/新鲜度/诊断能力与 X 单 Actor 继续流程合入本地 main；同时保留既有 MCP 令牌复制改动并解决决策编号冲突。",
  "status": "completed",
  "task_id": "2026-08-12-main-actorops-platform-source-integration",
  "unresolved": [
    "未选择 validation Key、未授权自动新鲜度，也未运行兼容 Canary 或任何付费 Actor；这些动作继续由用户逐项确认。"
  ],
  "validation": [
    "合并范围 preflight 13/13 通过（396.787 秒），mapping_miss=false。",
    "本地 main 完整 Test Gate 15/15 通过（427.315 秒），mapping_miss=false。",
    "决策记录保留 D146 MCP 复制，并将平台来源/ActorOps 韧性顺延为 D147/D148；WORKLOG 校验无 findings。"
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
  "recorded_on": "2026-08-12",
  "result": "只读诊断生产订阅抓取并在本地修复 X 旧数据假成功：生产每小时任务正常运行且 Dami 连续返回旧帖，schema 22 尚无来源水位；schema 23 上连续三次 no_advance 后，下一次自然计划会只调用一个健康备用，备用推进水位后成为来源活动 Actor。",
  "status": "completed",
  "task_id": "2026-08-12-production-x-stale-acquisition-failover",
  "unresolved": [
    "生产仍运行 2.2.14/schema 22，本次按用户要求仅只读检查生产并在本地修复，未修改生产、未部署、未运行付费 Actor。",
    "生产升级时必须先按离线流程应用 schema 23 migration，随后发布通过门禁的本地 main。"
  ],
  "validation": [
    "生产只读确认 API/Worker 健康，X 每小时任务成功但最新内容停在 2026-08-10，最近生产 Actor 为 Dami 且重复 valid_nonempty。",
    "Actor route、水位、resilience、source acquisition 与产品文档定向后端回归 83/83 通过；更新日志 Vitest 5/5、控制面校验通过。"
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-12",
  "result": "ActorOps 来源列表和详情现标记最近一次实际 Actor，并允许从下一次计划抓取起手动软切换；同时修复 X 单路兼容计划缺少 max_candidates 导致降低要求后返回 500 的问题，失败改为页面可见且不启动 Actor。",
  "status": "completed",
  "task_id": "2026-08-12-actorops-current-actor-switch-compatibility-plan",
  "unresolved": [
    "未执行任何付费 Canary、1/3 生效或生产部署；本地仅验证计划预览和现有来源状态。"
  ],
  "validation": [
    "ActorOps compatibility、API 与 route 定向后端回归 79/79 通过。",
    "ActorOps UI 与 changelog Vitest 73/73、TypeScript、UI 合同及 lint（0 error）通过。"
  ]
}
```

```json
{
  "control_topics": [
    "phase"
  ],
  "recorded_on": "2026-08-12",
  "result": "将当前本地 main 准备为 v2.3.2，推送精确发布提交并在 main Test Gate 成功后创建不可变发布标签。",
  "status": "completed",
  "task_id": "2026-08-12-release-v2.3.2",
  "unresolved": [],
  "validation": [
    "发布前检查和精确 main GitHub Test Gate 通过。",
    "v2.3.2 标签解析到已验证的 main 提交，Release Tag workflow 通过。"
  ]
}
```
