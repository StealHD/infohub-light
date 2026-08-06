# WORKLOG

<!-- init-pro:compact-worklog schema=1 -->

Entries are maintained by `worklogctl.py`; read-only and no-op tasks are not logged.


```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-04",
  "result": "为 Settings Workspace 发布补强选择器退出态可访问性，并消除原生 fetching 路由测试的异步挂载竞态；准备 v2.2.7 作为合规发布标签。",
  "status": "partial",
  "task_id": "2026-08-04-publish-settings-workspace-v227",
  "unresolved": [
    "等待最终 Release Gate、GitHub Release 与 VPS 安全切换。"
  ],
  "validation": [
    "Release Gate 首轮仅在 Select 退出态触发 Axe 对比度告警，修正后针对性 Playwright 通过。",
    "GitHub 首次 main 前端全量发现 fetching 路由断言竞态；修正后 App.test.tsx 定向 103/103 通过。"
  ]
}
```

```json
{
  "control_topics": [],
  "recorded_on": "2026-08-03",
  "result": "将包含 Telegram 多渠道通知与通用 ActorOps 控制面的合并结果升级为 2.2.0，准备创建 v2.2.0 注释标签、GitHub Release 与 revision-locked VPS 升级。",
  "status": "partial",
  "task_id": "2026-08-03-prepare-v2.2.0-actorops-release",
  "unresolved": [
    "release Test Gate、Git 推送、GitHub Release 与 VPS 部署尚待本任务后续步骤完成",
    "生产数据库迁移不调用 AI/Actor；任何真实付费 Canary 与生产 Route 激活仍保持独立审批"
  ],
  "validation": [
    "合并提交 5375da1 的 full Test Gate 23/23 通过",
    "项目与锁文件版本同步为 2.2.0",
    "v2.2.0 本地与远端 Tag 尚不存在"
  ]
}
```

```json
{
  "control_topics": [],
  "recorded_on": "2026-08-03",
  "result": "修正 v2.2.0 Release Gate 的 ActorOps、来源能力目录与 Changelog 浏览器验收契约，使验收脚本覆盖当前通用三槽控制面而非旧 X 专用界面。",
  "status": "partial",
  "task_id": "2026-08-03-align-v2.2.0-release-acceptance",
  "unresolved": [
    "完整 Release Test Gate、Tag、GitHub 发布与 VPS 部署尚待本任务后续步骤完成"
  ],
  "validation": [
    "Release Playwright 定向 15 项：13 passed、2 skipped",
    "订阅 capability catalog 404 消失，既有 light/dark 三视口截图无需更新",
    "ActorOps 通用路由表、当前三槽主备、全局 Discovery AI 和告警区域通过三视口可访问性验收"
  ]
}
```

```json
{
  "control_topics": [],
  "recorded_on": "2026-08-03",
  "result": "修复 v2.2.0 GitHub Linux UI Gate 暴露的移动端订阅视觉基线滞后；在隔离 linux/amd64 + Google Chrome 环境重生成 light/dark 基线，并将不可改写的公开失败标签后续版本升级为 2.2.1。",
  "status": "partial",
  "task_id": "2026-08-03-repair-v2.2.0-linux-visual-release-gate",
  "unresolved": [
    "v2.2.1 的 GitHub CI、Tag/Release、revision-locked 镜像与 VPS 正式切换尚待后续步骤完成",
    "v2.2.0 已公开且不改写，将在 v2.2.1 发布后标记为被补丁版取代"
  ],
  "validation": [
    "GitHub 后端与前端 Gate 均成功，唯一首错为 subscriptions-semantic-light-mobile-linux.png 的旧 UI 基线 2% 差异",
    "人工核对 CI expected/actual/diff，actual 为预期的新 capability catalog 订阅布局",
    "隔离 linux/amd64 + Google Chrome 151 重生成 light/dark 两张基线并通过 1/1；本机三视口复验 3/3 通过"
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-03",
  "result": "修复 ActorOps Route Canary 的跨 Discovery Run 断层：历史成功证据、未试 Revision、真实启动次数与费用预算统一按 Route 复用，candidate_shortfall 可继续生成最小补验计划。",
  "status": "partial",
  "task_id": "2026-08-03-fix-actorops-route-canary-history-reuse",
  "unresolved": [
    "v2.2.2 Git 推送、Tag、Release Gate 与 VPS 部署仍待本任务后续步骤完成",
    "部署不自动运行新的 AI Discovery、付费 Canary 或 Route 激活"
  ],
  "validation": [
    "补位 Run 自身 0 候选时仍读取旧 Run 的 1 路成功和不同发布者未试候选，并只生成 1 项 $0.02 补验计划",
    "次数与 $0.10 Route 认证预算跨 Run 累计，已真实尝试 Revision 不会重复进入计划",
    "ActorOps 后端 29 项、前端 22 项与 Changelog/ActorOps 定向 27 项通过",
    "python scripts/test_gate.py run --mode full: 23/23 passed"
  ]
}
```

