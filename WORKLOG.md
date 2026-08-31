# WORKLOG

<!-- init-pro:compact-worklog schema=1 -->

Entries are maintained by `worklogctl.py`; read-only and no-op tasks are not logged.


```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-29",
  "result": "修复平台托管 X、Instagram、YouTube 来源在保存设置时因隐藏启用控件缺席而误提交 enabled=false；恢复本地 X 来源与 ActorOps Binding 并重建健康容器。",
  "status": "completed",
  "task_id": "2026-08-29-managed-source-hidden-enabled-fix",
  "unresolved": [],
  "validation": [
    "HeroSubscriptionDialogs Vitest 11/11 通过",
    "TypeScript、ESLint 与 snapshot impacted preflight 11/11 通过",
    "本地 X Source enabled、Binding ready；API、Worker 与前端 revision 健康"
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
  "recorded_on": "2026-08-29",
  "result": "修复 ActorOps Replacement 两轮 Dataset 适配耗尽后仍以 running/adaptation_pending 永久占用 Route 的状态机缺口；计划改为保留具体原因与费用事实后终态失败，Candidate 不记故障，历史卡住计划由 Worker 零新增 Run 收敛。",
  "status": "completed",
  "task_id": "2026-08-29-actorops-adaptation-terminal-release",
  "unresolved": [],
  "validation": [
    "Dataset 适配失败释放 Route 与成功单 Run 路径定向 Pytest 2/2 通过",
    "Replacement Drawer Vitest 9/9、TypeScript、ESLint 通过",
    "snapshot impacted preflight 15/15 通过；本地 API、Worker、前端 revision 健康"
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-29",
  "result": "ActorOps 路线管理已合并为持久化单 Drawer：搜索、自动推荐、主备槽位选择、免费预检、按钮授权实测、Dataset 适配和按钮应用连续完成；Route 卡持续投影阶段、来源进度与安全费用。",
  "status": "completed",
  "task_id": "2026-08-29-actorops-unified-operator-workflow",
  "unresolved": [],
  "validation": [
    "后端影响域完整重跑通过，SQLite ResourceWarning 根因修复并以 error 级警告验证",
    "前端 ESLint、TypeScript、UI/E2E 合同、95 文件 688 项 Vitest、生产构建和前后端代码尺寸门通过",
    "完整 preflight 前 6 道通过后由新增测试连接警告停止；按规则未第三次整门重跑，修复后原失败域及剩余检查均分别通过",
    "Docker/Worker 保持关闭；本地 API 18080 与 Vite 15173 healthy，ActorOps schema 2 返回 3 条 Route 且均含 workflow 投影"
  ]
}
```

```json
{
  "control_topics": [],
  "recorded_on": "2026-08-30",
  "result": "校准 ActorOps 最终 Route 卡在 macOS 与 Linux 的三视口视觉基线，覆盖不可用状态、故障 Candidate、双备用槽与统一管理操作，解除 v2.6.0 main Gate 的旧快照阻断；未改产品运行逻辑。",
  "status": "completed",
  "task_id": "2026-08-30-actorops-route-card-release-baselines",
  "unresolved": [],
  "validation": [
    "GitHub main Gate 的 backend-full 与 frontend-full 通过，UI E2E 仅三张 ActorOps Linux 旧快照失败。",
    "人工核对 macOS 与 Linux actual 均为当前统一管理 Route 卡；失败视觉测试本地 3/3 通过。",
    "完整 ActorOps Playwright spec 本地 13 passed、2 skipped。"
  ]
}
```

