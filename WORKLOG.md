# WORKLOG

<!-- init-pro:compact-worklog schema=1 -->

Entries are maintained by `worklogctl.py`; read-only and no-op tasks are not logged.


```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-26",
  "result": "将信息之眼中央品牌图标粒子的切向游走、径向聚散和亮度呼吸整体提速约 40%，保持原有 4px 位移限制与 Reduced Motion 静止行为。",
  "status": "completed",
  "task_id": "2026-08-26-logo-particle-motion-speed",
  "unresolved": [],
  "validation": [
    "静态几何测试 6 项通过。",
    "本地静态预览刷新并目视检查通过。",
    "git diff --check 通过。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-26",
  "result": "校准公开静态页的滚动玻璃导航为低反差深海军蓝并减轻导航字重；加快眼弧、信息轨道和品牌眼仁粒子；背景网格、星尘与雾光改为分层漂移，并新增随精细指针产生、约 900ms 柔性复原的局部空间透镜扭曲，粗指针和 Reduced Motion 不启用透镜。",
  "status": "completed",
  "task_id": "2026-08-26-landing-space-warp-polish",
  "unresolved": [],
  "validation": [
    "对照 DeepSeek Harness 实际页面的近快远慢交互层次，并在本地浏览器完成鼠标扭曲与滚动玻璃导航目视验收。",
    "静态几何测试 7 项通过；Landing Playwright 三视口 12 项通过、6 项按条件跳过。",
    "前端生产构建和静态产物检查通过。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-26",
  "result": "公开静态页的信息之眼新增低幅呼吸、周期自然眨眼和同步眼仁淡出，外层轮廓尘减速且眼仁底光改为无边界渐隐；背景星尘改为非均匀聚簇与多级大小/亮度，指针速度驱动空间透镜半径，暗色网格单元与线条共同弯曲。页面固定为深色并移除主题切换，右上登录入口替换为项目 GitHub Releases。",
  "status": "completed",
  "task_id": "2026-08-26-breathing-eye-adaptive-lens",
  "unresolved": [],
  "validation": [
    "对照 DeepSeek Harness 的分层光场响应，并在本地浏览器检查睁眼、眨眼、快速指针光圈和深色移动端布局。",
    "静态几何测试 9 项通过；Landing Playwright 三视口 12 项通过、6 项按条件跳过，并更新深色桌面/手机视觉基线。",
    "前端生产构建与静态产物检查通过；旧浅色手机视觉基线已删除。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-26",
  "result": "将信息之眼眨眼重构为直接作用于粒子眼睑边界的 900ms 状态机：70/30 几何闭合、羽化吞没虹膜与眼仁、4–9 秒随机间隔、15% 双眨、指针靠近后 500–900ms 注意触发及冷却；Reduced Motion 下禁用眨眼。",
  "status": "completed",
  "task_id": "2026-08-26-natural-geometric-blink",
  "unresolved": [],
  "validation": [
    "静态几何测试 12 项通过，覆盖完整眨眼阶段、随机区间、双眨分布、眼睑收拢与粒子羽化。",
    "桌面 Playwright 专项通过：注意触发眨眼、频繁移动冷却，以及眼仁跟随和回中。",
    "本地浏览器验证 prepare/closed 阶段时序；前端生产构建、静态产物检查和 git diff --check 通过。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-26",
  "result": "公开静态页新增分层加载渐入：背景先显现，导航与文案错峰进入，信息之眼沿现有粒子眼睑几何约 1.5 秒从眼缝缓慢睁开；Reduced Motion 跳过入场。滚动玻璃导航降至 56% 深海军蓝，STATIC PREVIEW 调整为 10px/400。",
  "status": "completed",
  "task_id": "2026-08-26-landing-load-reveal-eye-open",
  "unresolved": [
    "非本任务的 src/services/subscription_mutation.py 相对仓库基线从 2238 增至 2242 行，导致 impacted preflight 的 code_size_policy 失败；本任务未修改该文件。"
  ],
  "validation": [
    "静态几何测试 13 项通过，覆盖几何睁眼阶段和 Reduced Motion 稳定态。",
    "桌面 Playwright 滚动玻璃导航专项通过；前端生产构建与静态产物检查通过。",
    "任务影响域 preflight 的 Markdown 控制检查通过，但代码尺寸门禁被任务前已有的 src/services/subscription_mutation.py 冻结文件增长 4 行阻断。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-26",
  "result": "按用户要求将粒子介绍页迁至独立工作目录，改为独立的本地静态调试站；主项目已移除其 Docker、Vite、构建、服务路由、文档和专属测试挂接。页面默认主入口改为项目 GitHub 链接，不再指向 /login。",
  "status": "completed",
  "task_id": "2026-08-26-detach-static-introduction",
  "unresolved": [],
  "validation": [
    "独立站几何测试 13 项通过，根路径与英文路径均返回独立静态页。",
    "主项目前端生产构建、静态产物检查和 React 服务路由测试通过。",
    "主项目中不再检出 landing-site、/_landing、landing.html、静态介绍路由或构建挂接引用。"
  ]
}
```

