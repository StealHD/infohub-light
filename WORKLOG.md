# WORKLOG

<!-- init-pro:compact-worklog schema=1 -->

Entries are maintained by `worklogctl.py`; read-only and no-op tasks are not logged.


```json
{
  "control_topics": [
    "decisions",
    "interface",
    "ui"
  ],
  "recorded_on": "2026-08-27",
  "result": "Closed the ActorOps validation gap by clearing stale maintenance assumptions and restoring the final full gate environment.",
  "status": "completed",
  "task_id": "2026-08-27-actorops-gate-closure",
  "unresolved": [],
  "validation": [
    "All ActorOps v2 backend tests passed 180 of 180",
    "Final full preflight passed 16 of 16",
    "Local API and Worker remain healthy"
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
  "recorded_on": "2026-08-27",
  "result": "完成 ActorOps 稳定控制环：统一候选故障与来源冷却、Binding 级健康、可恢复 Repair/Discovery/结算、默认安全维护、主备人工替换和 exact-Build 头像映射；补齐 global 33、构建源码摘要与发布护栏，并完成本地 32→33 迁移及新容器切换。",
  "status": "completed",
  "task_id": "2026-08-27-actorops-stability-control-loop",
  "unresolved": [],
  "validation": [
    "ActorOps 后端全域回归及迁移时序专项通过；前端定向 Vitest、TypeScript、ESLint 与生产构建通过。",
    "snapshot impacted preflight 17/17 通过，覆盖完整后端、前端、控制面、代码尺寸和隔离 Playwright E2E。",
    "本地 global 32/33 显式迁移均完成 0600 备份、integrity ok、foreign keys 0；API、Worker、前端及镜像 revision/source digest 健康验证通过。"
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
  "recorded_on": "2026-08-28",
  "result": "完成 ActorOps 本地稳定性闭环：exact Build 免费预检、validation 凭据隔离、四行溢出校验、故障主备人工替换、默认安全维护和历史 Dataset 无新增 Run 的头像补写；修复 Worker 异步上下文媒体落盘并切换最终本地容器。",
  "status": "completed",
  "task_id": "2026-08-28-actorops-real-data-stability-avatar",
  "unresolved": [
    "按项目完整 gate 最多重跑一次规则，修复两项旧测试假设后未执行第三次完整 preflight；定向受影响测试与静态门禁已全部通过。"
  ],
  "validation": [
    "ActorOps、媒体与来源头像定向 Pytest 196 项通过；前端 TypeScript、ESLint、前后端代码尺寸、控制文件与 diff 校验通过。",
    "本地真实验证 6 个 Apify Run 全部最终结算，替换费用 $0.0385112、正常抓取费用 $0.0209060；历史头像重放 Run 总数保持 1557 不变。",
    "Catalog 只投影登录保护的 /api/media 头像，认证访问 200、未认证 401、原始 URL 不泄露；最终 revision 0b0088690d60-dirty-5389507110d0 的 API 和 Worker healthy。"
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
  "recorded_on": "2026-08-28",
  "result": "将 Actor Replacement 的本地合同、目标指纹与 validation exact-Build 免费预检前移到计划创建前；confirmed 候选禁选，免费失败立即显示中文 Toast/Notice 与零费用说明，并建立宿主机新端口前后端快速验证流程。",
  "status": "completed",
  "task_id": "2026-08-28-actorops-replacement-free-preview-feedback",
  "unresolved": [
    "按用户要求未重建 canonical 8080 容器；当前容器保持停止，宿主机 18080 API 与 15173 Vite preview 正在运行。"
  ],
  "validation": [
    "ActorOps operator/API/Catalog/maintenance 定向 Pytest 70 项通过；替换回归证明失败前计划、Attempt、Run 与费用事实均为 0。",
    "ActorOps Drawer/Candidate/Route Vitest 12 项、TypeScript、ESLint、前后端代码尺寸及控制文件检查通过。",
    "真实数据库新端口 smoke 返回 confirmed_failure/build_unavailable 与 409 actorops_maintenance_revision_changed；计划 9、Attempt 334、Run 1564 前后不变，前端代理和后端 health 均为 200。"
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
  "recorded_on": "2026-08-28",
  "result": "修复 Replacement 免费预检漏捕 ActorManifestError 导致的 503，并把合同阻断细分为缺少原生目标 ID、handle、URL、Manifest 无效或输入模板不可渲染；真实 X 候选现返回可操作的零费用原因。",
  "status": "completed",
  "task_id": "2026-08-28-actorops-replacement-contract-detail",
  "unresolved": [
    "免费 Discovery 未找到新的可接受 X 候选；真正付费 Probe 仍需单独费用授权。",
    "按用户要求未重建 Docker 容器；当前使用宿主机 18080 API 与 15173 Vite 验证。"
  ],
  "validation": [
    "ActorOps operator/API 定向 Pytest 36 项及 Replacement Drawer Vitest 5 项通过；TypeScript、ESLint、全域代码尺寸与 Markdown 控制通过。",
    "真实 X Candidate 返回 409 actorops_replacement_target_native_id_missing，明确当前来源只有 handle/URL；计划 9、Attempt 334、Run 1564 前后不变。",
    "单次免费 Discovery 禁用 AI 与 Worker 后完成，accepted 0，Attempt/Run 保持不变。"
  ]
}
```

