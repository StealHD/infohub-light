# WORKLOG

<!-- init-pro:compact-worklog schema=1 -->

Entries are maintained by `worklogctl.py`; read-only and no-op tasks are not logged.

```json
{
  "control_topics": ["ui"],
  "recorded_on": "2026-08-06",
  "result": "将已验证的 AI Key 主导绑定、AI 设置简约化与 Apify Key 卡片重排快进合并到本地 main。",
  "status": "completed",
  "task_id": "2026-08-06-merge-key-driven-ai-bindings-to-main",
  "unresolved": [],
  "validation": [
    "main worktree 完整 Test Gate：23/23 命令通过。"
  ]
}
```

```json
{
  "control_topics": ["decisions", "ui"],
  "recorded_on": "2026-08-06",
  "result": "收紧 Apify Key 卡片的视觉秩序：成员状态与安全排空固定在 Header 右侧，额度改为无底色单行指标，Footer 仅保留检查时间和一致的移动、轮换、删除操作。",
  "status": "completed",
  "task_id": "2026-08-06-apify-key-card-alignment",
  "unresolved": [],
  "validation": [
    "定向 Vitest 106 项、TypeScript、ESLint 与 UI contract 检查通过。",
    "python3 scripts/test_gate.py run --mode full：23/23 命令通过。"
  ]
}
```

```json
{
  "control_topics": ["decisions", "ui"],
  "recorded_on": "2026-08-06",
  "result": "将 Apify Key 池重排为独立 HeroUI 卡片：身份与状态、三项额度指标、最近检查和生命周期操作直接分区呈现，移除详情 Disclosure。",
  "status": "completed",
  "task_id": "2026-08-06-apify-key-hero-card-layout",
  "unresolved": [],
  "validation": [
    "定向 Vitest 106 项、TypeScript、ESLint 与 UI contract 检查通过。",
    "python3 scripts/test_gate.py run --mode full：23/23 命令通过。"
  ]
}
```

```json
{
  "control_topics": ["decisions", "ui"],
  "recorded_on": "2026-08-06",
  "result": "将密钥页 Apify Key 池收敛为异常优先的紧凑摘要：正常行仅保留状态、额度和操作，详情按需显示检查、异常与生命周期管理。",
  "status": "completed",
  "task_id": "2026-08-06-apify-key-pool-simplification",
  "unresolved": [],
  "validation": [
    "定向 Vitest 111 项、TypeScript、ESLint 与 UI contract 检查通过。",
    "python3 scripts/test_gate.py run --mode full：23/23 命令通过。"
  ]
}
```

```json
{
  "control_topics": ["decisions", "ui"],
  "recorded_on": "2026-08-06",
  "result": "将 AI 设置页收敛为 Key 搜索主导的紧凑 HeroUI 表单：Provider/地址状态成为 Key 次级元数据，触底文案状态改为整块下拉并一次展示三个场景列表。",
  "status": "completed",
  "task_id": "2026-08-06-ai-settings-heroui-simplification",
  "unresolved": [],
  "validation": [
    "定向 Vitest 111 项、TypeScript、ESLint 与 UI contract 检查通过。",
    "python3 scripts/test_gate.py run --mode full：23/23 命令通过。",
    "当前 Worktree ./scripts/up-latest.sh 完成 8080 切换；API/Worker healthy，ready 返回 worker_status=ready，桌面与 390px 浏览器实测通过。"
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
  "recorded_on": "2026-08-06",
  "result": "将工作区分析与触底文案改为 AI Key 主导的平级绑定：Key 决定 Provider/Base URL，两个场景各自保存模型，触底文案不再跟随、筛选或回退工作区 AI。",
  "status": "completed",
  "task_id": "2026-08-06-key-driven-ai-bindings",
  "unresolved": [],
  "validation": [
    "定向 pytest 110 项通过",
    "前端 Vitest 106 项、TypeScript 与 UI contract 检查通过",
    "python scripts/test_gate.py run --mode full 通过",
    "未调用真实 AI、未重建 8080、未部署"
  ]
}
```