```json
{
  "control_topics": [],
  "recorded_on": "2026-08-03",
  "result": "发布 v2.2.2 并以本地预构建的 revision-locked linux/amd64 镜像完成 VPS 切换；生产 YouTube 补位 Run 现可跨 Discovery Run 复用历史候选并恢复最小续接 Canary 计划。",
  "status": "completed",
  "task_id": "2026-08-03-publish-deploy-v2.2.2-canary-history-reuse",
  "unresolved": [],
  "validation": [
    "main 与 v2.2.2 Tag GitHub Test Gate 均成功，本地 full 23/23、release 25/25 通过",
    "VPS 上传源码与镜像 SHA-256 一致，镜像为 amd64、version 2.2.2、revision aefcbae70d1df669e4b831fe38654594928edea8",
    "停机前及心跳安全窗后活跃 Job/Attempt/Validation/Batch 均为 0；0600 数据库与 .env 回滚备份 integrity ok、foreign keys 0",
    "API/Worker 使用精确 v2.2.2 镜像且 healthy、restart=0、worker_status=ready；RSSHub healthy，scheduler/staging 为 0，公网首页与 /feed 为 200",
    "生产最新 youtube/channel/items Run 虽自身候选为 0，现已返回 ready=true、历史成功 1 路、补验候选 1 项、授权上限 $0.02；未自动调用 AI、Actor 或付费 Canary"
  ]
}
```

```json
{
  "control_topics": [
    "interface"
  ],
  "recorded_on": "2026-08-03",
  "result": "修复 YouTube Actor Canary 的未知启动永久阻断与终态费用早结算：只读账户 Run 时间窗可证明未创建并安全解锁，已创建 Run 延迟复核真实费用，错误 Job 不再显示成功。",
  "status": "partial",
  "task_id": "2026-08-03-fix-youtube-apify-start-reconciliation",
  "unresolved": [
    "等待提交、Release Gate、本地 8080 切换、Git 发布与 VPS 部署",
    "全量前端 551 项在组合运行中有 1 个无关设置目录用例抖动，但该用例单独通过；ActorOps 22/22 通过"
  ],
  "validation": [
    "ActorOps/Apify 后端定向约 145 项通过，完整 Gate 后端及其余 21 组通过",
    "ActorOps 前端 22/22、通知设置 7/7 通过；全量前端串行 550/551，唯一无关 App 设置目录用例单独 1/1 通过",
    "未知启动恢复测试证明不发送第二次 Actor POST，只有账户时间窗权威为空才解除 Route/Key 阻断并结算 $0",
    "终态费用复核测试覆盖 0.00005 到 0.00505 的 Apify 最终值更新"
  ]
}
```

