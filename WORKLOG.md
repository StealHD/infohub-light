# WORKLOG

<!-- init-pro:compact-worklog schema=1 -->

Entries are maintained by `worklogctl.py`; read-only and no-op tasks are not logged.


```json
{
  "control_topics": [
    "architecture",
    "interface"
  ],
  "recorded_on": "2026-08-13",
  "result": "将 Worker lease heartbeat、终态/取消、retry、媒体与来源头像 savepoint/cleanup 拆入独立 lifecycle 和 media publication 模块，使 Worker façade 达到项目硬上限。",
  "status": "completed",
  "task_id": "2026-08-13-code-health-worker-lifecycle",
  "unresolved": [],
  "validation": [
    "Worker、lease、Feed/outbox、Actor validation/Canary、media/avatar、Source Health、通知与调度扩展定向回归全部通过，ResourceWarning 为 0。",
    "worker.py 由 992 行降至 676 行并移除文件旧债，run_worker_once 为 154 行；新模块 357/148 行，最大函数 68/48 行。",
    "受影响 preflight 16/16 与完整 Test Gate 18/18 通过，mapping miss 为 false，前端 typecheck、lint 和 UI contract 通过。"
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
  "recorded_on": "2026-08-13",
  "result": "将通知服务、目标和个人通知设置的 13 个 HTTP 适配器从 FastAPI composition root 抽到独立模块；接口、路由顺序、OpenAPI、鉴权、迁移门槛与存储语义保持不变，server.py 旧债同步收紧。",
  "status": "completed",
  "task_id": "2026-08-13-code-health-notification-routes",
  "unresolved": [
    "总代码健康 Goal 尚未完成；后续继续小步拆分 transport/secrets、Catalog、ActorOps API、ServiceStore 与 ApifyActorOpsService。"
  ],
  "validation": [
    "全 API 路由、通知路由与 OpenAPI 规范 SHA 均与 c9a1519 基线一致；通知、权限、操作日志、API lifespan 与 React 服务定向回归通过。",
    "staged preflight 16/16 与完整 Test Gate 18/18 通过，SQLite 未关闭连接警告 0；首屏 JavaScript Brotli 235447 bytes。"
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
  "recorded_on": "2026-08-13",
  "result": "将工作区 Email 与 Telegram 通知 transport 的 8 个兼容 HTTP 适配器从 FastAPI composition root 抽到独立模块；接口、路由顺序、OpenAPI、鉴权、迁移门槛与 SecretStore/发送语义保持不变。",
  "status": "completed",
  "task_id": "2026-08-13-code-health-notification-transports",
  "unresolved": [
    "总代码健康 Goal 尚未完成；后续继续小步拆分 secrets/key-pool、Catalog、ActorOps API、ServiceStore 与 ApifyActorOpsService。"
  ],
  "validation": [
    "全 API 路由、transport 路由与 OpenAPI 规范 SHA 均与 7cde2e6 基线一致；通知 transport、权限、操作日志与 lifespan 定向回归 78/78 通过。",
    "staged preflight 16/16 与完整 Test Gate 18/18 通过，SQLite 未关闭连接警告 0；首屏 JavaScript Brotli 235443 bytes。"
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
  "recorded_on": "2026-08-13",
  "result": "将 Apify Key Pool 的 4 个 HTTP 适配器从 FastAPI composition root 抽到独立模块；接口、路由顺序、OpenAPI、鉴权、migration gate、generation/CAS、drain 与 resilience event 语义保持不变。",
  "status": "completed",
  "task_id": "2026-08-13-code-health-key-pool-routes",
  "unresolved": [
    "总代码健康 Goal 尚未完成；后续继续小步拆分 secrets、Catalog、ActorOps API、ServiceStore 与 ApifyActorOpsService。"
  ],
  "validation": [
    "全 API 路由、Key Pool 路由与 OpenAPI 规范 SHA 均与 4e529f4 基线一致；Key Pool、resilience、权限、操作日志与 lifespan 定向回归 46/46 通过。",
    "staged preflight 16/16 与完整 Test Gate 18/18 通过，SQLite 未关闭连接警告 0；首屏 JavaScript Brotli 235453 bytes。"
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
  "recorded_on": "2026-08-13",
  "result": "将 SecretStore 列表、创建、轮换、连接、额度与删除的 6 个 HTTP 适配器从 FastAPI composition root 抽到独立模块；全局路由顺序、OpenAPI、权限、配置同步、Key Pool/drain、quota 与 source-health 语义保持不变。",
  "status": "completed",
  "task_id": "2026-08-13-code-health-secret-routes",
  "unresolved": [
    "总代码健康 Goal 尚未完成；后续继续小步拆分 Catalog、ActorOps API、ServiceStore 与 ApifyActorOpsService。"
  ],
  "validation": [
    "全 API 路由与 OpenAPI 规范 SHA 均与 f7cb6ac 基线一致；Secrets、Key Pool、ActorOps、quota、权限、操作日志与 lifespan 定向回归 71/71 通过。",
    "staged preflight 16/16 与完整 Test Gate 18/18 通过，SQLite 未关闭连接警告 0；首屏 JavaScript Brotli 235451 bytes。"
  ]
}
```

