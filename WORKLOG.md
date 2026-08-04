# WORKLOG

<!-- init-pro:compact-worklog schema=1 -->

Entries are maintained by `worklogctl.py`; read-only and no-op tasks are not logged.


```json
{
  "control_topics": [],
  "recorded_on": "2026-08-03",
  "result": "在生产环境确认管理员所选全局 DeepSeek 配置 ready 后，通过 ActorOps 服务层 CAS 开启 Discovery；配置 generation 从 2 热更新为 3。",
  "status": "completed",
  "task_id": "2026-08-03-enable-production-actor-discovery",
  "unresolved": [],
  "validation": [
    "启用前 selected_key=true、global AI ready=true，provider=deepseek、model=deepseek-v4-flash",
    "启用后 enabled=true、generation=3，生产无需重启",
    "操作前后 Discovery Run 仍为 8，未创建支持检查、未调用 AI、未启动 Actor 或付费 Canary",
    "活跃 Fetch Job 为 0"
  ]
}
```

```json
{
  "control_topics": [],
  "recorded_on": "2026-08-03",
  "result": "将通用 ActorOps 与通知服务合并到本地 main，发布不可变 v2.2.1 标签和 GitHub Release，并用本地构建的 revision-locked linux/amd64 镜像完成 VPS 离线迁移与生产切换。",
  "status": "completed",
  "task_id": "2026-08-03-publish-and-deploy-v2.2.1",
  "unresolved": [],
  "validation": [
    "main 与 v2.2.1 GitHub Test Gate 均通过；标签门禁覆盖 backend-full、frontend-full、Linux UI E2E 和 release-smoke",
    "发布镜像 inteliscope-service:v2.2.1-3a8f9f425db0 为 linux/amd64，上传哈希一致，并先在隔离 staging 返回 2.2.1/3a8f9f425db0",
    "生产停机前无活跃 Fetch Job 或 Actor Attempt；0600 数据库/.env 回滚备份 integrity ok、foreign keys 0",
    "离线迁移 15–19 全部成功且各自生成 0600 备份；迁移前后 fetch_jobs=649、apify_actor_attempts=105，未产生 AI、Actor 或付费 Canary 调用",
    "VPS API/Worker 使用精确 v2.2.1 镜像且 healthy、restart=0、worker_status=ready；RSSHub healthy，scheduler/staging 容器为 0",
    "https://rb.jiefs.top/、/feed、live、ready 均为 200，未登录 ActorOps 管理 API 为 401，API/Worker 严重日志计数均为 0"
  ]
}
```

```json
{
  "control_topics": [
    "ui"
  ],
  "recorded_on": "2026-08-03",
  "result": "补齐 v2.2.1 Linux 移动端视觉基线修复的产品手册复核与 Changelog 说明，解除 GitHub impact 文档门禁。",
  "status": "partial",
  "task_id": "2026-08-03-complete-v2.2.1-product-doc-review",
  "unresolved": [
    "等待 GitHub Test Gate 通过后创建 v2.2.1 标签、GitHub Release 并部署 VPS"
  ],
  "validation": [
    "首个 GitHub CI 错误仅为两个产品文档源未随补丁提交复核",
    "ActorOps 运行、费用和审批契约未改变"
  ]
}
```


```json
{
  "control_topics": [],
  "recorded_on": "2026-08-03",
  "result": "将 Telegram 多渠道通知、v15/v16 迁移、统一通知服务交互与 fake-IP 精确网络策略从 codex/telegram-multichannel-notifications-20260730 fast-forward 合入本地 main。",
  "status": "completed",
  "task_id": "2026-08-03-merge-telegram-notifications-to-local-main",
  "unresolved": [
    "按用户要求只合入本地 main，未推送远端，也未重建 8080"
  ],
  "validation": [
    "fast-forward main: 308320b -> 536ae0d without conflicts",
    "product documentation gate passed for 27 product-code paths",
    "python scripts/test_gate.py run --mode full on merged main: 23/23 passed",
    "git diff --check passed"
  ]
}
```


