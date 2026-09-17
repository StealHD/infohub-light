# WORKLOG

<!-- init-pro:compact-worklog schema=1 -->

Entries are maintained by `worklogctl.py`; read-only and no-op tasks are not logged.


```json
{
  "control_topics": [
    "verification"
  ],
  "recorded_on": "2026-09-15",
  "result": "在本地 main 工作区修复 df068ba9 简化发布后遗漏的重复测试：移除运行时测试中要求 Tag 查询旧 Gate 与执行 smoke 的断言，由既有 Tag 专项测试集中验证版本、main 归属和无 CI/smoke 依赖；开发 CI 的手动 smoke 检查保留。仅修改测试，不改变发布流程或图片适配。",
  "status": "completed",
  "task_id": "2026-09-15-tag-workflow-test-sync",
  "unresolved": [],
  "validation": [
    "修复前定向复现 tests/test_light_runtime_scripts.py:1085 旧 Gate 查询断言失败；该文件被 python_api_store 和 python_scripts 共用。",
    "相关 Pytest 四个文件 67 项通过；任务范围 diff 审查与 git diff --check 通过。",
    "任务 snapshot impacted preflight 8/8 通过，无映射遗漏与未关闭 SQLite 连接警告；证据 .test-results/20260915T115236Z-99665/result.json。"
  ]
}
```

```json
{
  "control_topics": [
    "verification"
  ],
  "recorded_on": "2026-09-15",
  "result": "按用户要求将本地 main 已验证的两份 Tag 发布测试修复补丁应用到 codex/analyze-openai-reset-test-miss 与 codex/ui-sidebar-automations-0915 工作区；两处均保留为未提交修改，未合并或推送。",
  "status": "completed",
  "task_id": "2026-09-15-apply-tag-test-fix-to-two-branches",
  "unresolved": [],
  "validation": [
    "两个目标均通过 git apply --check；应用后两份测试文件与本地 main 修复逐字节一致。用户随后明确只需应用，不追加 preflight。"
  ]
}
```

```json
{
  "commit": "1735c336",
  "control_topics": [
    "architecture",
    "interface",
    "ui",
    "verification"
  ],
  "recorded_on": "2026-09-15",
  "result": "修复 ActorOps 已结算成功 Run 因原 source_fetch Job 失败而长期阻塞的问题：Reconciler 以 CAS 重排 exact Job，运行时只读原 Dataset 并重新验证/发布，不创建第二个 Attempt、费用预留或 Actor POST；明确区分费用待结算与结果待恢复，原 Job 取消时保留真实费用并安全终结。",
  "status": "completed",
  "task_id": "issue-3-actorops-result-recovery-20260915",
  "unresolved": [],
  "validation": [
    "合并后的 main 后端全量 Pytest 通过；前端全量 150 个测试文件、939 项通过。",
    "工作日志、Markdown、可观测性和差异检查通过；合并提交为 1735c336。"
  ]
}
```
```json
{
  "commit": "1735c336",
  "control_topics": [
    "architecture",
    "interface",
    "ui",
    "verification"
  ],
  "recorded_on": "2026-09-15",
  "result": "实现 Instagram 独立帖子媒体提取、图集和视频封面缓存接入、详情顺序保持，以及默认预览和显式摘要确认的单文章补图 CLI。媒体通过原帖子身份校验关联，不修改 Candidate Manifest；维护路径只复用私有地址或同来源已结算 Run 的既有 Dataset，不创建 Actor、费用预留、文章、快照、AI 或通知。",
  "status": "completed",
  "task_id": "instagram-post-media-adaptation-20260915",
  "unresolved": [
    "两个旧成功 Dataset 返回 404，未做历史文章补图；用户确认不需要补回。"
  ],
  "validation": [
    "Instagram 提取、补图、媒体缓存、展示、ActorOps 映射与旧内容修复关联回归 77 项通过；合并后的 main 后端全量 Pytest 通过。",
    "前端全量 150 个测试文件、939 项通过；工作日志、Markdown、可观测性和差异检查通过；合并提交为 1735c336。"
  ]
}
```