```json
{
  "commit": "fd67ef7",
  "control_topics": [
    "architecture",
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-13",
  "result": "将来源类型与 Actor 管理能力清单的 2 个只读 Catalog HTTP 适配器从 FastAPI composition root 抽到独立模块；路由顺序、OpenAPI、权限、可用性与安全投影语义保持不变。",
  "status": "completed",
  "task_id": "2026-08-13-code-health-catalog-metadata-routes",
  "unresolved": [
    "总代码健康 Goal 尚未完成；后续继续分片拆分 Catalog 写路径、ActorOps API、ServiceStore 与 ApifyActorOpsService。"
  ],
  "validation": [
    "全 API 路由、2 个 Catalog 路由与 OpenAPI 规范 SHA 均与 3ad639f 基线一致；Catalog、ActorOps、Key Pool、权限、操作日志、lifespan 与 import boundary 定向回归通过。",
    "server.py 由 7259 行降至 7179 行，create_app 由 6277 行降至 6197 行；新模块 100 行。",
    "staged preflight 16/16 与完整 Test Gate 18/18 通过，SQLite 未关闭连接警告 0；首屏 JavaScript Brotli 235509 bytes。"
  ]
}
```

```json
{
  "commit": "5250ae3",
  "control_topics": [
    "architecture",
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-13",
  "result": "将 Catalog 来源列表、使用量、共享、软删除、订阅和取消订阅的 6 个 HTTP 适配器拆到独立模块；接口、路由顺序、权限、跨用户隐藏、事务与操作日志语义保持不变。",
  "status": "completed",
  "task_id": "2026-08-13-code-health-catalog-membership-routes",
  "unresolved": [
    "总代码健康 Goal 尚未完成；Catalog create/patch 与 ActorOps API 保持原位，后续先下沉验证和计划边界再拆。"
  ],
  "validation": [
    "全 API 路由、Catalog 路由与 OpenAPI 规范 SHA 均与 0ec7740 基线一致；Catalog、SubscriptionMutation、权限、操作日志、lifespan 与 import boundary 定向回归 182/182 通过。",
    "server.py 由 7179 行降至 7074 行，create_app 由 6197 行降至 6094 行；新模块 198 行且所有新函数符合硬上限。",
    "staged preflight 16/16 与完整 Test Gate 18/18 通过，SQLite 未关闭连接警告 0；首屏 JavaScript Brotli 235482 bytes。"
  ]
}
```

```json
{
  "commit": "4f8ec2e",
  "control_topics": [
    "architecture",
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-13",
  "result": "将 Apify Actor 告警设置、测试发送与 incident 的 4 个 HTTP 适配器拆到独立模块；接口、路由顺序、权限、迁移门槛、threadpool 发送时机与安全投影保持不变。",
  "status": "completed",
  "task_id": "2026-08-13-code-health-actor-alert-routes",
  "unresolved": [
    "总代码健康 Goal 尚未完成；ActorOps 控制路由、Catalog create/patch、ServiceStore 与 ApifyActorOpsService 继续按独立高风险阶段处理。"
  ],
  "validation": [
    "全 API 路由、4 个 Actor 告警路由与 OpenAPI 规范 SHA 均与 0d11426 基线一致；告警、通知多渠道、权限、操作日志、lifespan 与 import boundary 定向回归 77/77 通过。",
    "server.py 由 7074 行降至 6915 行，create_app 由 6094 行降至 5974 行；新模块 188 行且所有新函数符合硬上限。",
    "staged preflight 16/16 与完整 Test Gate 18/18 通过，SQLite 未关闭连接警告 0；首屏 JavaScript Brotli 235519 bytes。"
  ]
}
```

```json
{
  "commit": "4727531",
  "control_topics": [
    "architecture",
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-13",
  "result": "将 ActorOps Route 与 Revision 的安全公共投影拆到独立纯模块；字段、价格过滤、运行状态、Canary 与激活资格保持不变，模块不含 SQL、远端调用、审批或写操作。",
  "status": "completed",
  "task_id": "2026-08-13-code-health-actorops-public-projection",
  "unresolved": [
    "总代码健康 Goal 尚未完成；public_actor_ops_detail 的 SQL/来源校验与 ActorOps 控制路由仍需先分层后拆，不能机械迁移。"
  ],
  "validation": [
    "全 API 路由与 OpenAPI 规范 SHA 均与 8254a72 基线一致；ActorOps API/service、compatibility、权限、操作日志、lifespan 与 import boundary 定向回归 108/108 通过。",
    "server.py 由 6915 行降至 6733 行，create_app 由 5974 行降至 5792 行；新纯投影模块 188 行且最大函数低于 80 行。",
    "staged preflight 16/16 与完整 Test Gate 18/18 通过，SQLite 未关闭连接警告 0；首屏 JavaScript Brotli 235572 bytes。"
  ]
}
```

```json
{
  "commit": "960514b",
  "control_topics": [
    "architecture",
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-13",
  "result": "将 6 个 ActorOps 只读 route、pool、新鲜度与事件查询 HTTP 适配拆到独立模块；路由顺序、OpenAPI、权限、字段和缓存语义保持不变。",
  "status": "completed",
  "task_id": "2026-08-13-code-health-actorops-read-routes",
  "unresolved": [
    "总代码健康 Goal 尚未完成；public_actor_ops_detail、ActorOps 写路由、Catalog create/patch、ServiceStore 与 ApifyActorOpsService 仍需按独立高风险阶段处理。"
  ],
  "validation": [
    "全 API 140 条路由顺序/方法/名称与完整 OpenAPI 哈希均与 75a4748 基线一致；ActorOps、兼容、权限、操作日志、lifespan、import boundary 与代码规模定向回归 96/96 通过。",
    "server.py 由 6733 行降至 6641 行，create_app 由 5792 行降至 5695 行；新只读适配模块 170 行且所有新函数低于 80 行。",
    "staged preflight 16/16 与完整 Test Gate 18/18 通过，SQLite 未关闭连接警告 0；首屏 JavaScript Brotli 235543 bytes。"
  ]
}
```

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
