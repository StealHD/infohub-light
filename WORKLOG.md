# WORKLOG

<!-- init-pro:compact-worklog schema=1 -->

Entries are maintained by `worklogctl.py`; read-only and no-op tasks are not logged.


```json
{
  "commit": "17254a3",
  "control_topics": [
    "architecture",
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-13",
  "result": "将 ActorOps Canary plan/batch 的纯公共投影与两个 GET 查询适配拆到既有安全模块；选择、审批、费用、批次创建和激活写路径保持原位不变。",
  "status": "completed",
  "task_id": "2026-08-13-code-health-actorops-canary-reads",
  "unresolved": [
    "总代码健康 Goal 尚未完成；Discovery/public_actor_ops_detail 读模型、ActorOps 写路由、Catalog create/patch、ServiceStore 与 ApifyActorOpsService 仍需按独立高风险阶段处理。"
  ],
  "validation": [
    "全 API 140 条路由顺序/方法/名称与完整 OpenAPI 哈希均与 530181e 基线一致；ActorOps、权限、操作日志、lifespan、observability 与 import boundary 定向回归 57/57 通过。",
    "server.py 由 6641 行降至 6517 行，create_app 由 5695 行降至 5564 行；投影与只读适配模块分别为 295 与 226 行，新增函数均低于 80 行。",
    "staged preflight 16/16 与完整 Test Gate 18/18 通过，SQLite 未关闭连接警告 0；首屏 JavaScript Brotli 235398 bytes。"
  ]
}
```

```json
{
  "commit": "9a9f1fa",
  "control_topics": [
    "architecture",
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-13",
  "result": "将用户订阅 list/create/patch/delete、source-health 与两个请求模型完整拆到独立 HTTP 适配模块；通知约束、viewer 权限、停用处置、schedule 投影和用户隔离保持不变。",
  "status": "completed",
  "task_id": "2026-08-13-code-health-subscription-routes",
  "unresolved": [
    "按用户要求本轮在完整测试后结束；server.py 剩余 ActorOps/Catalog 写路径、ServiceStore、ApifyActorOpsService 与依赖环留待后续独立任务。"
  ],
  "validation": [
    "全 API 140 条路由顺序/方法/名称与完整 OpenAPI 哈希均与 8e9a3c8 基线一致；订阅/API/source-health/schedule/权限/操作日志/lifespan/边界九组定向测试通过。",
    "server.py 由 6517 行降至 6330 行，create_app 由 5564 行降至 5402 行；新 subscription_routes.py 258 行，最大 handler 73 行。",
    "staged preflight 16/16 与完整 Test Gate 18/18 通过，SQLite 未关闭连接警告 0；首屏 JavaScript Brotli 235505 bytes。"
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
  "recorded_on": "2026-08-13",
  "result": "完成信息流真实卡片骨架、收藏即时同步、可访问的展开提示及受角色限域、可安全停止的手动刷新链路；服务端不信任客户端刷新范围，取消请求在 Worker 安全边界阻断后续副作用。",
  "status": "completed",
  "task_id": "2026-08-13-feed-refresh-polish",
  "unresolved": [],
  "validation": [
    "新增角色范围、无订阅、取消与发布原子性后端覆盖，以及收藏、星标、溢出检测、骨架和按钮状态前端覆盖。",
    "Feed Playwright 已覆盖 desktop/tablet/mobile 的骨架、收藏即时可见、刷新停止与布局锚点；预检 16/16 通过。",
    "完整 Test Gate 18/18 通过（全量 Python、前端 lint/typecheck/Vitest/build、Compose 与控制面检查）。"
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
  "recorded_on": "2026-08-14",
  "result": "修正 ActorOps 槽位替换工作流的服务端 operation_slot 投影与前端标题/请求一致性，抽出阶段读取和工作流模块；补齐实际收费超授权后的终结对账，且将身份不匹配的固定 Build 记为不可再选。Docker 构建基础镜像改用可达的 Quay/Microsoft 源。",
  "status": "completed",
  "task_id": "2026-08-14-actorops-pool-workflow-cost-guard",
  "unresolved": [
    "X 的现有外部候选均未通过身份/契约安全验证，因此保持活动主备不变；等待新的安全候选或其 Build 证据变化后才能完成真实替换。"
  ],
  "validation": [
    "ActorOps 定向 Pytest、前端定向 Vitest、typecheck、lint 和 production build 通过。",
    "完整 Test Gate 18/18 通过，mapping miss 为 false。",
    "本地 8080 已验证槽位替换路径和候选 Modal 使用主用槽；真实验证的身份不匹配候选已被后续列表禁用。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "interface"
  ],
  "recorded_on": "2026-08-14",
  "result": "补齐所有 Actor 路线的主备池手动主用切换、未来单次费用上限与安全候选质量排序；X 的 route identity 透传与严格免费预检保持付费验证前的零写入拒绝。",
  "status": "completed",
  "task_id": "2026-08-14-actorops-pool-management-controls",
  "unresolved": [],
  "validation": [
    "定向后端回归、ActorOps 前端交互、lint 与 typecheck 通过。",
    "preflight 16/16 与完整 Test Gate 18/18 通过；无 mapping miss。",
    "本地 8080 已切换到 5f6853cd1ee4，API/Worker healthy，worker_status=ready；新 promote/price-cap 路由和 ActorOps 前端产物已确认。",
    "本轮部署和验证没有发起付费 Actor Run。"
  ]
}
```