```json
{
  "control_topics": [],
  "recorded_on": "2026-08-30",
  "result": "消除生产管理 E2E 在桌面侧栏展开动画期间强制滚动并误点击文档菜单的竞态；验收等待侧栏达到最终 232px 几何后再验证菜单。",
  "status": "completed",
  "task_id": "2026-08-30-release-sidebar-menu-gate-stability",
  "unresolved": [],
  "validation": [
    "GitHub main Gate trace 确认点击时侧栏仍由 72px 向 232px 过渡且 footer 被水平滚动。",
    "桌面账户与文档菜单 Playwright 场景并发重复 20 次，20/20 通过。"
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-30",
  "result": "将 ActorOps 头像证据从 Instagram 专用路径收敛为 proof 与 source 绑定的通用 sidecar，X 与其他可信来源可在正常获取及 acquisition cache 命中时静默更新当前头像；成功任务会刷新 Catalog 头像而不新增外部调用。",
  "status": "completed",
  "task_id": "2026-08-30-source-avatar-auto-refresh",
  "unresolved": [],
  "validation": [
    "ActorOps 直接传递与 acquisition cache 回放定向 Pytest 8 项通过；头像 checksum、24 小时复核、失败保旧与事务清理相关 Pytest 19 项通过。",
    "任务终态、头像 immutable URL 与 changelog 定向 Vitest 26 项通过，TypeScript 类型检查通过。",
    "snapshot impacted preflight 16/16 通过，覆盖完整前后端、控制检查、代码尺寸与隔离 E2E，SQLite 连接警告为 0。"
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-30",
  "result": "补齐 X Actor 实际 user_profile_image_url 头像别名，复用已成功且 proof/source/身份校验通过的 Dataset 零启动回放并替换 immutable 头像资产；同时移除 15173 指向临时库的旧本地运行时，统一到修复分支与正式本地数据。",
  "status": "completed",
  "task_id": "2026-08-30-x-avatar-runtime-alias-repair",
  "unresolved": [],
  "validation": [
    "ActorOps、头像 publication 与 acquisition 定向 Pytest 72 项通过；头像刷新、Catalog 失效与 ActorOps 页面定向 Vitest 35 项通过",
    "已验证头像映射 /user_profile_image_url、asset ID 与 checksum 均变化，新文件落盘且只保留一个 ready 资产",
    "snapshot impacted preflight 16/16 通过；15173 代理 18081，API 与原生 Worker ready，15174/18080 关闭且未启动容器"
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-30",
  "result": "修复 tibo/thsottiaux 回退头像未更新的本地验证链路：用最新成功 Attempt 的冻结 proof 与账号身份零启动回放当前 Dataset，生成新 immutable 头像资产；补充 A→B→A 回退缓存用例，并将 15173/18080/Worker 原生运行时切到头像修复工作树。",
  "status": "completed",
  "task_id": "2026-08-30-x-avatar-reversion-runtime-fix",
  "unresolved": [],
  "validation": [
    "最新头像从 med_55f8ede…/b5d8… 更新为 med_5bdf262…/35e3…，文件落盘且 Feed 8 个 thsottiaux 条目均请求新 asset ID",
    "X 实际字段、publication 与 A→B→A 回退相关 Pytest 44 项通过；冻结文件增长问题已移至新聚焦测试文件",
    "精确基线 snapshot impacted preflight 16/16 通过；15173/18080 与受限原生 Worker 运行修复分支，无容器和新增 Actor Run"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-29",
  "result": "按订阅页 command bar 统一 ActorOps 路由/日志切换，移除顶部说明，将路线模式并入标题行，并把底部事实与操作按左右/移动端上下布局重新对齐。",
  "status": "completed",
  "task_id": "2026-08-29-actorops-subscription-ui-alignment",
  "unresolved": [],
  "validation": [
    "ActorOps 与页面定向 Vitest 14 项、TypeScript 和 ESLint 通过。",
    "ActorOps Playwright 三视口规格 13 项通过、2 项按范围跳过，并更新三端视觉基线。",
    "snapshot impacted preflight 12/12 命令通过；本地浏览器确认无横向溢出。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-30",
  "result": "修复生产 Feed 社交卡名称字段误显示完整帖子 URL：卡片与 Agent 上下文过滤 URL 形态的来源/作者名，保留可读账号名，并在名称均无效时从可信社交链接提取账号 handle 兜底。",
  "status": "completed",
  "task_id": "2026-08-30-feed-social-source-url-label",
  "unresolved": [
    "尚未发布到生产 VPS；本任务仅完成本地代码修复与验证。"
  ],
  "validation": [
    "Workbench 定向 Vitest 58 项、TypeScript、ESLint 与 UI 合约检查通过。",
    "Playwright 本地 Vite 桌面回归通过，证明 Feed 卡片和 Agent 上下文均不显示帖子 URL，并继续显示 X 与可读账号名。"
  ]
}
```