```json
{
  "control_topics": [],
  "recorded_on": "2026-08-26",
  "result": "完成 v2.5.2 正式发布前准备：整合本地页面标题栏、静态路由模块化与来源订阅兼容修复，并通过定向质量检查。",
  "status": "completed",
  "task_id": "2026-08-26-v2-5-2-release-preparation",
  "unresolved": [
    "待将已授权的提交整合并推送至 main，由精确 main CI、tag smoke 和 VPS 健康检查完成正式发布。"
  ],
  "validation": [
    "后端 tests/test_api_service.py 93 项通过。",
    "前端 AppBootstrap 与 design-system 定向 Vitest 5 项、TypeScript 与 ESLint 通过。",
    "git diff --check 与 worklog schema 校验通过。"
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
  "recorded_on": "2026-08-25",
  "result": "修复 Apify 专用 validation Key 的历史 unknown-start 错误阻塞生产 Key 排空：生产 drain 仅统计 acquisition 角色 Run，专用 validation 保留独立锁定并仅以原 Key 的账户时间窗 GET 证据收口；Worker 在 claim 前有界对账且失败不阻塞普通 Job。",
  "status": "completed",
  "task_id": "2026-08-25-apify-validation-drain-isolation",
  "unresolved": [
    "本地部署启动时 Worker 领取既有任务并登记了一个新的 acquisition 远端 Run，已立即停止 Worker 防止继续调用；该 Run 的远端读取或终止需要 acquisition Key 的单独授权。"
  ],
  "validation": [
    "32 项 Apify Key-pool 定向回归与 10 项 Worker 相关测试通过。",
    "snapshot impacted preflight、Markdown/control、worklog、JSON 与 diff 检查通过。",
    "从目标 worktree 部署后，池由 draining/generation 1940 恢复为 ready/generation 1941，备用 acquisition Key 已 active；历史 validation unknown-start 由空窗口证据终结为 start_rejected、$0、charge_final。",
    "部署前创建主运行库 0600 SQLite 备份。"
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
  "recorded_on": "2026-08-25",
  "result": "Instagram ActorOps v2 sources now retain a validated avatar candidate across content time-window filtering, treat malformed optional avatar URLs as non-fatal, and cache it through the existing protected source-avatar path without an extra Actor call.",
  "status": "completed",
  "task_id": "2026-08-25-instagram-source-avatar",
  "unresolved": [
    "No production source fetch, paid Actor call, AI call, notification, deployment, release, tag, or push was performed. Existing Instagram sources recover on their next scheduled or manually requested normal fetch; Actors that do not emit a valid avatar keep the IG fallback."
  ],
  "validation": [
    "Targeted Actor manifest, ActorOps adapter/source execution/service, runtime, social scraper, source-avatar, and catalog runner tests passed.",
    "Frontend SourceAvatar Vitest, TypeScript typecheck, and ESLint passed.",
    "Backend and frontend code-size comparisons against the task baseline plus git diff --check passed."
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-26",
  "result": "修复 ActorOps v2 路由详情 E2E mock 缺失的 Binding 核验字段，并让 Workbench Agent 面板的布局切换不等待不存在的导航，消除 4 项 CI UI 回归。",
  "status": "completed",
  "task_id": "2026-08-26-release-ui-gate-repair",
  "unresolved": [],
  "validation": [
    "Linux Playwright release E2E：121 通过、62 按项目规则跳过、0 失败（含三端 ActorOps 视觉/交互和 Workbench Insights）。",
    "staged impacted preflight：前端 lint、类型、Vitest、生产构建、代码尺寸与 E2E 合约全部通过。"
  ]
}
```