```json
{
  "control_topics": [
    "decisions",
    "interface"
  ],
  "recorded_on": "2026-08-28",
  "result": "扩展 X Discovery 的 exact-Build Schema 确定性映射，支持已声明的 handle/主页 URL、核心输出别名、头像字段与运行条数上限；真实免费 Discovery 生成两个 static_valid 候选，并成功创建零费用 Replacement preview。",
  "status": "completed",
  "task_id": "2026-08-28-actorops-x-schema-proven-mapping",
  "unresolved": [
    "替换计划保持 previewed；未获得本次付费 Probe 授权，因此未启动 Apify Run、未应用替换。"
  ],
  "validation": [
    "ActorOps Adapter、Operator controls 与 Discovery 定向 Pytest 共 54 项通过，backend code-size 通过。",
    "真实 X 免费 Discovery 将两个精确 Build 映射为 static_valid；低价候选 preview 返回 200。",
    "preview 前后 Attempt 保持 334、Apify Run 保持 1564；本地 API ready、Vite 与代理接口均返回 200。"
  ]
}
```

```json
{
  "control_topics": [
    "decisions",
    "interface"
  ],
  "recorded_on": "2026-08-28",
  "result": "用真实 X Replacement Probe 定位并修复确定性映射只按字段名、误把 author 对象当作 handle 的缺陷；多格式输出缺少可证明嵌套身份字段时现保持 mapping_pending，并为剩余结构明确候选创建新的零费用预览。",
  "status": "completed",
  "task_id": "2026-08-28-actorops-x-output-type-guard",
  "unresolved": [
    "新计划 replacement-5bbcf29a5ccc4b2badf8737bc4029ee4 保持 previewed；旧计划授权不继承，尚未授权新的付费 Probe。"
  ],
  "validation": [
    "ActorOps Adapter、Operator controls 与 Discovery 定向 Pytest 56 项通过，backend code-size 与 Markdown 控制检查通过。",
    "真实失败 Dataset 只读检查确认 /author 为对象，精确错误为 apify_actor_contract_mismatch；远端实测费用最终结算为 $0.0005。",
    "修复后免费 Discovery 将该多格式 Actor 保持 mapping_pending，另一个 exact Build 保持 static_valid；免费预览后 Attempt 与远端 Run 均未增加。"
  ]
}
```