```json
{
  "control_topics": [
    "decisions",
    "ui"
  ],
  "recorded_on": "2026-08-02",
  "result": "排查确认 Instagram 三槽保存失败源于两个 probationary 与一个 static_valid Revision 不满足 2+1；ActorOps 现于付费、三槽保存和来源级验证前显示可达性并阻断无效操作。",
  "status": "completed",
  "task_id": "2026-08-02-actorops-certification-flow-guard",
  "unresolved": [
    "当前 Instagram discovery cycle 只剩一次 Canary，至少还需三次全部成功，必须由管理员强制重新发现；本次未触发 AI、Actor Run 或费用",
    "分支未合并 main、未推送，也未发布 VPS"
  ],
  "validation": [
    "日志确认两次 Active Pool 写入均以 apify_actor_active_pool_uncertified 原子拒绝；最新四次 Route Canary 为两次成功、一次 300 秒超时和一次远端 failed",
    "ActorOps 前端测试 20/20、生产构建和完整 Test Gate 23/23 通过",
    "页面按槽位禁用未认证 Revision、提前阻断数学上无法完成的 Canary cycle，并在 Route 未激活时锁定来源级验证"
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
  "recorded_on": "2026-08-02",
  "result": "删除 ActorOps 手工 Revision 排槽；候选认证完成后由服务端确定性生成 2+1 主备方案，管理员只提交 generation 与独立确认短语使其生效。",
  "status": "completed",
  "task_id": "2026-08-02-actorops-server-recommended-activation",
  "unresolved": [
    "当前 Instagram 候选仍未达到两个 certified，需继续按现有规则逐次确认 Canary 或强制重新发现；本次未调用 AI、Apify Actor 或产生费用",
    "分支未合并 main、未推送，也未发布 VPS"
  ],
  "validation": [
    "后端 ActorOps/API 定向测试 44 passed；前端 ActorOps 21 passed，生产构建通过",
    "完整 Test Gate 23/23 passed",
    "8080 API/Worker 从当前任务提交重建并 healthy，worker_status=ready，scheduler containers=0；真实 Instagram Route 显示 0/2 已认证、3/3 不同 Actor、2/2 发布者，且不再出现 Revision 下拉或手工保存按钮"
  ]
}
```

```json
{
  "control_topics": [
    "capabilities",
    "decisions",
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-02",
  "result": "ActorOps 保持完整 2+1 优先，同时允许两个不同发布者、均已成功 Canary 的固定 Build 先以 2/3 降级主备上线；第三槽空缺且不运行、不产生费用。",
  "status": "completed",
  "task_id": "2026-08-02-actorops-expedited-two-actor-activation",
  "unresolved": [
    "新建具体 Instagram 来源后仍需按当前两个活动 Actor 依次完成来源级 2/2 Canary；本次实现与重建未调用 AI、Actor 或产生费用",
    "第三槽后续按 generation 热补位；分支未合并 main、未推送，也未发布 VPS"
  ],
  "validation": [
    "真实数据库只读核对：fetch_cat 与 alwaysprimedev 各有成功 Canary；超时的 krazee_kaushik 未进入推荐",
    "Backend targeted 50 passed；Frontend ActorOps 21 passed；Changelog 5 passed；production build passed",
    "Full Test Gate 23/23 passed",
    "8080 已运行提交 fe56d9f，API/Worker healthy、worker_status=ready、scheduler=0；真实 Instagram Route generation 2 已为 ready，两个 probationary Actor 来自不同发布者，第三槽为空"
  ]
}
```

```json
{
  "control_topics": [
    "capabilities",
    "decisions",
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-02",
  "result": "修正 YouTube Channel Items 候选判定与审批可达性：频道资料/统计与频道自身 ID/URL 不再冒充视频内容，固定 Build 的永久输出失败停止重复付费，剩余次数按两个不同发布者的快速主备计算。",
  "status": "partial",
  "task_id": "2026-08-02-youtube-actor-items-capability-gate",
  "unresolved": [
    "真实 Route 仍需对剩余 streamers 与 apidojo 两个不同发布者的候选各执行一次管理员确认的付费 Canary；本次未调用 AI、Actor 或产生费用",
    "分支未合并 main、未推送，也未发布 VPS"
  ],
  "validation": [
    "真实数据库只读重判五个 YouTube 候选：三个以历史 metadata-only 或静态 item identity 冲突阻断，仅保留 streamers 与 apidojo 两个不同发布者候选",
    "Backend targeted 70 passed；Frontend ActorOps 22 passed（含 3 个阻断候选、2 个有效候选仍显示两个付费入口）；Python compile、TypeScript typecheck 与 git diff check 通过",
    "Full Test Gate 23/23 passed in 193.596 seconds"
  ]
}
```

