# WORKLOG

<!-- init-pro:compact-worklog schema=1 -->

Entries are maintained by `worklogctl.py`; read-only and no-op tasks are not logged.


```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-25",
  "result": "按 DeepSeek Harness 的连续滚动叙事框架重做 Inteliscope 双语官网：改为紧凑悬浮页头、沉浸首屏、居中来源/上下文宣言、三段交替真实产品场景、线性自托管架构、启动区与极简收尾，移除原卡片墙、信号路径与锚点导航式布局。",
  "status": "completed",
  "task_id": "2026-08-25-public-landing-scroll-redesign",
  "unresolved": [
    "完整 UI E2E 的既有 ActorOps、HeroUI 预览与 Workbench 失败未在本次官网重做中改动或更新视觉基线。"
  ],
  "validation": [
    "官网 Playwright 6/6 通过，覆盖桌面、平板、手机、双语、深浅模式、Reduced Motion、键盘焦点、零 API 请求、无横向溢出与 Axe serious/critical 为零。",
    "定向 Vitest 5/5、完整前端 lint、TypeScript、UI 合同、E2E 合同、生产构建和前端代码尺寸检查通过。",
    "浏览器逐屏检查深色首屏、浅色手机宣言与产品叙事段；桌面/手机视觉基线已重建并稳定复验。"
  ]
}
```

