# WORKLOG

<!-- init-pro:compact-worklog schema=1 -->

Entries are maintained by `worklogctl.py`; read-only and no-op tasks are not logged.


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

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-09-02",
  "result": "新增统一的稳定异步按钮并迁移系统内保存、提交、测试、刷新、连接、删除等文字操作；通知设置保存不再重挂载表单，UI 合同与静态门禁禁止中间态改变按钮外部几何。",
  "status": "completed",
  "task_id": "2026-09-02-stable-async-buttons",
  "unresolved": [
    "完整 Playwright 运行仍有 8 个与本次按钮和更新日志改动无关的既有失败，集中在旧 HeroUI 预览 CSS 隔离及 ActorOps/页头视觉快照；本次直接影响的更新日志验收修正后已全部通过。"
  ],
  "validation": [
    "StableAsyncButton、UI 合同、通知设置与更新日志定向 Vitest 57 项通过；完整 Vitest 96 文件 698 项通过。",
    "TypeScript、ESLint、UI 合同、生产构建及预览产物检查通过；门禁控制、代码尺寸和 diff 检查通过。",
    "补齐声明的 dev 依赖后，门禁选中的后端 Pytest 组完整通过。",
    "本地通知页 DOM 验证按钮为 110×36 px，正常态和保存中状态共用同一布局轨道；更新日志相关 Playwright 4 项在桌面、平板和移动端通过。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-09-02",
  "result": "将用户发起的刷新与重试收敛到 RefreshButton：图标立即旋转，快请求仍保留 400 ms 可感知反馈，长请求持续到完成，并保持文案、图标位置与按钮几何稳定；已迁移存储、助手、订阅、系统设置、密钥与 ActorOps 的同类请求按钮。",
  "status": "completed",
  "task_id": "2026-09-02-refresh-button-feedback",
  "unresolved": [],
  "validation": [
    "RefreshButton、StableAsyncButton、UI 合同与更新日志定向 Vitest 60 项通过，受影响文件 ESLint、UI 合同检查与生产构建通过。",
    "本地真实浏览器验收 /agents 与 /settings/storage：点击后旋转类、busy 状态、禁用状态与稳定可见文案均生效。",
    "完整 impacted preflight 14/14 通过，包含 97 个前端测试文件共 702 项、控制合同、代码尺寸、后端定向检查与生产构建。"
  ]
}
```

```json
{
  "control_topics": [
    "decisions",
    "instructions",
    "ui"
  ],
  "recorded_on": "2026-09-02",
  "result": "纠正分支关系：本地 main 回退到 39ee4a92 后，纯快进合入 codex/non-docker-dev-20260902 的稳定异步/刷新按钮修改；随后在同一分支将固定版本外部 UI 教材蒸馏为项目唯一交互宪章、Skill 入口、验收清单和自动影响映射。",
  "status": "completed",
  "task_id": "2026-09-02-ui-contract-distillation",
  "unresolved": [
    "移动端部分输入控件沿用现有 13px type-control，可能触发 iOS Safari 聚焦缩放；按用户裁决本次不改变现法，仅保留后续审计项。"
  ],
  "validation": [
    "按钮修改完整 Vitest 97 文件 703 项、TypeScript、UI 合同、生产构建通过；43 文件 staged preflight 14/14 通过。",
    "项目 inteliscope-ui Skill quick_validate、Markdown/项目控制、worklog、JSON、UI 合同、TypeScript 和 diff 检查通过。",
    "蒸馏差异 staged preflight 16/16 通过，覆盖控制面、Python/前端全量、生产构建和 UI 合同。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-09-03",
  "result": "完成新 UI Skill 驱动的全局交互整改：稳定异步按钮增加同步单飞锁，刷新、订阅、通知、成员、存储、ActorOps 与专题操作统一局部 pending 反馈；新增 coarse-pointer 按钮命中区、OverflowValue 长文本入口及保留页面上下文的 Empty/Error 状态。",
  "status": "completed",
  "task_id": "2026-09-03-global-ui-interaction-remediation",
  "unresolved": [
    "代码仅保留在 codex/non-docker-dev-20260902，等待用户完成实际操作与视觉验收；未经明确批准不得合入 main。",
    "移动端 13px 输入文字及 iOS 自动缩放风险按既有裁决本次不修改。"
  ],
  "validation": [
    "UI Contract 与 TypeScript 检查通过；12 个直接影响 Vitest 文件共 131 项通过，StableAsyncButton 额外回归 7 项通过。",
    "Markdown、project-controls、Worklog、JSON 与 diff 校验全部通过；生产构建在实现阶段通过。",
    "唯一一次 impacted preflight 14/14 通过，覆盖 control、frontend_full 与 python_api_store，无 SQLite 连接泄漏警告。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-09-03",
  "result": "修复 StableAsyncButton 同步锁在真实浏览器中抢先禁用 submitter、导致登录和设置表单无响应的回归：表单按钮先完成原生 submit 分发，再发布 pending，连续点击仍由同步锁阻止。",
  "status": "completed",
  "task_id": "2026-09-03-fix-stable-submit-activation",
  "unresolved": [
    "修复仅提交到 codex/non-docker-dev-20260902，继续等待用户实际验收，未经批准不得合入 main。"
  ],
  "validation": [
    "StableAsyncButton、登录、订阅、通知、RSSHub 设置与更新日志定向 Vitest 7 文件 37 项通过；TypeScript 与 UI Contract 检查通过。",
    "真实浏览器使用虚构账号发起登录探针，服务端返回明确的账号密码错误，证明 submit 与 API 请求恢复；浏览器无 error。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-09-03",
  "result": "按项目 UI Constitution 完成 M1-M7 全局交互稳定性整改：统一异步与刷新单飞反馈、保留局部内容和 DOM 身份、补齐粗指针命中区与 Reduced Motion、改善长文本及局部空错状态，并强化 UI 静态合同。",
  "status": "completed",
  "task_id": "2026-09-03-global-ui-interaction-stability",
  "unresolved": [
    "修改仅保留在 codex/non-docker-dev-20260902 供用户视觉与操作验收，未经明确确认不合入 main、不推送。"
  ],
  "validation": [
    "前端 lint、typecheck、UI contract、生产构建与全量 Vitest 100 文件 729 项全部通过。",
    "snapshot impacted preflight 14/14 通过，覆盖控制面、前端全量、Python API/store 与映射 UI E2E；代码体积冻结策略通过。",
    "目标 Worktree 的非 Docker API、Vite 与 Worker 已启动，8080/5173 readiness 均为 ready 且 worker_status=ready。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-09-03",
  "result": "ActorOps 替换候选会把同一商城 Actor 的另一固定版本明确标为独立核验的新版本；候选读取失败时隐藏旧推荐并禁止继续替换，精确 Build 保留在技术详情。",
  "status": "completed",
  "task_id": "2026-09-03-actorops-same-actor-version-recommendation",
  "unresolved": [],
  "validation": [
    "ActorOps 候选卡、替换 Drawer 和路由模型定向 Vitest 22/22 通过，TypeScript、ESLint 与 UI 合同检查通过。",
    "ActorOps 三视口 Playwright 13 passed、2 skipped；同 Actor 新版本提示、焦点恢复和无横向溢出通过。"
  ]
}
```