```json
{
  "control_topics": [
    "interface"
  ],
  "recorded_on": "2026-08-03",
  "result": "确认生产未知启动自愈失败源于 Apify Run 列表拒绝带 +00:00 的日期过滤；v2.2.5 改用 UTC Z 格式并固定 30 秒证明窗口，避免延迟对账混入无关 Run。",
  "status": "partial",
  "task_id": "2026-08-03-fix-youtube-apify-reconcile-date-format-v225",
  "unresolved": [
    "等待提交合并、Release Gate、Git Tag/Release、本地 amd64 镜像构建与 VPS 切换",
    "部署后需确认旧未知启动结算为 0 美元并解除 YouTube Route 与 Key 阻断"
  ],
  "validation": [
    "生产只读诊断返回 400 invalid-value，明确 startedAfter 不是接口接受的 ISO UTC 格式",
    "修复格式后的生产只读查询返回 authoritative_empty=true，未启动 Actor 且未产生费用",
    "Apify pool/key 定向 22 项通过，完整 Test Gate 23/23 通过"
  ]
}
```

```json
{
  "control_topics": [],
  "recorded_on": "2026-08-03",
  "result": "发布并部署 v2.2.5，修复 Apify 未知启动对账日期格式；生产旧未知启动以 0 美元安全终结，唯一补验成功后自动激活 YouTube 两路不同发布者 Actor 主备。",
  "status": "completed",
  "task_id": "2026-08-03-publish-deploy-v2.2.5-youtube-actor-ready",
  "unresolved": [],
  "validation": [
    "定向 Apify pool/key 22 项、完整 Gate 23/23、Release Gate 25/25 通过；GitHub main 与 v2.2.5 Tag Test Gate 均成功",
    "本地 8080 运行精确 f46e6a2497e0，API/Worker healthy、worker_status=ready、前端资产已更新；scheduler 未启动",
    "VPS 使用本地预构建 amd64 镜像 docker load 与 --no-build 切换；0600 数据库和 .env 备份完成，integrity ok、foreign keys 0",
    "生产未知启动变为 start_rejected、实际费用 0 且 Key Pool 解锁；补验只启动一次，实际费用 0.00145 美元并终结",
    "youtube/channel/items generation 4 为 ready，Primary/Backup 1 是两个不同 Actor 和两个发布者，Backup 2 留空；活动任务 0、API/Worker/RSSHub healthy、日志无 HTTPStatusError 或 Traceback"
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
  "recorded_on": "2026-08-04",
  "result": "将完整原生 Settings Workspace 合入本地 main，并准备 v2.2.6 发布版本；保留 v2.2.5 ActorOps 对账安全修复和现有生产运行边界。",
  "status": "partial",
  "task_id": "2026-08-04-integrate-settings-workspace-v226",
  "unresolved": [
    "等待 full/release Test Gate、GitHub Tag/Release 与 VPS 安全切换。"
  ],
  "validation": [
    "合并冲突仅限控制文档和产品手册，已保留双方语义并将 Settings 决策编号顺延至 D115–D119。",
    "集成后前端 typecheck、UI contract、lint（0 error）与相关 Vitest 117 项通过。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-05",
  "result": "设置工作区侧栏规格与主应用侧栏统一：宽度 260px→232px（token），导航内边距/分组标签字号/图标尺寸/条目间距对齐 HeroWorkbenchShell 展开态，移动端抽屉 320px→260px，外观主题预览侧栏占比 28%→20%。",
  "status": "partial",
  "task_id": "2026-08-05-unify-settings-sidebar-specs",
  "unresolved": [
    "等待 full Test Gate 与合并验证（e2e 断言已同步为 232px）。"
  ],
  "validation": [
    "前端 typecheck、check:ui 通过；SettingsLayout/SettingsAppearance/HeroChangelog/HeroManual 4 个 Vitest 文件 11 项通过。",
    "./scripts/up-latest.sh 重建完成，API/Worker healthy，线上 CSS 确认 --inteliscope-width-settings-sidebar:232px。",
    "changelog 新增 v2.2.8 条目，manual 工作区设置描述同步，满足 check_product_docs 门禁。"
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-05",
  "result": "触底文案支持绑定任意全局 AI Key（新配置 ai_key_env，空值回退全局），/settings/ai 新增生成用 Key 下拉；Feed 顶部搜索栏背景 95%→70% 半透明并保留 backdrop-blur，明暗主题自适应。",
  "status": "partial",
  "task_id": "2026-08-05-feed-end-ai-key-binding-and-search-translucency",
  "unresolved": [
    "等待 full Test Gate 与合并验证。"
  ],
  "validation": [
    "后端 pytest：test_feed_end_messages 17、test_config_server + test_api_permissions_matrix 85、test_api_service 92 全部通过，含新增绑定/回退用例。",
    "前端 typecheck 与 39 项相关 Vitest 通过；API_CONTRACT 第 10 条、DECISION_LOG D120、changelog v2.2.9、manual 已同步。",
    "./scripts/up-latest.sh 重建完成，API/Worker healthy，线上 SettingsAIPage chunk 确认包含 ai_key_env 与默认选项。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-05",
  "result": "Feed 顶栏透明穿透最终形态：悬浮 absolute 条 + 内层 data-view-bar 毛玻璃（bg-background/70 + backdrop-blur），quiet-scroll-region overflow-y-scroll 对齐滚动条 gutter 消除 5px 偏差；筛选行 RemovableTag 新增 transparent 变体，清除全部改为 28px 紧凑 meta 按钮；设置概览卡片去箭头、徽标固定右上角、去已迁移标记，帮助与版本整行可点跳转。",
  "status": "partial",
  "task_id": "2026-08-05-feed-glass-bar-and-overview-cards",
  "unresolved": [
    "等待 full Test Gate 与合并验证。"
  ],
  "validation": [
    "workbench-live 106 项、design-system + settings + changelog/manual 相关 Vitest 全过，typecheck 与 check:ui 通过。",
    "三次 ./scripts/up-latest.sh 重建均 healthy；线上 chunk 确认悬浮条、gutter 对齐、透明标签与新卡片结构。",
    "changelog 新增 v2.2.10，manual 同步，产品文档门禁满足。"
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
  "recorded_on": "2026-08-05",
  "result": "闭环修复 Kimi K3 分支：触底文案独立 AI Key 现在进入 SecretStore 使用关系并阻止误删；Feed 悬浮工具栏按真实高度动态避让内容，筛选换行、移动搜索、提示、加载和空态均不会遮挡首项，阅读锚点按有效可视边界保持稳定。",
  "status": "completed",
  "task_id": "2026-08-05-workbuddy-stability-closure",
  "unresolved": [],
  "validation": [
    "后端引用/删除/同 Key/空值回退定向 pytest 105 项通过；前端 App 与 VirtualFeed 定向 Vitest 138 项通过。",
    "npm run typecheck、npm run check:ui 与 production-workbench desktop E2E 31 项通过。",
    "Full Test Gate：23/23 命令通过（245.628 秒）；git diff --check 通过。"
  ]
}
```