```json
{
  "control_topics": [
    "ui",
    "verification"
  ],
  "recorded_on": "2026-09-15",
  "result": "Automations 详情栏改为与任务列表同轨占宽，顶栏随列表同步缩短；详情操作统一为有说明的图标按钮，描述箭头和测试区操作完成右对齐，并同步 UI 合同、手册与更新日志。独立分支未修改后端、数据库、自动化执行或通知行为。",
  "status": "partial",
  "task_id": "2026-09-15-ui-sidebar-automations-0915",
  "unresolved": [
    "impacted preflight 被现有 Release Tag workflow 合同基线断言阻断；同一断言已在未包含本分支改动的本地 main 独立复现，本次 UI-only 范围未修改发布工作流。"
  ],
  "validation": [
    "定向前端 20/20、完整前端 151 个文件共 943 项、TypeScript、ESLint、UI 合同、生产构建及产物检查通过。",
    "Playwright 桌面、平板、手机共 12/12 通过，覆盖明暗主题、200% 缩放、详情开关、拖动与键盘调宽、焦点返回、草稿保留、等待态尺寸和无横向溢出；使用模拟接口，未触发真实抓取、模型或通知。",
    "impacted targeted/preflight 在基线失败前完成 7 项控制与格式检查；Release Tag workflow 合同断言在本地 main 单测中同样失败。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-09-15",
  "result": "修复工作区切换菜单左右留白不对称与品牌按钮常驻背景；Automations 新建和编辑操作靠右，来源选择与模型刷新分列对齐，触发与通知字段进入编辑后直接显示；同步 UI 合同、操作手册和变更日志。",
  "status": "completed",
  "task_id": "ui-workspace-automation-edit-polish-20260915",
  "unresolved": [
    "内置浏览器不响应页面缩放快捷键，未取得实际 200% 缩放测量；已用 390×844、1024×768、1440×900 和 320 px 详情宽度覆盖重排与溢出风险。"
  ],
  "validation": [
    "工作区菜单在 1440×900 实测侧栏 232 px、菜单 216 px、左右各 8 px且页面无横向溢出；Automations 在 400 px 与 320 px 详情宽度下操作靠右、触发字段直接可见。",
    "1024×768 Drawer 与 390×844 Sheet 均无横向溢出；手机面板宽 390 px，模型、推理、触发和通知选择控件均完整位于 21–369 px 内容区。",
    "定向 Vitest 7 项通过；Information Automations 分组已执行的 26 项通过，另有 1 个 worker 启动超时后将该文件 2 项单独复验通过；lint、typecheck、UI contract 通过；impacted preflight 11/11 通过。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-09-15",
  "result": "信息流右侧 Agent 不再使用独立模型与思考下拉框，改为与完整 OpenClaw 对话共用模型、思考、Fast 和默认恢复胶囊浮层；同步 UI 合同、操作手册与变更日志。",
  "status": "completed",
  "task_id": "ui-inscope-openclaw-runtime-picker-20260915",
  "unresolved": [],
  "validation": [
    "OpenClaw 对话相关 Vitest 3 个文件 44 项通过；typecheck 与 UI contract check 通过。",
    "127.0.0.1:5173/feed 实页确认右侧 Agent 显示统一 GPT-5.6-Terra／medium 胶囊，展开后可见 Fast、模型入口、思考滑杆和默认恢复；未发送消息或调用模型。",
    "impacted preflight 13/13 通过，包含 frontend_full、control 与 python_api_store 分组。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-09-15",
  "result": "OpenClaw 会话入口并入侧栏标题行并与工作区箭头对齐；删除确认支持成功后按账号记住不再提醒并可从全部会话恢复；完整工作台和信息流 Agent 共用右对齐用户气泡；执行详情逐项显示安全操作名、状态和耗时并明确截断或缺失证据。同步 UI 合同、手册与更新日志，未改后端、数据库或真实执行行为。",
  "status": "completed",
  "task_id": "ui-openclaw-conversation-messages-20260915",
  "unresolved": [],
  "validation": [
    "相关会话、删除偏好、消息气泡和事件投影 Vitest 通过；TypeScript、ESLint、UI contract 和 diff 检查通过。",
    "127.0.0.1:5173 实页确认加号与工作区箭头对齐、全部会话删除开关、确认框不再提醒、用户气泡靠右且多条助手回复纵向排列；未发送消息、删除会话或调用模型。",
    "impacted preflight 13/13 通过，覆盖 control、frontend_full 与 python_api_store，0 失败。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-09-16",
  "result": "OpenClaw 侧栏移除会话区与工作区之间的装饰分隔线，将全部会话改为带说明的历史图标并与新对话加号同排；完整工作台移除助手消息之间的装饰横线。同步 UI 合同、操作手册与更新日志，未改变会话、消息或 Gateway 业务行为。",
  "status": "completed",
  "task_id": "ui-openclaw-remove-dividers-history-icon-20260916",
  "unresolved": [],
  "validation": [
    "相关 Agent Workspace 与 OpenClaw 会话 Vitest 17/17 通过；TypeScript、ESLint、UI contract 和 diff 检查通过。",
    "127.0.0.1:5173 实页确认两处装饰横线已移除、全部会话与新对话图标同排，历史图标可正常打开原会话目录；未发送消息或删除会话。",
    "impacted preflight 13/13 通过，覆盖 control、frontend_full 与 python_api_store，0 失败。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-09-16",
  "result": "修复完整 OpenClaw 会话的运行/发送错误错位：将错误提示从外层滚动区改为复用居中消息宽度轨道；错误内容、连接/重试行为与紧凑 Agent 布局未改变。为保持代码规模限制，将提示抽为同目录专用组件，并同步 UI 合同与更新日志。",
  "status": "completed",
  "task_id": "ui-openclaw-issue-track-alignment-20260916",
  "unresolved": [],
  "validation": [
    "OpenClaw 会话回归 34/34 通过；TypeScript、ESLint、UI contract 及前端代码规模检查通过。",
    "新增 workspace 错误轨道断言，确认错误提示具有与 transcript 相同的居中最大宽度；未中断当前 Gateway 或发送消息来制造真实错误。",
    "首次 preflight 仅因 OpenClawTimeline 超过 150 行失败；抽取组件后 impacted preflight 13/13 通过，0 失败。"
  ]
}
```