```json
{
  "control_topics": [
    "interface"
  ],
  "recorded_on": "2026-08-14",
  "result": "修复 ActorOps 免费 Discovery 在候选含公开评分时写入不可变 Revision 引发的 AttributeError；评分/评分人数/使用人数改为同固定 Build 的静态证据一次冻结，并让旧池检查尊重管理员已保存的 Route 单次费用上限。",
  "status": "completed",
  "task_id": "2026-08-14-actorops-discovery-quality-free-refresh",
  "unresolved": [],
  "validation": [
    "Actor candidate-quality 与 discovery 定向回归 56/56 通过。",
    "完整 Test Gate preflight 16/16 通过，含 Python 全集、前端 lint/typecheck/Vitest/build、产品文档与代码规模门禁。",
    "Discovery 主文件由 2373 行降至 2362 行，run_discovery 由 756 行降至 743 行；未增加历史单体文件。"
  ]
}
```

```json
{
  "control_topics": [
    "interface"
  ],
  "recorded_on": "2026-08-14",
  "result": "修正 ActorOps 单槽新增/替换的候选发现：这类操作只在免费静态安全检查后要求一名候选，完整池仍维持多发布者门槛；X、Instagram 与 YouTube 均保留同 Route 先前已通过静态检查的固定 Build，不会被后一次空搜索清空。兼容验证计划与候选展示统一使用管理员保存的 Route 上限，最高 $0.10。",
  "status": "completed",
  "task_id": "2026-08-14-actorops-single-slot-candidate-flow",
  "unresolved": [],
  "validation": [
    "ActorOps quality、discovery、兼容与主备池定向 Pytest 81/81 通过。",
    "完整 Test Gate preflight 16/16 通过（全量 Python、前端 lint/typecheck/Vitest/build、代码规模与文档门禁）。",
    "未启动付费 Actor Run；待部署后只执行一次免费 X 候选刷新验证。"
  ]
}
```

```json
{
  "control_topics": [
    "phase"
  ],
  "recorded_on": "2026-08-15",
  "result": "将包含 ActorOps 主备池管理、单槽安全候选保留与前端平面化调整的本地 main 准备为 v2.3.3；正式发布仅在精确 SHA 的 GitHub Test Gate 和 Release Tag smoke 均成功后才切换 VPS。",
  "status": "completed",
  "task_id": "2026-08-15-release-v2.3.3",
  "unresolved": [],
  "validation": [
    "v2.3.3 是在既有 v2.3.2 标签后的补丁版本；本地 main 已包含 ActorOps 完整门禁通过的精确功能提交。",
    "发布脚本会执行相对 v2.3.2 的预检、等待 main Test Gate、创建 tag、等待 tag API smoke，并在 VPS 仅 docker load 后验证 API、Worker 与前端 revision。"
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
  "result": "在 v2.3.3 发布门禁前拆分 ServiceStore 订阅查询、API 测试 fixture/手动刷新场景和 Workbench Playwright mock，并将卡片展示派生逻辑独立，恢复不可增长的代码规模债务上限。",
  "status": "completed",
  "task_id": "2026-08-15-release-v2.3.3-code-health-gate",
  "unresolved": [
    "需在推送后重跑精确 main 的 GitHub 完整 Test Gate，成功后才能创建 v2.3.3 tag 与 VPS 部署。"
  ],
  "validation": [
    "发布基线 b0083d38 的 code-size policy 对比通过，四个历史文件和两个 callable 的债务上限均未增加。",
    "手动 Feed 刷新定向 Pytest 5/5、前端 typecheck、lint、VirtualFeed Vitest 36/36 与 Playwright test list 通过。"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-15",
  "result": "修复 ActorOps 发布包 E2E 的端口耦合、移动端视觉基线，并隔离 Insights 手动面板几何测试与首次自动展示之间的竞态。",
  "status": "completed",
  "task_id": "2026-08-15-release-v2.3.3-e2e-stability",
  "unresolved": [],
  "validation": [
    "发布级 E2E 116 通过、55 按项目配置跳过；代码规模、控件与 diff 检查全部通过。",
    "ActorOps 跨 desktop/tablet/mobile 的新增、替换、移出流程在生产构建端口上通过。"
  ]
}
```

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