```json
{
  "control_topics": [
    "interface"
  ],
  "recorded_on": "2026-08-28",
  "result": "修复 ActorOps X 候选抓取流程：合并多个能力查询后按 Actor 去重，以公开用户量、评分、评价数和收藏数选取前 12 个 exact Build；最终 rank 保持质量顺序，accepted、mapping_pending 和 rejected 均保留商城身份。",
  "status": "completed",
  "task_id": "2026-08-28-actorops-x-quality-discovery",
  "unresolved": [
    "本次只完成候选获取与可见性；高质量 mapping_pending Actor 的嵌套字段、查询模板和 Dataset 行结构将在下一步逐个比对，不启动付费 Probe。"
  ],
  "validation": [
    "ActorOps Catalog、Discovery、Worker、Adapter 与 API 定向 Pytest 全部通过。",
    "impacted preflight 14/14 命令通过，覆盖后端、前端 TypeScript/ESLint、控制文件、代码尺寸与 diff 检查。",
    "真实免费 X Discovery 完成并保存 12/12 商城资料；抓到 7.5 万用户 Tweet Scraper、3.25 万用户 Scraper Lite、Xquik、Advanced Search 等候选，新增 Apify Run 为 0。"
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
  "recorded_on": "2026-08-28",
  "result": "ActorOps 逐 exact Build 的 AI 字段映射新增必填输入语义校验、X 高级搜索 from:<handle> 编译、用户名与数字帖子 ID 派生标准 URL、DB exact-Schema 缓存及旧 pending 去重；真实 X Discovery 从 5 个可映射候选提升到 6 个。",
  "status": "completed",
  "task_id": "2026-08-28-actorops-exact-schema-ai-derived-x-mapping",
  "unresolved": [
    "新 static_valid 候选尚未执行有费用的 Replacement Probe；本次只证明公开 Schema 映射并写入缓存。"
  ],
  "validation": [
    "真实 X Discovery 完成：6 accepted、5 pending、1 rejected；新增 Apify Actor Run 为 0，误报缺作者的 scrape.badger 候选已以 /username 映射为 static_valid。",
    "ActorOps 受影响 Pytest 53 项通过，修正测试断言后失败 spec 单独重跑 1 项通过；前端 Vitest 10 项、TypeScript 与 ESLint 通过。",
    "backend/frontend code-size 与 git diff --check 通过；此前 impacted preflight 的唯一 code-size 失败已按项目规则修复并定向闭环。"
  ]
}
```

```json
{
  "control_topics": [
    "interface"
  ],
  "recorded_on": "2026-08-28",
  "result": "执行真实 X Replacement Probe 并逐字段审计：Actor 正确返回目标账号帖子，但 X/Twitter API v1 时间格式被系统误判为合同不兼容；解析器现支持该精确带时区格式，同一已结算 Dataset 零费用重放通过，并生成脱敏详细报告。",
  "status": "completed",
  "task_id": "2026-08-28-actorops-x-replacement-probe-timestamp-format",
  "unresolved": [
    "旧代码已将 Candidate/Plan 写入不可逆 rejected/failed 终态；需要新增不篡改历史费用事实的规则升级后 Dataset 重验与候选恢复流程，才能应用替换。",
    "Replacement Runner 仍把输出转换异常收敛为笼统 contract_mismatch，管理界面尚未直接显示具体字段和格式。"
  ],
  "validation": [
    "真实 Probe 仅启动 1 次 Actor Run，实际费用 $0.0999 已终结；第二个 Binding 未启动、未自动尝试其他候选、未应用替换。",
    "修复后只读重放同一 Dataset 得到 valid_nonempty，目标身份、帖子 ID、正文、时间和派生 URL 均通过。",
    "Manifest 与 X Adapter 定向 Pytest 30 项、backend code-size 和 git diff --check 通过。"
  ]
}
```