```json
{
  "control_topics": [
    "verification"
  ],
  "recorded_on": "2026-09-16",
  "result": "修复普通发布未传 v47 回执时 SSH 丢弃空尾参数、VPS cutover 在严格模式读取第 10/11 参数失败的问题；可选回执与备份均使用安全空值默认，不改变迁移、备份、切换或回滚边界。",
  "status": "completed",
  "task_id": "release-empty-migration-arguments-20260916",
  "unresolved": [],
  "validation": [
    "tests/test_release_runtime_scripts.py 与 tests/test_release_preflight.py 定向回归通过；bash -n scripts/release_vps.sh 和 git diff --check 通过。",
    "首次真实发布在 VPS 切换前安全停止，未创建 Tag；修复后将从同一干净 main 重试。"
  ]
}
```

```json
{
  "control_topics": [
    "observability",
    "verification"
  ],
  "recorded_on": "2026-09-16",
  "result": "从 v2.6.22 定位客户端代理路径的同步断线，为站点添加持久化精确域名直连规则并补充故障定位操作说明；以回退提交 d4b9f6d0 撤销未发布的 v2.6.23，已推送 main，生产保持 v2.6.22。",
  "status": "completed",
  "task_id": "web-disconnect-proxy-route-20260916",
  "unresolved": [
    "代理节点内部周期关闭连接的原因未调查；本次定位并绕开当前客户端的异常代理路径。"
  ],
  "validation": [
    "同机同时三分钟持久 HTTPS 对照：直连 35 次成功、0 断线、1 条连接；原代理路径 23 次成功、3 次断线、4 条连接。",
    "代理路径三次中断时间与 API browser_transport/1006 对齐；90 秒 TCP 关闭标志采样覆盖其中两次，均看到代理出口先发 FIN/RST。",
    "规则生效后重复同样测试：两个入口均 35 次成功、0 断线、1 条连接；实际 Chrome 两条连接保持原 ID 并持续双向流量。",
    "文档 impacted preflight 5/5 通过；main 回退后与 v2.6.22 文件树完全一致。",
    "2026-09-16 15:57 至 16:22，两条实际 Chrome 连接分别持续 1474/1449 秒，连接 ID 保持且双向流量增长；用户确认页面恢复后结束观察，未宣称完成原计划 30 分钟。",
    "截至 16:22:03，API 有界日志查询显示 15:58 后 relay 关闭记录为 0；容器 restart_count=0、OOM=false。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-09-16",
  "result": "从本地 main 创建独立 worktree，优化 /agents：管理员个人 Agent 与成员审批页签改为紧凑并说明用途，个人状态区分网页聊天连接与接入状态，外部 MCP 连接明确适用场景并折叠旧手动配置命令；同步操作手册与更新日志。",
  "status": "completed",
  "task_id": "agents-connection-ui-20260916",
  "unresolved": [],
  "validation": [
    "相关 Vitest 4 文件 20 项通过，TypeScript 类型检查与 UI 静态契约通过。",
    "Playwright 托管接入桌面与手机 4 项通过，并查看深色桌面与手机截图；浅色和 200% 重排截图生成。",
    "impacted preflight 13/13 通过；首次尝试因系统 Python 缺少 pytest 停止，改用现有项目虚拟环境后完整通过。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "ui",
    "verification"
  ],
  "recorded_on": "2026-09-17",
  "result": "在现有 codex/agents-connection-ui-20260916 分支移除外部 MCP 连接页面入口，收紧个人 Agent 卡片的状态、权限与操作布局；既有服务端手动授权保持兼容，文档与页面说明同步更新。未提交或部署。",
  "status": "completed",
  "task_id": "agents-unified-connection-ui-20260917",
  "unresolved": [],
  "validation": [
    "最终 impacted preflight 13/13 通过，包含 Python 定向检查、前端全量 Vitest、lint、UI 合同、生产构建及首屏体积检查（244412/245760 bytes）。",
    "桌面与手机 Agent 接入端到端场景通过；410px 实页确认状态、刷新及三个操作紧凑排列，无横向溢出；本地 /agents 返回 200。"
  ]
}
```