```json
{
  "control_topics": [
    "capabilities",
    "decisions",
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-02",
  "result": "ActorOps Route 认证改为一次管理员审批的服务端串行批次：每个候选付费前免费复核公开 Actor 与精确 Build，两位不同发布者成功即停，未启动项为零费用，候选不足自动创建不启动 Actor 的补位发现任务；批准上限与实际费用分账。",
  "status": "completed",
  "task_id": "2026-08-02-actorops-serial-canary-batches",
  "unresolved": [
    "真实 Route batch Canary 与后续生产激活仍需管理员分别确认；本次实现、测试和迁移未调用真实 AI、Store 或 Actor，也未产生新费用",
    "分支不合并 main、不推送，也不发布 VPS"
  ],
  "validation": [
    "ActorOps/Apify 定向后端 260+ 项、批次 Worker/API/迁移 32 项、前端 ActorOps 22 项及 Changelog 5 项通过",
    "Full Test Gate 23/23 passed；observability contract、TypeScript typecheck、JSON 与 diff checks 通过",
    "global migration 19 以 0600 SQLite backup 成功 apply，integrity/FK 通过；修复 3 条 proven-no-start 为 $0、对账 16 条真实终态费用，迁移前后 X Candidate/attempt/实际费用保持一致"
  ]
}
```

```json
{
  "control_topics": [
    "capabilities",
    "decisions",
    "architecture"
  ],
  "recorded_on": "2026-08-03",
  "result": "修复 YouTube Actor Discovery 与 Canary 计划的控制面误杀：channelIds 使用真实 UC ID，Manifest 从 Dataset row 根映射并安全去除可证明不存在的模型包装，精确视频 Schema 可覆盖模糊定价事件，重复 Discovery Job 幂等结束。",
  "status": "completed",
  "task_id": "2026-08-03-youtube-actor-schema-recovery",
  "unresolved": [
    "真实 Route 批量 Canary（最多 $0.06，两个不同发布者成功即停）与生产激活仍必须分别由管理员确认；本轮未启动 Actor 或产生 Canary 费用",
    "分支不合并 main、不推送，也不发布 VPS"
  ],
  "validation": [
    "只读复核五个既有 YouTube Dataset 的无值字段路径/类型，确认 maximedupre Build 具备 videoId、videoUrl、videoPublishedAt 和视频正文，旧 Manifest 的 /candidate 前缀为误判根因",
    "免费读取当前 Actor/Build 元数据，五个已知候选均通过修复后的确定性筛选，ninhothedev channelIds 已绑定 target.native_id",
    "真实 Store/全局 AI Discovery 一次成功：5 个 static_valid Revision、5 个发布者，AI JSON/Manifest 均 valid；未启动 Actor，实际 Canary 费用 $0",
    "修复后的付费计划为 ready，包含已实证返回视频内容的 maximedupre，最多批准 $0.06；定向后端 80 项及 Full Test Gate 23/23 passed"
  ]
}
```

