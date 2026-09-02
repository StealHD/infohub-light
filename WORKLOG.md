# WORKLOG

<!-- init-pro:compact-worklog schema=1 -->

Entries are maintained by `worklogctl.py`; read-only and no-op tasks are not logged.


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

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-31",
  "result": "修复 YouTube 条目把底层 rss 显示为来源名的问题：既有 Feed/收藏/历史/详情按 source_id 投影当前频道名，ActorOps 后续获取写入规范来源名称与 catalog 类型，不迁移或改写旧内容。",
  "status": "completed",
  "task_id": "2026-08-31-youtube-feed-source-name",
  "unresolved": [],
  "validation": [
    "后端定向 Pytest 20 项、更新日志 Vitest 5 项通过；原失败头像 spec 单独复验通过。",
    "本地 service.db 只读备份中的真实异常行已从 rss 投影为老高與小茉 Mr & Mrs Gao。",
    "snapshot impacted preflight 重跑 14/14 通过，覆盖 Feed/Store/API、ActorOps、前端与控制检查，SQLite 连接警告为 0。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-31",
  "result": "社交卡片顶部不再显示与底部频道同名的来源标签；平台、关注账号、时间和底部频道分类保持可见，真实来源 handle 不受影响。",
  "status": "completed",
  "task_id": "2026-08-31-social-card-channel-label-dedup",
  "unresolved": [],
  "validation": [
    "Workbench 模型、卡片渲染与更新日志定向 Vitest 65 项通过。",
    "snapshot impacted preflight 12/12 通过，覆盖 frontend_full 与 control，SQLite 连接警告为 0。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-31",
  "result": "Feed 卡片将复制摘要与忽略从三点菜单改为右上角悬浮/聚焦直达操作，图标提供下方说明；带图卡片为操作区预留空间并隔离媒体命中区域，触屏继续常显，来源概览不展示这些逐条操作。",
  "status": "completed",
  "task_id": "2026-08-31-feed-card-hover-actions",
  "unresolved": [],
  "validation": [
    "VirtualFeed、来源概览、模型、更新日志等定向 Vitest 71 项通过；失败的 App 忽略/撤销用例更新后单独复验通过。",
    "真实已登录本地页面完成悬浮、命中区域和提示文本检查；Playwright 在 320、390、645、1024、1440px 五档全部通过。",
    "snapshot impacted preflight 12/12 通过，覆盖 frontend_full、control、694 个前端测试、类型、Lint、UI 契约与代码尺寸检查。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-31",
  "result": "移除 Feed 卡片右上角复制/忽略操作组的独立描边、背景、圆角、阴影和模糊面板，统一复用右下角无外框图标操作组的视觉处理，单个图标仍保留共享悬浮反馈和说明。",
  "status": "completed",
  "task_id": "2026-08-31-feed-card-action-visual-unity",
  "unresolved": [
    "代码保留在 codex/fix-youtube-source-label 工作区，等待用户明确授权提交。"
  ],
  "validation": [
    "VirtualFeed 与更新日志定向 Vitest 42 项通过；TypeScript、ESLint 和 UI 契约检查通过。",
    "已登录本地页面实测无外层面板且复制摘要 Tooltip 正常；320、390、645、1024、1440px Playwright 5/5 通过，并比较上下操作组计算样式一致。",
    "snapshot impacted preflight 12/12 通过，覆盖 frontend_full、control、全量前端测试、代码尺寸与控制文件检查。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-09-01",
  "result": "修复 Feed 文章展开/收起时按钮按压缩放与内容展开动画叠加造成的视觉抖动；时间流与专题速览共用的展开控件在点击期间保持固定几何尺寸，同时保留内容过渡和滚动锚点。",
  "status": "completed",
  "task_id": "2026-09-01-feed-expand-press-jitter",
  "unresolved": [
    "代码保留在 codex/fix-youtube-source-label 工作区，等待用户明确授权提交。"
  ],
  "validation": [
    "VirtualFeed、SourceOverviewFeed 与更新日志定向 Vitest 48/48 通过；TypeScript 与 UI 契约检查通过。",
    "专题速览真实指针 Playwright 1/1 通过，按下时 transform 为 none 且按钮宽高位移不超过 0.5px；已登录本地页面完成展开视觉复验。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-09-01",
  "result": "Feed 卡片复制摘要现在提供即时视觉反馈：成功后图标临时变为勾并在上方显示“已复制”，失败时保留复制图标并显示“复制失败”，2.8 秒后恢复空闲状态；屏幕阅读器状态继续保留。",
  "status": "completed",
  "task_id": "2026-09-01-feed-copy-feedback",
  "unresolved": [
    "代码保留在 codex/fix-youtube-source-label 工作区，等待用户明确授权提交。"
  ],
  "validation": [
    "VirtualFeed 与更新日志定向 Vitest 42/42 通过；TypeScript、ESLint、UI 契约与代码尺寸检查通过。",
    "已登录本地页面实测勾选、上方“已复制”和自动恢复；桌面 Playwright 2/2 通过，验证反馈位置、图标及 2.8 秒复位。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "decisions",
    "interface"
  ],
  "recorded_on": "2026-09-01",
  "result": "修复新用户订阅已有 workspace/public 来源后近 7 天 Feed 为空：可证明 title_origin=native 的旧稳定条目不再因缺 source_native_title 被跳过，没有安全用户供体时回退到同 workspace 中性来源缓存；托管来源准备启用时也先完成零网络目标订阅投影。",
  "status": "completed",
  "task_id": "2026-09-01-existing-source-new-subscriber-reuse",
  "unresolved": [
    "尚未部署或修改 VPS；修复保留在 codex/fix-youtube-source-label 工作区，等待用户确认后续合入与发布。"
  ],
  "validation": [
    "新增合成回归覆盖来源缓存无用户供体、托管来源暂时停用、旧条目缺 source_native_title 但原始标题可证明三条路径，定向 Pytest 7/7 通过。",
    "既有订阅复用、API、Feed Store 与 import boundary 回归 35 项通过；本地真实数据库只读聚合确认 235 条旧记录中 176 条具备可信 native title 证明。",
    "snapshot full preflight 16/16 通过，覆盖完整后端、前端、控制检查、代码尺寸和映射 E2E，SQLite 连接警告为 0。"
  ]
}
```

```json
{
  "control_topics": [
    "phase"
  ],
  "recorded_on": "2026-09-01",
  "result": "将 YouTube 来源名称、社交标签去重、卡片复制/忽略与展开反馈、以及新用户订阅已有来源的安全内容回填合入本地 main，并整理为 v2.6.6 正式发布版本。",
  "status": "completed",
  "task_id": "2026-09-01-release-v2-6-6",
  "unresolved": [],
  "validation": [
    "合并后的本地 main 为干净线性历史，功能修复 snapshot full preflight 16/16 通过。",
    "版本与 uv lock 同步为 2.6.6；版本准备 snapshot full preflight 16/16 通过，覆盖完整前后端、控制检查、代码尺寸与映射 E2E，SQLite 连接警告为 0。",
    "本次没有数据库 migration 文件或 schema delta，适用标准 revision-locked VPS 发布流程。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-09-01",
  "result": "修复 v2.6.6 首次 main UI Gate 暴露的卡片交互回归：带缩略图卡片的复制/忽略按钮改为位于图片左侧并恢复顶部对齐，不再增加卡片高度；悬停交互测试在提示检查后重新激活卡片再点击。",
  "status": "completed",
  "task_id": "2026-09-01-release-v2-6-6-ui-gate-fix",
  "unresolved": [],
  "validation": [
    "首次失败的 production-workbench 桌面 Playwright 7/7 通过，覆盖 320/390/645/1024/1440px 操作反馈及 1440x900 至少四张完整卡片。",
    "VirtualFeed 定向 Vitest 37/37、TypeScript、UI 契约通过；snapshot impacted preflight 12/12 通过，覆盖 frontend_full 与控制检查。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "decisions",
    "interface"
  ],
  "recorded_on": "2026-09-01",
  "result": "修复 public/workspace 来源只写入触发用户的问题：成功 source_fetch 现会在同一事务向全部有效非 Viewer 订阅者生成各自的 Feed 投影；中性缓存默认开启，新订阅优先缓存并安全回退稳定内容，最多 200 条。",
  "status": "completed",
  "task_id": "2026-09-01-public-source-content-sharing",
  "unresolved": [
    "未合并、未推送或部署 VPS；发布后需对已有 X 来源执行一次正常成功抓取以补齐现有缺失的近期条目。"
  ],
  "validation": [
    "公共来源 fan-out、private/Viewer 隔离、缓存优先回填、catalog runner 接线与系统默认值定向 Pytest 22 项通过。",
    "完整 impacted preflight 16/16 通过：Python 全量、前端 lint/typecheck/Vitest 694 项、构建、UI/控制/代码规模检查全部成功。"
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-09-02",
  "result": "修复公共来源成功抓取后的通知差集：后续 fan-out 快照不再覆盖任务基线，同一 source_fetch 的可信订阅身份可补齐中性共享内容缺失的 provenance，并保留共享历史不补发语义。",
  "status": "completed",
  "task_id": "2026-09-02-fix-public-source-notification-fanout",
  "unresolved": [
    "尚未部署 VPS；生产历史漏发内容按现有通知水位合同不自动补发。"
  ],
  "validation": [
    "新增公共来源抓取→任务快照→真实 fan-out→通知 outbox 集成回归，生产代码先稳定复现 0 条，修复后精确生成 1 条 pending delivery。",
    "通知、公共共享/复用与 Catalog runner 定向 Pytest 67 项通过；更新日志 Vitest 5 项、TypeScript、ESLint、编译和代码规模检查通过。",
    "impacted preflight 14/14 通过；本地唯一共享 Telegram 服务执行一次真实 smoke，返回 provider_accepted。"
  ]
}
```