```json
{
  "control_topics": [
    "ui",
    "verification"
  ],
  "recorded_on": "2026-09-17",
  "result": "在现有 codex/agents-connection-ui-20260916 分支将空对话的简单查询升级为三类可编辑进阶分析任务，并以设计系统响应式任务卡展示；专题与已选内容也使用证据导向的完整提问。同步 UI 合同、手册与更新日志，未提交或部署。",
  "status": "completed",
  "task_id": "agent-advanced-suggestions-20260917",
  "unresolved": [],
  "validation": [
    "类型检查、UI 合同、相关 Vitest 13 项与生产构建通过；桌面和手机端 Agent 快捷入口浏览器用例 14 项通过、2 项按原有条件跳过。",
    "462px 和桌面实页已检查任务卡布局；点击只填入草稿、不发送。最终 impacted preflight 13/13 命令通过；本地 /agent 预览 HTTP 200。"
  ]
}
```

```json
{
  "control_topics": [
    "ui",
    "verification"
  ],
  "recorded_on": "2026-09-17",
  "result": "在现有 codex/agents-connection-ui-20260916 分支为 Agent 助手回复加入按需加载的安全 Markdown 排版，支持标题、列表、强调、代码和表格；仅允许 HTTP(S) 外链，原始 HTML 和远程图片不执行或加载。同步 UI 合同、手册和更新日志，未提交或部署。",
  "status": "completed",
  "task_id": "agent-markdown-replies-20260917",
  "unresolved": [],
  "validation": [
    "类型检查、UI 合同、Lint、相关 Vitest 13 项与生产构建通过，初始 JS Brotli 245345/245760 bytes。",
    "桌面与手机端 Markdown 浏览器用例 2 项通过，包含长表格、长代码、无横向溢出及 Axe；最终 impacted preflight 13/13 命令通过，控制面结构检查通过，/agent 本地预览 HTTP 200。"
  ]
}
```