```json
{
  "control_topics": [
    "decisions",
    "interface",
    "phase",
    "ui"
  ],
  "recorded_on": "2026-08-30",
  "result": "修复 Instagram Probe 条数下限与已证明无启动失败记账；按 exact Schema 核验 YouTube Shorts/排序，并以 global 36 仅为业务验证成功候选开启非最后一路自动替换。",
  "status": "completed",
  "task_id": "2026-08-30-actorops-verified-auto-replacement",
  "unresolved": [
    "未启动 Worker、未发起新的付费 Probe、未部署 VPS；生产自动替换仍须走现有发布与有界付费授权门。"
  ],
  "validation": [
    "ActorOps Adapter/Discovery/Maintenance/Replacement/Readiness/global36 定向 Pytest 通过；前端变更日志 5 项测试与 TypeScript 通过。",
    "免费 Catalog GET 核验 YouTube exact Build，未启动 Actor；确认 Shorts-only、长短二选一与 all+newest 三类能力差异。",
    "本地 global36 显式迁移创建 0600 backup，integrity/FK 通过，3 条 system_default Route 开启 proof gate；18080 API 与 15173 前端代理健康。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-30",
  "result": "来源抓取在 Worker 心跳过期或状态未知时改为提示“获取未开始”，明确任务未创建且未产生费用，不再误报来源获取失败。",
  "status": "completed",
  "task_id": "2026-08-30-source-fetch-not-started-copy",
  "unresolved": [
    "本地预览按合同未启动 Worker；需要真实手动抓取时仍须显式进入可能产生 Apify 费用的 Worker 执行边界。"
  ],
  "validation": [
    "数据库定向查询确认 @thsottiaux 最近四次抓取成功，本次没有创建 source_fetch Job，阻断原因是 Worker 心跳过期。",
    "App 定向 Vitest、更新日志 5 项测试与 TypeScript 通过。",
    "本地订阅页通过 Vite/API 正常加载，显示 Worker 不可用且 @thsottiaux 来源健康，浏览器无控制台错误。"
  ]
}
```

```json
{
  "control_topics": [
    "phase"
  ],
  "recorded_on": "2026-08-30",
  "result": "将本地最新 main 的 ActorOps 稳定性、来源头像、Feed 社交名称修复整理为 v2.6.1 发布版本；版本身份与既有 v2.6.0 标签分离，global 36 保持显式停机迁移。",
  "status": "completed",
  "task_id": "2026-08-30-release-v2-6-1",
  "unresolved": [],
  "validation": [
    "ActorOps、迁移、头像、运行脚本定向 Pytest 164 项通过。",
    "Workbench、ActorOps、Settings、变更日志与 App 定向 Vitest 172 项通过。"
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-30",
  "result": "修复 Apify 以 403 build-not-found 拒绝已删除固定 Build 时的错误分类：第一次失败即确认为 Build 不可用并触发候选发现、有界实测与自动替换；完成本地 ActorOps 根因复现、候选换版验证和 Worker 热加载。",
  "status": "completed",
  "task_id": "2026-08-30-apify-build-not-found-auto-upgrade",
  "unresolved": [
    "X 当前主 Actor 可正常获取，但两个旧备用 Build 已删除；同 Actor 新 Build 在第二来源返回 noResults/demo，已被正确隔离，后续候选探测因当日 5 次安全上限延至下一 UTC 日。",
    "YouTube 仍通过免费原生 RSS 降级稳定获取；现有 Actor 候选为 stale_regression 或输出合同不兼容，自动修复将在探测额度恢复后继续。"
  ],
  "validation": [
    "授权最小复现确认旧 Build 0.0.980 返回 403 build-not-found 且未创建远端 Run；现行 Build 0.0.982 可启动并返回有效 X 数据。",
    "Apify 错误分类、远端 no-start 证据与硬故障修复定向 Pytest 通过；完整影响 preflight 16/16 通过。",
    "本地 8080 API readiness 返回 database/worker/logging 全部 ready，5173 前端可用；ActorOps 页面显示 Instagram 健康、X 降级可用、YouTube 原生降级。"
  ]
}
```

```json
{
  "control_topics": [
    "phase"
  ],
  "recorded_on": "2026-08-30",
  "result": "将本地 main 的 Apify 已删除 Build 精确错误分类整理为 v2.6.2 发布版本，并同步修正项目锁文件中的版本身份。",
  "status": "completed",
  "task_id": "2026-08-30-release-v2-6-2",
  "unresolved": [],
  "validation": [
    "Apify Client、ActorOps Maintenance 与 Repair 定向 Pytest 41 项通过。",
    "依赖与构建配置触发的完整 impacted preflight 16/16 通过，后端/前端全域检查、控制校验与构建均成功。"
  ]
}
```