```json
{
  "control_topics": [
    "decisions",
    "interface"
  ],
  "recorded_on": "2026-08-28",
  "result": "ActorOps 新增已结算 Dataset 的零 Actor 费用重验：字段规则修复后保留原失败与费用，valid_nonempty 恢复 probationary 并计证明，合同兼容但无可发布内容只恢复 static_valid；真实 X 两来源复验后完成主用替换。",
  "status": "completed",
  "task_id": "2026-08-28-actorops-dataset-revalidation-x-replacement",
  "unresolved": [
    "未部署 VPS；本次按授权仅迁移共享本地数据库并完成本地真实 X 替换。"
  ],
  "validation": [
    "global 34 显式迁移创建 0600 备份并通过 marker/trigger、integrity 与 foreign keys；历史 X Dataset 零费用重验新增 1 条 remote_run_id=NULL 的 no_evidence 事实，原 $0.0999 失败 Attempt 不变。",
    "真实 X 新计划对两个 Binding 各启动 1 次 Run，均 valid_nonempty 且各结算 $0.0999；纯本地收口新增 Run 0，计划 applied，新 Candidate certified active，旧 Candidate certified inactive。",
    "ActorOps 定向 Pytest 70 项、前端 Vitest 12 项、TypeScript、ESLint、backend/frontend code-size、Markdown/项目/worklog 控制校验与 git diff --check 通过；本地前端和代理 API readiness 均为 HTTP 200。"
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
  "recorded_on": "2026-08-28",
  "result": "ActorOps Route 固定显示备用 1/2，并为未占用槽位新增人工补充入口；后端复用 Replacement 计划、Probe 和费用证据链，应用时只新增 Standby，不下线现有 Candidate。",
  "status": "completed",
  "task_id": "2026-08-28-actorops-empty-standby-manual-supplement",
  "unresolved": [
    "真实付费备用 Probe 与最终应用留给用户在本地页面手动验收。",
    "未部署 VPS；VPS 发布后仍需用户手动验收。"
  ],
  "validation": [
    "OperatorRepository 回归 18 项通过，覆盖空备用计划、Probe、费用门和应用。",
    "ActorOps 前端 Vitest 16 项、TypeScript、ESLint、backend/frontend code-size 通过。",
    "15173 已重启并确认提供补充入口新模块，18080 当前 Worktree API readiness 200。"
  ]
}
```

```json
{
  "control_topics": [
    "decisions",
    "interface"
  ],
  "recorded_on": "2026-08-29",
  "result": "ActorOps Discovery 在确定性 Manifest 未通过严格证明时继续进入逐 Candidate AI fallback；YouTube channel/items 补齐 RSS url 到 Actor target 的目标桥和 channelId/channelUrls/channelUrl、maxResults、date 等常见字段映射。定向发现的 4528 用户 Candidate 已通过免费 Preview 与一次真实 Probe，替换主用计划进入 ready。",
  "status": "completed",
  "task_id": "2026-08-29-actorops-youtube-mapping-and-replacement",
  "unresolved": [
    "YouTube 主用替换计划等待用户在本地 Drawer 完成最终应用确认。",
    "本地 API-only 预览仍不运行完整 Worker；另有 X 备用 2 与 Instagram 备用 1 授权计划尚未处理。",
    "未部署 VPS，VPS 仍需用户手动验收。"
  ],
  "validation": [
    "ActorOps Discovery、Adapter、Operator、Runtime、Maintenance 定向 Pytest 124 项通过。",
    "backend code-size、Markdown controls、TypeScript、ESLint 与 git diff check 通过。",
    "YouTube Candidate candidate_7490eadb60a13947ac64519c 免费 Preview 通过；真实 Probe valid_nonempty，1 次 Run 最终费用 $0.00105；计划 replacement-b3dfa0ea9bd845a8b7aaaaea1acdf45e 为 ready。",
    "15173 到当前 Worktree 18080 API readiness 返回 200。"
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
  "recorded_on": "2026-08-29",
  "result": "为 X、Instagram、YouTube 分别建立面向新发布内容的 Actor 字段映射 Prompt 与别名合同；最小发布合同改为 ID、原文 URL、发布时间、目标身份及 title/text 任一，图片为可选增强；YouTube 支持目标频道 URL 安全派生、handle 绑定和 maxItemsPerUrl，映射缺口改为可操作安全枚举。",
  "status": "completed",
  "task_id": "2026-08-29-actorops-route-specific-mapping-prompts",
  "unresolved": [
    "嵌套发布数组、命名 Dataset 与相对发布时间仍保留为待适配状态，未在本任务中自动展开或运行收费 Probe。"
  ],
  "validation": [
    "ActorOps 字段映射相关后端定向测试 108 项通过，随后解析器/Adapter/Prompt 回归 71 项通过；前端状态模型 5 项、TypeScript 与 ESLint 通过。",
    "旧 v28 migration 测试夹具降级顺序已修复，定向 2 项通过；冻结单体由 1538 行缩至 1497 行，代码体积门通过。",
    "最终 impacted preflight 16/16 通过；相同 7 个公开 YouTube Build Schema 的免费严格静态配对由 1/7 提升到 2/7，未运行 Actor、DeepSeek 或产生费用。"
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
  "recorded_on": "2026-08-29",
  "result": "ActorOps 候选闭环合并为高质量发现、系统可用性证明和稳定投入使用三阶段；Manifest v1 支持有界平铺/嵌套 Dataset 展开，运行、维护、替换与重验共享验证入口；已结算映射失败在原 Replacement plan 内最多两轮复用同一 Dataset 自动生成不可变后继 Candidate，新增 Actor Run 为零。",
  "status": "completed",
  "task_id": "2026-08-29-actorops-three-stage-dataset-adaptation",
  "unresolved": [
    "未发起真实付费 Actor Probe，因此公开商城前五候选的生产实测适配率仍需后续在既有费用授权下验收。",
    "按任务边界未重建容器、未部署 VPS、未操作用户浏览器。"
  ],
  "validation": [
    "ActorOps 后端三阶段定向 Pytest 193 项及 Manifest/结算/对账回归 46 项通过；代码尺寸测试 13 项通过。",
    "前端 ActorOps Vitest 21 项、TypeScript 和 ESLint 通过。",
    "独立端口 API 18082 live/ready、前端 15174 与 API 代理验证通过，使用临时数据库后已停止并清理。",
    "最终 impacted preflight 16/16 通过，包含完整后端/前端、控制合同、代码尺寸、语法和 diff 门禁。"
  ]
}
```