```json
{
  "control_topics": [
    "observability"
  ],
  "recorded_on": "2026-08-05",
  "result": "按 codex/workbuddy 工作树完成本地 8080 切换，仅重建 horizon-api 与 horizon-worker；未启动 scheduler。",
  "status": "completed",
  "task_id": "2026-08-05-start-workbuddy-local-containers",
  "unresolved": [],
  "validation": [
    "API 和 Worker 运行 revision 4a66181fd303-dirty，两个容器均为 healthy。",
    "/api/health/ready 返回 worker_status=ready；已加载前端资源 index-CIdTQQ7Q.js，包含本次 Feed 工具栏变更标记。"
  ]
}
```
```json
{
  "control_topics": [
    "interface",
    "observability"
  ],
  "recorded_on": "2026-08-05",
  "result": "AI Key 现在可独立保存并编辑 Base URL；全局 AI 和触底文案只允许引用相同 Provider 的已保存 Key，生成优先使用绑定 Key 的连接地址，旧的跨 Provider 绑定安全回退全局 Key。为本地升级增加带 0600 备份、Worker/运行中作业保护和 SQLite 完整性检查的离线迁移脚本。",
  "status": "completed",
  "task_id": "2026-08-05-ai-key-connection-profile",
  "unresolved": [],
  "validation": [
    "后端 30 项定向 pytest（含迁移、触底生成和 Secret API）通过；前端 typecheck 与 UI contract 通过。",
    "Full Test Gate 通过；git diff --check 通过。"
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
  "recorded_on": "2026-08-05",
  "result": "移除工作区 AI 的全局 Base URL 配置概念；每个 AI Key 独立保存连接地址，空地址使用 Provider 默认端点，并在工作区分析、触底文案和 Actor Discovery 中一致生效。",
  "status": "completed",
  "task_id": "2026-08-05-ai-key-independent-connection-url",
  "unresolved": [],
  "validation": [
    "Secret API、触底文案、Actor Discovery 与配置定向 pytest 154 项通过。",
    "前端 typecheck、UI contract 与设置/更新日志定向 Vitest 111 项通过。",
    "Full Test Gate 23/23 通过；git diff --check 通过。"
  ]
}
```