```json
{
  "control_topics": [
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-25",
  "result": "将公开根路径和 /en 收口为现代化单首屏项目介绍：以 Inteliscope 双弧粒子场、蓝色空间网格与深浅主题呈现项目定位，仅保留双语、外观和工作台入口，不展示功能、截图或命令安装模块，也不请求 Service API。",
  "status": "completed",
  "task_id": "2026-08-25-public-intro-particle-hero",
  "unresolved": [
    "impacted preflight 在本任务前已有的 src/services/subscription_mutation.py 冻结文件净增 4 行处提前失败；该无关改动未覆盖，完整 TypeScript 门禁也仍受既有 HeroSubscriptionDialogs info 状态类型错误阻断。",
    "未部署、未发布。"
  ],
  "validation": [
    "官网 Playwright 在桌面、平板、手机共 8 项通过、4 项按视口跳过，覆盖零 API、双语、键盘焦点、无横向溢出、Axe serious/critical 为零及深色桌面/浅色手机视觉基线。",
    "定向 Vitest 3 文件 9 项、完整 ESLint、UI 合同、E2E 合同、Vite 生产构建、前端代码尺寸和控制文件校验通过。",
    "impacted preflight 已按规定执行一次并保留无关冻结文件失败证据。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-25",
  "result": "Added an info-status compatibility mapping for Hero notices and rebuilt the local API/Worker image so the new public particle landing page is served by the local runtime.",
  "status": "completed",
  "task_id": "2026-08-25-landing-runtime-rebuild",
  "unresolved": [
    "Impacted preflight remains blocked by pre-existing growth in frozen src/services/subscription_mutation.py."
  ],
  "validation": [
    "Targeted design-system Vitest passed (2 tests).",
    "Frontend lint and Docker production build passed; local API and Worker report healthy.",
    "Browser DOM and screenshot confirmed the new particle landing page is served by the local runtime."
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
  "result": "公开介绍页已从业务启动链解耦，只以原生超链接进入项目；右侧改为双弧粒子眼，品牌图标粒子眼仁、眼弧和背景光带按分层惯性响应指针，并支持触屏漂移与 Reduced Motion 静止。",
  "status": "completed",
  "task_id": "2026-08-25-public-inteliscope-eye",
  "unresolved": [
    "完整 impacted preflight 被任务开始前已有的冻结后端文件 src/services/subscription_mutation.py 增长 4 行阻断；本次 frontend code-size scope 独立通过。"
  ],
  "validation": [
    "前端 ESLint、TypeScript、UI contract、生产构建与预览产物扫描通过；3 个定向 Vitest 文件共 12 项通过。",
    "Landing Playwright 在 1440/1024/390 px 共 9 项通过、6 项按设备条件跳过，覆盖零 API/业务包、Axe、无横向溢出、双语、视觉基线和眼仁左右追踪/回中质心。",
    "./scripts/up-latest.sh 重建成功，revision da7ff4a76bbd-dirty 的 API 与 Worker 均 healthy，8080 已提供新首页。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "ui"
  ],
  "recorded_on": "2026-08-25",
  "result": "将公开介绍页剥离为可独立启动的原生 HTML/CSS/Canvas 静态站点，并把右侧视觉重构为上强下柔的非对称凤眼、品牌粒子瞳孔、椭圆信息场与汇聚数据尘；通过静态背景分层、批量粒子绘制和自适应像素倍率消除 Retina 卡顿。",
  "status": "completed",
  "task_id": "2026-08-25-static-phoenix-eye-performance",
  "unresolved": [
    "影响域 preflight 仍被任务开始前已有的 src/services/subscription_mutation.py 冻结文件增加 4 行阻断；本任务相关的 src/api/server.py 增长已通过拆分路由模块消除。",
    "按用户要求未继续 Docker 构建或容器验收；静态页当前仅通过独立本地服务器提供。"
  ],
  "validation": [
    "静态几何 5 项测试、前端 TypeScript、ESLint、生产构建与静态产物合同通过。",
    "Playwright 1440/1024/390px 的静态资源隔离、零 API、Axe、双语、交互回中和视觉基线通过；最终像素倍率断言三档通过。",
    "1440x900 性能采样从平均 124ms/帧改善为 16.6ms/帧，DPR 2 环境同样约 16.6ms/帧且采样中没有超过 20ms 的帧。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-25",
  "result": "提升凤眼、信息场、品牌符号、汇聚尘与星尘密度；用分支分层采样使上下眼弧均匀闭合，并让下半弧保持连续可辨而在两端轻微消散。",
  "status": "completed",
  "task_id": "2026-08-25-static-phoenix-eye-density-repair",
  "unresolved": [
    "本地静态服务器继续运行在 127.0.0.1:4175，未启动 Docker 或项目容器。"
  ],
  "validation": [
    "静态几何 5 项测试、完整 landing Playwright 规格 9 项、Reduced Motion 与手机视觉基线、生产构建和静态产物合同通过。",
    "DPR 2 的 1440x900 动画采样平均 16.6ms、最慢 17.5ms，未出现超过 20ms 的帧。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-25",
  "result": "将信息之眼从均匀点描轮廓调整为有高密核心、扩散粒子带与游离数据尘的流场；增加眼弧和信息场粒子，并修正窄屏抽样只保留上弧导致下弧消失的问题。",
  "status": "completed",
  "task_id": "2026-08-25-particle-field-release",
  "unresolved": [],
  "validation": [
    "静态几何测试 5 项通过；前端生产构建与静态产物检查通过。",
    "Landing Playwright 共 9 项通过、6 项按视口条件跳过，包含桌面/手机视觉基线、零 API、可访问性及粒子眼仁的鼠标追踪/回中。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-25",
  "result": "按 Harness 顶部栏参考将静态首页页头改为统一悬浮玻璃胶囊，移除品牌图标及 favicon 的方形底；语言与工作台入口采用固定占位，切换中英文时不再发生水平抖动，并撤回误加的背景光带。",
  "status": "completed",
  "task_id": "2026-08-25-static-header-polish",
  "unresolved": [],
  "validation": [
    "静态几何测试 5 项通过。",
    "Landing Playwright 9 项通过、6 项按视口条件跳过，覆盖固定语言控件位置、视觉基线、零 API、可访问性及鼠标粒子交互。",
    "前端生产构建与静态产物检查通过。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-25",
  "result": "公开静态页的页头改为滚动驱动状态：顶部保持无底导航，向下滚动后整条收拢为悬浮玻璃胶囊，回到顶部还原；同时保留无框品牌符号、透明 favicon 与稳定的双语控件占位。",
  "status": "completed",
  "task_id": "2026-08-25-static-scroll-header",
  "unresolved": [],
  "validation": [
    "静态几何测试 5 项通过。",
    "滚动页头 Playwright 专项、桌面深色与手机浅色视觉基线通过。",
    "前端生产构建、静态产物检查和 git diff --check 通过。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-25",
  "result": "按 DeepSeek Harness 实测参数重新校准滚动玻璃导航：收拢态高度 42px、最大宽度 980px、桌面两侧 40px 安全边距，采用 25% 中性白玻璃、12px 背景模糊和无阴影呈现，并同步压缩内部品牌与操作控件。",
  "status": "completed",
  "task_id": "2026-08-25-scroll-header-harness-calibration",
  "unresolved": [],
  "validation": [
    "浏览器实测本地滚动态为 663×42px，颜色 rgba(255,255,255,.25)、backdrop blur(12px)。",
    "滚动页头 Playwright 专项与静态几何 5 项通过。",
    "前端生产构建、静态产物检查和 git diff --check 通过。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-25",
  "result": "为信息之眼中央品牌符号增加独立粒子运动：粒子在保持图标轮廓的前提下进行轻微径向聚散、切向漂移与明暗呼吸，单粒子位移限制在 4px 内；Reduced Motion 下保持完全静止。",
  "status": "completed",
  "task_id": "2026-08-25-logo-particle-motion",
  "unresolved": [],
  "validation": [
    "静态几何测试 6 项通过，覆盖粒子位移上限、时序变化及 Reduced Motion 静止。",
    "粒子眼仁鼠标跟随与回中 Playwright 专项通过。",
    "本地浏览器刷新目视验收通过；前端生产构建、静态产物检查和 git diff --check 通过。"
  ]
}
```

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