```json
{
  "control_topics": [
    "architecture",
    "decisions",
    "interface",
    "phase",
    "ui"
  ],
  "recorded_on": "2026-08-29",
  "result": "完成 ActorOps 候选质量与第二阶段可用性闭环：商城最多召回 80 条并检查 20 个 exact Revision 以补足 5 个相关候选；缺 Output Schema 通过 global 35 私有 InputPlan 进入受控单 Run 样本适配；仅 observed Manifest、当前 Binding 真实证明、最终费用及健康状态齐备时投影 system_usable，UI 按四类候选分组且静态结果不再显示为可替换。",
  "status": "completed",
  "task_id": "2026-08-29-actorops-stage2-usability",
  "unresolved": [],
  "validation": [
    "ActorOps 全域 Pytest（actorops、worker、migration）通过；缺 Schema 集成用例证明远端启动数始终为 1，适配失败不记为 Actor 故障。",
    "ActorOps 前端 Vitest 10 文件 46 项、TypeScript、ESLint 与代码尺寸硬门通过。",
    "独立本地端口 18089/15189 验证 API live/ready、OpenAPI、Vite 页面及 API 代理；未操作浏览器、未启动 Worker、未重建容器、未部署 VPS。",
    "impacted preflight：15/15 commands passed。"
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
  "result": "Closed ActorOps stage-two evidence gaps by preserving proof under immutable provider Actor identity, correcting real-schema aliases and input semantics, stopping AI at five quality-ranked candidates, and exposing exact Binding proof deficits or blockers instead of a generic sample state.",
  "status": "completed",
  "task_id": "2026-08-29-actorops-stage2-evidence-closure",
  "unresolved": [],
  "validation": [
    "Real Catalog/DeepSeek discovery: X 5/5, Instagram 5/5, YouTube 5/5 reached static_ready or sample_required with zero Actor starts",
    "Existing settled Dataset evidence: 4/7 system_usable and all 7/7 resolved as system_usable or an exact safe blocker; 344 attempts and 337 remote runs remained unchanged during no-run validation",
    "Backend targeted: 137 passed; frontend targeted: 25 passed; TypeScript, ESLint, backend/frontend code-size and diff checks passed",
    "Final impacted preflight: 15/15 commands passed"
  ]
}
```

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