```json
{
  "control_topics": [
    "capabilities",
    "architecture"
  ],
  "recorded_on": "2026-08-03",
  "result": "在管理员明确批准本轮 YouTube Canary 总上限 $0.06 后执行服务端串行批次；maximedupre 与 khadinakbar 两个不同发布者均返回 valid_nonempty，Route 已达到两路快速主备激活条件。",
  "status": "partial",
  "task_id": "2026-08-03-youtube-canary-two-provider-ready",
  "unresolved": [
    "生产 Active Pool 仍需管理员独立确认“确认启用 Actor 主备”；确认前 YouTube Actor Route 不参与运行",
    "第三槽保持空缺且不运行、不产生费用，后续可按 generation 热补位；分支不合并 main、不推送，也不发布 VPS"
  ],
  "validation": [
    "已有 maximedupre Build 0.0.10 成功 Route Canary，valid_nonempty、费用 $0.001；本轮 khadinakbar Build 1.4.5 成功，valid_nonempty、费用 $0.00005",
    "本轮批次批准上限 $0.06、实际终结费用 $0.00015，两个不同 Actor/发布者成功后进入 activation_ready；失败候选未进入推荐池",
    "服务端推荐为 expedited_2of3：Primary maximedupre、Backup 1 khadinakbar、Backup 2 空缺，runnable_actor_count=2、publisher_count=2"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "capabilities",
    "decisions",
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-03",
  "result": "由本地 main 作为唯一集成 owner 合入 ActorOps 任务分支，保留 Telegram 通知 logical v15/v16，并将 ActorOps logical v15/v16/v17 固定到全局 migration 17/18/19；API、Worker、初始化、发布脚本、控制文件与前端时间线均完成组合冲突处理。",
  "status": "partial",
  "task_id": "2026-08-03-integrate-actorops-into-local-main",
  "unresolved": [
    "v2.2.0 版本提交、Tag、GitHub 发布与 VPS 迁移部署尚待本任务后续步骤完成",
    "VPS 发布只部署代码与安全迁移，不自动执行真实 AI、付费 Canary 或生产 Route 激活"
  ],
  "validation": [
    "通知与 ActorOps 迁移/API/Worker/运行脚本定向后端回归通过",
    "ActorOps 与 Changelog 冲突前端回归 27/27 通过；App 全文件连续三次 297/297 通过",
    "python scripts/test_gate.py run --mode full: 23/23 passed in 214.465 seconds",
    "worklog validator、JSON、git diff check 与 observability contract 通过"
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
  "control_topics": [
    "architecture",
    "decisions",
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-03",
  "result": "将 Settings 从 Feed Sidebar 中拆分为带返回按钮、独立侧栏与内容区的 Settings Workspace；首批迁移概览、外观和通知，并保留未迁移设置的兼容入口与原业务逻辑。",
  "status": "completed",
  "task_id": "2026-08-03-refactor-settings-workspace-ui",
  "unresolved": [],
  "validation": [
    "前端 Vitest 64 文件、561 项通过；typecheck、UI contract、lint（0 error）与生产构建通过",
    "Playwright 覆盖移动 Drawer、390/768/1024/1440 响应式、浅深主题与严重/关键 Axe 违规为 0",
    "VITEST_MAX_WORKERS=4 python scripts/test_gate.py run --mode full：23/23 passed in 225.425 seconds"
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
  "recorded_on": "2026-08-03",
  "result": "Settings Workspace 第二阶段将 AI 与已忽略内容迁入原生路由；Legacy 仅保留获取、存储和密钥，并保持 API、缓存、权限、保存 payload 与 write-only 语义不变。",
  "status": "completed",
  "task_id": "2026-08-03-settings-intelligence-native-ui",
  "unresolved": [
    "分支按任务边界保持未合并、未推送"
  ],
  "validation": [
    "新增 AI payload/diff 与折叠草稿保留单测；应用级回归覆盖旧 hash、只读零请求、AI/触底保存、已忽略内容恢复和高级设置桥接",
    "Playwright 通过桌面原生 AI/ignored/hash/请求惰性、390/768/1024/1440、浅深主题与 Axe，以及移动 Drawer 验收",
    "VITEST_MAX_WORKERS=4 python scripts/test_gate.py run --mode full：23/23 passed in 333.669 seconds"
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
  "result": "将 Owner/Admin 密钥管理迁入原生 Settings Workspace：新增 /settings/secrets、导航和旧 hash 兼容，迁移 AI Key 与 Apify 池操作，Legacy 只保留获取/主题和存储/归档。",
  "status": "completed",
  "task_id": "2026-08-04-settings-secrets-native-workspace",
  "unresolved": [],
  "validation": [
    "完整 Test Gate full 23/23 通过（Python、Compose、legacy、React contract/lint/typecheck/Vitest/build）",
    "前端 Vitest 567/567 通过；生产构建包含独立 SettingsSecretsPage 懒加载 chunk",
    "Member/Viewer 直达密钥页不请求 secrets、quota 或 Apify pool；旧 /settings/legacy#settings-secrets 重定向",
    "未修改 API、数据库、SecretStore 格式或 Query key"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "decisions",
    "ui"
  ],
  "recorded_on": "2026-08-04",
  "result": "将 RSSHub、获取窗口和阅读主题库迁入原生 Settings Workspace；Legacy Settings 收缩为 ActorOps 与存储归档，并保留独立/原子保存、旧 hash 重定向、角色过滤和缓存失效语义。",
  "status": "completed",
  "task_id": "2026-08-04-settings-fetching-native-workspace",
  "unresolved": [
    "ActorOps 原生化与存储归档原生化按后续阶段继续；本阶段未改后端接口、数据库或获取业务规则。"
  ],
  "validation": [
    "前端 TypeScript、构建、UI 合同及 36 项 Playwright 浏览器回归通过（12 项按项目策略跳过）",
    "python3 scripts/test_gate.py run --mode full：23/23 通过",
    "当前工作树 ./scripts/up-latest.sh 已待提交后执行"
  ]
}
```