```json
{
  "control_topics": [
    "ui",
    "verification"
  ],
  "recorded_on": "2026-09-17",
  "result": "在当前分支将完整 Agent 进阶建议改为透视叠放卡片，加入渐变、纹理、侧卡预览、按钮/方向键/滑动切换；当前卡片仅填入问题。组件按需加载，同步组件合同、路由说明、决策、手册和更新日志，未提交或部署。",
  "status": "completed",
  "task_id": "agent-spatial-suggestions-20260917",
  "unresolved": [],
  "validation": [
    "类型检查、相关 Vitest 11 项通过；桌面及手机浏览器检查 4 项通过，涵盖切换、滑动、填入不发送、无横向溢出和 Axe。",
    "已查看桌面/手机截图并确认本地 5173 实际页面显示新效果。",
    "最终 impacted preflight 13/13 通过（.test-results/20260917T080318Z-7573），生产首屏 JS Brotli 245337/245760 bytes。"
  ]
}
```

```json
{
  "control_topics": [
    "ui",
    "verification"
  ],
  "recorded_on": "2026-09-17",
  "result": "对照用户录屏与 HeroUI Pro 公共页面，在当前分支将 Agent 进阶建议改为纵向透视卡片：更明显的侧卡层次、动态光影与投影、4.5 秒自动轮换；悬停或聚焦暂停，保留手动切换与填入问题行为。同步 UI 合同、手册和更新日志，未提交或部署。",
  "status": "completed",
  "task_id": "agent-spatial-refine-20260917",
  "unresolved": [],
  "validation": [
    "类型检查、UI 合同、生产构建通过，初始 JS Brotli 245333/245760 bytes。",
    "桌面和手机专项浏览器检查 5 项通过、1 项按设备条件跳过；覆盖自动轮换、悬停暂停及交互。",
    "最终 impacted preflight 11/11 命令通过（.test-results/20260917T094027Z-9124）。"
  ]
}
```

```json
{
  "control_topics": [
    "ui",
    "verification"
  ],
  "recorded_on": "2026-09-17",
  "result": "细化当前分支 Agent 建议卡片：保留 3D 层级与指针倾斜，缩小卡片并移除右下硬黑边；三种独立细线底纹仅受光时显现，紫灰、青绿和暖金底色保持独立；背景光限制色强和范围并消除底部直线边界。侧卡切换、正面卡填入建议，自动轮换保留。同步组件合同与更新日志，未提交或部署。",
  "status": "completed",
  "task_id": "agent-card-light-depth-20260917",
  "unresolved": [],
  "validation": [
    "完整 impacted preflight 11/11 通过（.test-results/20260917T100442Z-13413），生产首屏 JS Brotli 245499/245760 bytes。",
    "桌面/手机交互浏览器测试 5 项通过、1 项按设备跳过；新增无光隐藏、移入显纹、移出隐藏检查 1 项通过，已查看受光截图和本地手机页面。",
    "最后光晕范围调整后的生产构建通过，Markdown 控制和 E2E 合同补查通过。"
  ]
}
```

```json
{
  "control_topics": [
    "ui",
    "verification"
  ],
  "recorded_on": "2026-09-17",
  "result": "移除 Agent 建议卡片底部上一项、页码与下一项栏，保留读屏播报；修复透明 3D 容器拦截侧卡点击，点击露出侧卡切换，正面卡填入建议。同步 UI 合同、手册与更新日志，未提交或部署。",
  "status": "completed",
  "task_id": "agent-direct-card-navigation-20260917",
  "unresolved": [],
  "validation": [
    "impacted preflight 11/11 通过（.test-results/20260917T102828Z-15836）。",
    "修复透明容器后，桌面与手机侧卡点击、键盘及滑动浏览器测试 4/4 通过；本地页面点击露出的侧卡已确认切换且不改草稿。"
  ]
}
```