```json
{
  "control_topics": [
    "interface"
  ],
  "recorded_on": "2026-08-30",
  "result": "修复 Actor 明确 no-results 被误判为账号身份不匹配的问题；无内容控制行现在安全完成为空结果，demo/占位和其他普通语义异常保留具体错误并按证据阈值恢复，不再统一升级为一次即确认的合同故障。",
  "status": "completed",
  "task_id": "2026-08-30-actor-no-results-health-recovery",
  "unresolved": [
    "本轮按用户要求只完成本地修复；VPS 仍运行 v2.6.2，需后续发布新版本并对既有 X 故障证据执行受控恢复。"
  ],
  "validation": [
    "noResults/no_results、身份不匹配、placeholder 与合同错误分类定向回归通过。",
    "Actor Manifest、候选 Runtime、X 回复过滤与输出错误分类受影响测试全部通过。",
    "impacted preflight 14/14 通过，后端、Worker、前端、控制校验和代码尺寸检查均成功。"
  ]
}
```

```json
{
  "control_topics": [
    "phase"
  ],
  "recorded_on": "2026-08-30",
  "result": "将本地 main 的 Actor no-results 合法空结果与可恢复语义故障修复整理为 v2.6.3 发布版本，并同步项目版本和锁文件身份。",
  "status": "completed",
  "task_id": "2026-08-30-release-v2-6-3",
  "unresolved": [],
  "validation": [
    "运行与健康脚本定向 Pytest 38 项通过，uv lock 校验成功。",
    "依赖与构建配置触发的完整 impacted preflight 16/16 通过，后端、前端、控制校验与构建均成功。"
  ]
}
```

```json
{
  "control_topics": [
    "interface"
  ],
  "recorded_on": "2026-08-31",
  "result": "ActorOps v2 Discovery 现在免费读取当前 Apify 账户 tier，并从 exact Build 公开 README 派生有界适配级别；禁止 FREE API、仅 Demo、限制月运行次数或禁止周期监控的 Actor 会排在兼容候选之后，再按原商城质量排序。",
  "status": "completed",
  "task_id": "2026-08-31-actor-account-fit-ranking",
  "unresolved": [
    "本轮只完成本地分支实现，未部署 VPS，也未自动改写生产现有主备顺序；既有 active Actor 需在后续受控发布和主备操作中处理。"
  ],
  "validation": [
    "Apify Catalog、Discovery、Discovery AI 与 Worker 定向 Pytest 67 项通过；更新日志 Vitest 5 项通过。",
    "impacted preflight 14/14 通过，后端、前端、控制文件、代码尺寸、语法与构建检查全部成功。",
    "实现与验证未启动新的 Apify Actor Run，README 原文、账户对象、目标和密钥均未持久化或进入 AI。"
  ]
}
```

```json
{
  "control_topics": [
    "phase"
  ],
  "recorded_on": "2026-08-31",
  "result": "将 ActorOps 当前账户套餐适配排序合入本地 main，并整理为 v2.6.4 发布版本；FREE API、Demo、月运行和监控受限 Actor 会在兼容候选之后参与既有质量排序。",
  "status": "completed",
  "task_id": "2026-08-31-release-v2-6-4",
  "unresolved": [],
  "validation": [
    "Apify Catalog、Discovery、Discovery AI 与 Worker 定向 Pytest 67 项通过，更新日志 Vitest 5 项通过。",
    "功能分支 impacted preflight 14/14 通过；版本与 uv lock 已同步为 2.6.4，未增加数据库迁移或付费 Actor 调用。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-31",
  "result": "为 X、Instagram 与 YouTube 既有来源补回显式启用控制；订阅仍开启但来源/Binding 已停用时，可由有来源管理权限的用户恢复 Binding 并以本地证据重新启用，且不创建 Job、Actor Attempt 或费用。",
  "status": "completed",
  "task_id": "2026-08-31-managed-source-explicit-recovery",
  "unresolved": [],
  "validation": [
    "ActorOps 来源生命周期 Pytest 6/6、来源表单 Vitest 12/12、锁定平台场景 1/1 通过；TypeScript 与相关 ESLint 通过",
    "snapshot impacted preflight 14/14 通过，前后端均命中且 SQLite 连接警告为 0",
    "本地生产构建、核心 API smoke 8/8、live/ready、API/Worker 双容器与 React 资源均健康；未调用真实来源、Actor、AI 或通知"
  ]
}
```