```json
{
  "control_topics": [],
  "recorded_on": "2026-08-26",
  "result": "修复 ActorOps v2 repair 已注册处理器却遗漏 Worker 可领取类型的策略缺口，防止 repair 永久 queued、取消后重入队并阻塞正式发布；发布版本顺延至 v2.5.3。",
  "status": "completed",
  "task_id": "2026-08-26-actorops-repair-claim-policy",
  "unresolved": [],
  "validation": [
    "Worker policy、ActorOps v1 隔离与 v2 housekeeping 定向回归 10 项通过。",
    "snapshot impacted preflight 16/16 通过，覆盖完整后端/前端、代码尺寸、控制合同与 diff 检查。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-26",
  "result": "将订阅页顶部导航、搜索、筛选和新增来源重构为参考 DeepSeek Harness 的一体式胶囊 command bar，保留滚动收拢、权限语义和移动端两行布局，并同步明暗主题视觉基线与用户文档。",
  "status": "completed",
  "task_id": "2026-08-26-subscription-command-bar",
  "unresolved": [],
  "validation": [
    "Vitest 直接相关 116 项、TypeScript、ESLint、UI contract 和 frontend code-size 均通过。",
    "订阅 Playwright 交互规格在桌面/平板/手机共 4 项通过、2 项按设备条件跳过；明暗主题三视口视觉基线在 macOS 与 Linux 均通过并更新。",
    "impacted preflight 12/12 通过；浏览器验证 320 px 无横向溢出，开发服务器运行在 127.0.0.1:5173。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-26",
  "result": "将订阅 command bar 的搜索框改为紧邻页签组左侧起排，并移除页签滚动容器无必要的稳定滚动条槽；桌面实测间隔由 19 px 收为 8 px，手机两行布局保持不变。",
  "status": "completed",
  "task_id": "2026-08-26-subscription-search-left",
  "unresolved": [],
  "validation": [
    "订阅路由定向 Vitest 通过。",
    "浏览器 1280 px 实测页签与搜索同排且间隔 8 px。",
    "impacted preflight 11/11 通过，frontend code-size 与 git diff check 通过。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-26",
  "result": "将订阅页标题栏从内缩圆角面改为铺满 52 px 顶部轨道的 flush 外观，去除四周黑色画布，仅保留底部分隔线；Bootstrap 静态壳同步相同几何。",
  "status": "completed",
  "task_id": "2026-08-26-subscription-header-flush",
  "unresolved": [],
  "validation": [
    "浏览器实测标题栏 x/y 为 0、宽 320 px、高 52 px、margin/radius 为 0，仅底边 1 px。",
    "TypeScript、ESLint、UI contract、定向 Vitest 和 page-header 三视口 Playwright 6 项通过。",
    "impacted preflight 12/12 通过，frontend code-size 与 git diff check 通过。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-26",
  "result": "将全部已登录页面的共享标题栏统一为半透明圆角玻璃胶囊；设置工作区复用同一 PageHeader，外侧 4/8px 留白由语义表面承接，不再露出黑色条带，刷新前 Bootstrap 几何同步。",
  "status": "completed",
  "task_id": "2026-08-26-global-transparent-rounded-header",
  "unresolved": [],
  "validation": [
    "共享模式、Bootstrap、Settings 与 Workbench 定向 Vitest 共 37 项通过；TypeScript、ESLint 与 UI contract 通过。",
    "PageHeader Playwright 桌面、平板、手机 6 项通过，覆盖 Feed、History、Subscriptions、Agents、Settings 与 Bootstrap takeover。",
    "本地浏览器实测 Settings 与 History 均为 44px、999px 圆角、75% 语义表面、24px blur、无横向溢出；impacted preflight 12/12 通过。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-26",
  "result": "按用户确认删除透明圆角 PageHeader 外侧整条横向轨道背景与扩散外圈，仅保留半透明胶囊、细边框和圆角；Bootstrap 同步移除外圈绘制。",
  "status": "completed",
  "task_id": "2026-08-26-remove-page-header-outer-track",
  "unresolved": [],
  "validation": [
    "宽屏本地订阅页截图复查通过，计算样式 box-shadow 为 none，胶囊仍为 75% 语义表面与 999px 圆角。",
    "定向 Vitest 5 项、PageHeader 三视口 Playwright 6 项、impacted preflight 12/12 通过。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-26",
  "result": "修正全站透明圆角标题的真实层级：Workbench、Settings 与刷新前 Bootstrap 的页面画布均从 y=0 延伸到标题背后，52px 只作为正文避让空间，不再由独立黑色顶栏轨道占位；同时修复设置页网格自动排版导致标题落到底部的问题。",
  "status": "completed",
  "task_id": "2026-08-26-page-header-canvas-overlay",
  "unresolved": [],
  "validation": [
    "浏览器逐页实测订阅、历史、设置：画布 top=0、正文 padding-top=52px、标题 top=4/height=44/radius=999px/box-shadow=none。",
    "相关 Vitest 38 项通过；TypeScript、ESLint、UI contract 与 git diff check 通过。",
    "PageHeader Playwright 桌面、平板、手机 6 项通过；一次移动端接管时序波动在单场景重跑和完整重跑中均通过。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-27",
  "result": "Implemented a shared y=0 scroll region with scrollable 52px top clearance across authenticated pages, corrected sticky offsets to avoid double spacing, and added deterministic real-content glass-header overlap coverage for desktop, tablet, and mobile.",
  "status": "completed",
  "task_id": "2026-08-27-page-header-real-scroll-through",
  "unresolved": [],
  "validation": [
    "Vitest: 5 files / 41 tests passed",
    "Playwright page-header-geometry: 6 passed",
    "TypeScript, ESLint, UI contract, code-size policy, and git diff checks passed"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-27",
  "result": "Reduced the subscriptions page initial header-to-toolbar gap from 28px to 20px while preserving the y=52 sticky position and real scroll-through behavior; refreshed responsive light/dark snapshots.",
  "status": "completed",
  "task_id": "2026-08-27-subscriptions-header-spacing",
  "unresolved": [],
  "validation": [
    "Vitest: 2 files / 15 tests passed",
    "Playwright subscription semantic visual baselines: 3 passed",
    "TypeScript and browser geometry checks passed"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-27",
  "result": "Replaced the Linux PageHeader scroll-through visual baselines with the verified CI actual images after a platform font-rendering mismatch; no layout or runtime behavior changed.",
  "status": "completed",
  "task_id": "2026-08-27-page-header-linux-visual-baselines",
  "unresolved": [],
  "validation": [
    "CI artifact visual review for desktop, tablet, and mobile",
    "Playwright page-header-geometry: 6 passed"
  ]
}
```