```json
{
  "control_topics": [
    "observability"
  ],
  "recorded_on": "2026-08-05",
  "result": "将 AI Key 独立连接地址与 Feed 稳健修复合入并推送 main，发布 GitHub v2.2.10，并用本地预构建 linux/amd64 镜像完成 VPS 从 v2.2.7 到 v2.2.10 的备份、迁移和 API/Worker 切换；scheduler 未启动。",
  "status": "completed",
  "task_id": "2026-08-05-release-v2.2.10-deploy",
  "unresolved": [],
  "validation": [
    "本地 Release Gate 25/25、GitHub main Test Gate 与 v2.2.10 Tag Test Gate（含 release smoke）通过；GitHub Release 已发布。",
    "本地镜像 inteliscope-service:v2.2.10-92637c48e2b6 为 linux/amd64，revision 标签精确；上传归档 SHA-256 为 39083b1e7d81fadae9a3f6b1c82c793049ce2e78094e0a09f259b31d62053ffd。",
    "生产迁移备份位于 /opt/inteliscope/backups/v2.2.10-92637c48e2b6-20260805T115838Z，数据库与环境备份均为 0600，迁移前备份和迁移后数据库 integrity ok、foreign keys 0。",
    "首次切换因 Docker health 尚在 starting 而按预案回滚 v2.2.7；旧服务恢复 ready 后重试成功，无活动作业或数据回退。最终 API/Worker healthy、restarts 0、worker_status=ready，公网根页和设置页 200、受保护接口 401、前端独立 Key URL 标记存在、严重级别错误日志 0。"
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "observability",
    "ui"
  ],
  "recorded_on": "2026-08-06",
  "result": "YouTube 频道头像改为按已验证 UC Channel ID 从固定公开频道页有界解析并缓存为本地受保护媒体；工作日志 schema‑3 基线已通过事务化 topic 归一、重复恢复与归档轮转修复。",
  "status": "completed",
  "task_id": "2026-08-06-fix-youtube-avatar-and-repair-worklog",
  "unresolved": [],
  "validation": [
    "YouTube/RSS/source-avatar 定向 pytest 69 项通过。",
    "前端 Changelog 定向 Vitest、typecheck 与 UI contract 通过。",
    "Full Test Gate 23/23 命令通过；worklogctl validate 返回 VALID。"
  ]
}
```

```json
{
  "control_topics": [
    "observability"
  ],
  "recorded_on": "2026-08-06",
  "result": "从 codex/diagnose-youtube-avatar-20260806 工作树完成本地 8080 切换；只重建 horizon-api 与 horizon-worker，未启动 scheduler。",
  "status": "completed",
  "task_id": "2026-08-06-start-youtube-avatar-local-containers",
  "unresolved": [],
  "validation": [
    "API 与 Worker 均 healthy，readiness 报告 worker_status=ready。",
    "两个服务均运行 revision de82a29d55cc，前端资源 index-BwptAGhG.js 已由 8080 提供。"
  ]
}
```