```json
{
  "control_topics": [
    "operations"
  ],
  "recorded_on": "2026-08-07",
  "result": "从 subscriptions-layout-cleanup 任务分支重建本地 8080 运行时，切换已提交的订阅页布局镜像。",
  "status": "completed",
  "task_id": "2026-08-07-start-subscription-layout-container",
  "unresolved": [],
  "validation": [
    "horizon-api 与 horizon-worker 均 healthy，readiness 返回 API 和 Worker ready。",
    "127.0.0.1:8080 已提供 revision ce53c72cfe5b 的前端资源 index-BNbh5sci.js；未启动 scheduler。"
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

```json
{
  "control_topics": [
    "interface"
  ],
  "recorded_on": "2026-08-06",
  "result": "修复 YouTube 官方频道头像在 yt3.googleusercontent.com 被媒体缓存安全 DNS 策略拒绝的问题；仅将 googleusercontent.com 纳入受信任媒体 CDN 后缀，并为已订阅频道准备单源免费回填。",
  "status": "completed",
  "task_id": "2026-08-06-fix-youtube-avatar-cdn-policy",
  "unresolved": [],
  "validation": [
    "已用实际频道 UCMUnInmOkrWN4gof9KlhNmQ 复现：频道页可解析 og:image，但 Worker 记录 avatar_cache=failed。",
    "安全网络策略模拟 198.18.0.0/15 合成 DNS 时允许 yt3.googleusercontent.com；常规非白名单策略未放宽。",
    "全量 Test Gate 因本机 Python 3.14 缺少 pytest 在启动阶段失败，非测试断言失败。"
  ]
}
```

```json
{
  "control_topics": [
    "interface"
  ],
  "recorded_on": "2026-08-06",
  "result": "在完成 YouTube 官方 CDN 安全策略修复并重建本地服务后，仅对已订阅频道 src_f89d4d3d9960417da412aa218e51bdbb 执行免费单源头像回填。",
  "status": "completed",
  "task_id": "2026-08-06-backfill-youtube-avatar-source",
  "unresolved": [],
  "validation": [
    "回填结果 stored；媒体资产为 image/jpeg、110250 bytes、status=ready。",
    "未运行 Feed 抓取、AI、通知、计划任务或付费 Actor。",
    "API 与 Worker 在 revision 5c71e3ef1991 上 healthy，Worker readiness=ready。"
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-06",
  "result": "将 YouTube 频道头像解析、官方 CDN 安全缓存与单源回填修复合并到本地 main；保留 main 的 AI Key 更新日志和本分支的 YouTube 头像更新日志。",
  "status": "completed",
  "task_id": "2026-08-06-merge-youtube-avatar-into-main",
  "unresolved": [],
  "validation": [
    "合并冲突已解析，更新日志时间线保留两条 2026-08-06 记录并同步测试索引。",
    "WORKLOG 已安全归档轮转，控制工具在合并结果上校验通过。",
    "复用 key-driven-ai-bindings 虚拟环境重跑完整 Test Gate：23/23 命令通过（238.387 秒）。"
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-06",
  "result": "从本地 main 重建共享 8080 运行时，切换 YouTube 头像合并后的服务镜像。",
  "status": "completed",
  "task_id": "2026-08-06-rebuild-local-main-after-youtube-merge",
  "unresolved": [],
  "validation": [
    "首次切换 revision b343d01647ce：horizon-api 与 horizon-worker 均 healthy，readiness 返回 API 和 Worker ready。",
    "服务前端资源 index-oj-oGb1j.js 已验证由本地服务提供；未启动 scheduler。"
  ]
}
```

```json
{
  "control_topics": [
    "capabilities"
  ],
  "recorded_on": "2026-08-06",
  "result": "已将本地 main 推送至 GitHub，并完成 VPS 预检及修订 2c86ba1473c8 的本地 linux/amd64 镜像构建；因发布级浏览器门禁失败，未上传镜像、未切换生产。",
  "status": "blocked",
  "task_id": "2026-08-06-youtube-avatar-production-release-gate",
  "unresolved": [
    "release Playwright 141 项中 10 条管理页验收失败，需修复或取得明确豁免后再部署。"
  ],
  "validation": [
    "VPS 预检：数据库 integrity/foreign key 通过、迁移标记至 v19、无活跃作业、API/Worker healthy、scheduler stopped。",
    "release Test Gate：23/24 命令通过；release_playwright 失败（83 passed、10 failed、48 skipped）。",
    "本地镜像 inteliscope-service:v2.2.10-2c86ba1473c8 已验证为 amd64，OCI revision=2c86ba1473c8。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-06",
  "result": "将 release Playwright 的管理页断言同步到当前 AI Key 主导设置与 Apify Key 卡片语义，清除原 10 条过期验收失败。",
  "status": "completed",
  "task_id": "2026-08-06-fix-release-playwright-admin-baseline",
  "unresolved": [],
  "validation": [
    "定向 Playwright：12/12 项目组合通过，无失败附件。",
    "release Test Gate：25/25 命令通过（484.911 秒）；Playwright 93 passed、48 skipped，隔离 Docker API smoke 通过。"
  ]
}
```

```json
{
  "control_topics": [
    "capabilities",
    "ui"
  ],
  "recorded_on": "2026-08-06",
  "result": "在 release 门禁修复后将 v2.2.10-421464fc3f06 本地 amd64 镜像加载并切换到 VPS，随后仅对老高與小茉 YouTube 频道执行免费单源头像回填。",
  "status": "completed",
  "task_id": "2026-08-06-deploy-youtube-avatar-release",
  "unresolved": [],
  "validation": [
    "生产 API/Worker 均运行 revision 421464fc3f06 且 healthy，readiness 返回 worker_status=ready；scheduler stopped。",
    "生产数据库 integrity/foreign key 通过、迁移标记至 v19；release 前后无活跃作业。",
    "目标频道头像回填返回 stored；ready 文件为 image/jpeg、110250 bytes、官方 yt3.googleusercontent.com，未创建 Feed、AI、通知或付费任务。"
  ]
}
```

```json
{
  "control_topics": [
    "decisions",
    "ui"
  ],
  "recorded_on": "2026-08-07",
  "result": "将订阅页收紧为四类固定视图：搜索移入页签工具栏，来源统计移至右上健康状态下方，来源库继续按真实频道浏览。",
  "status": "completed",
  "task_id": "2026-08-07-subscription-layout-cleanup",
  "unresolved": [],
  "validation": [
    "定向 Vitest、三视口订阅 Playwright 与 light/dark 视觉基线通过。",
    "完整 Test Gate：23/23 命令通过（247.228 秒）；git diff --check 通过。"
  ]
}
```

```json
{
  "control_topics": [
    "decisions",
    "ui"
  ],
  "recorded_on": "2026-08-07",
  "result": "取消“我的订阅”的固定视图，搜索、筛选和新增来源收为滚动固定的半透明工具栏；来源库继续按真实频道浏览。",
  "status": "completed",
  "task_id": "2026-08-07-subscription-toolbar-without-views",
  "unresolved": [
    "按用户约定，本分支未更新或运行 Playwright；最终集成分支再统一处理一次浏览器断言与视觉快照。"
  ],
  "validation": [
    "定向 Vitest 152 项、TypeScript、UI 合同检查、lint 和构建通过。",
    "完整 Test Gate：23/23 命令通过（233.256 秒）；git diff --check 通过。"
  ]
}
```
