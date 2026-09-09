<!-- init-pro:control schema=3 profile=backend project=inteliscope-infohub-light file=PLAN.md -->
# Inteliscope InfoHub Light 当前实施计划

## 当前阶段与接续入口

2026-09-09 发布任务：用户授权将已整合的本地 main 发布为 v2.6.12 并部署 vps-tokyo。按精确 main CI、Tag smoke、本地 amd64 镜像、VPS 停服备份及 global 37–41 显式迁移、健康检查和失败回滚推进；本节是发布执行授权与范围，不代表已经上线。个人绑定、Skills 开放及真实模型/通知验收不隐式启用。

2026-09-09 当前任务：在本地 main 的独立 Worktree 实现 Skills 管理员开放控制。分支为 `codex/skill-access-control`，目录为同级 `infohub-light-skill-access-control`，起点 `dac81e2c`；不带入主工作区未提交修改。

- 实施范围：全站统一空默认开放清单、Owner/Admin 管理目录、普通目录与调用过滤、Service 到个人 Agent 的版本化同步、UI 和 global 41 显式迁移工具；合同见 [Gateway](docs/contracts/api/openclaw-gateway.md) 与 [Agent UI](docs/contracts/ui/agent-workspace.md)。
- 本阶段只交付独立 Worktree 的代码和受控验证，运行库迁移、容器重建、Gateway 真实写入、提交合并及生产发布未执行。
- 前期 Agent 阶段 1–6 的本地实现已落地；原库 global 38/39、个人 Gateway 接入与真实验收的历史证据见 WORKLOG。阶段 4、5 的真实通知仍待验收，不能以本次受控测试替代。
- 按 snapshot、定向测试、diff 审查、impacted preflight 和控制面校验收尾，追加一条任务记录。后续运行验收和发布另行安排。

## 现役能力与基线

| 分类 | 当前范围 |
| --- | --- |
| core | 小团体账号与角色、来源订阅、共享获取、用户 Feed/History、Worker、React/HeroUI、受保护媒体、可观测性、OpenClaw 工作区 |
| compatibility | 旧设置 URL、Service DB snapshot 双读、ActorOps v2 alias、离线迁移读路径、首库引导、OpenClaw 浏览器直连 |
| disabled | Remote MCP、OpenClaw chat、图片 I/O、付费 Actor/AI、通知和生产 MCP 写入默认关闭；目标环境启用需独立证据 |
| planned | 信息提醒、connector 和统一体验；阶段 2–6 本地实现不代表真实模型、通知或生产发布验收完成 |

2026-09-08 只读核验：线上 API/Worker 均为 `2.6.11 / 5b5916454b55`、running/healthy；公开 `/api/health/live` 版本一致，`/api/health/ready` 的服务与 Worker 均 ready。OpenClaw VPS 安装 `2026.9.2`，仅 `main` Agent，默认模型 `google/gemini-3.7-flash`，`llm-task` 未启用。本轮未执行模型、通知、服务器配置写入或数据库迁移；此证据只描述核验时状态。

阶段 0 snapshot：`/tmp/inteliscope-agent-experience-stage0-impact.json`，schema 2，base_sha 为上述 main 起点。文件丢失可用 `preflight --base 7f7be166adfa2f2961d8a71ec1494f0e9aaded51 --head HEAD` 复核起点以来已提交差异；下一阶段重新建立自己的 snapshot。snapshot 只是差异基线，不是测试通过证据。

阶段 1 功能提交 `df37a955`，snapshot `/tmp/inteliscope-agent-experience-stage1-impact.json`；完整证据见 WORKLOG。合同入口：[Gateway](docs/contracts/api/openclaw-gateway.md)、[Remote MCP](docs/contracts/api/remote-mcp.md)、[运行时/迁移](docs/contracts/architecture/jobs-notifications-runtime-migrations.md)、[Agent UI](docs/contracts/ui/agent-workspace.md)。

用户 2026-09-08 明确要求使用**原本地测试库**：runtime `/Users/stealmac/Documents/Inteliscope/infohub-light`，页面 `http://127.0.0.1:8080`，原 admin 密码已核对正确、未修改。原库 global 37 迁移已通过完整性检查，备份 `data/backups/service-agent-connections-v37-20260908T024212147468Z.db`。从任务 Worktree 执行标准 `./scripts/up-latest.sh`，不再传临时 runtime。原库已切回，原 admin 个人绑定已通过真实 MCP 验证并激活，登录与既有数据保留已核验。原有账号、订阅和历史保留；不要把临时数据库复制覆盖原库。先前 `/tmp/inteliscope-agent-experience-runtime` 仅保留双账号隔离验证证据，其 LOGIN.txt 不再是原库登录凭据。

## 前期阶段与退出条件

目标流程：描述关注的信息 → 澄清条件 → 可编辑规则卡 → 测试并确认启用 → 判断新增内容 → 自动通知 → 查看依据与发送结果。

| 阶段 | 本轮交付 | 退出条件 |
| --- | --- | --- |
| 0 基线 | 分支、Worktree、阶段计划、测试与运行版本基线 | 独立检出、控制检查及提交完成，不改业务功能 |
| 1 身份 | 用户/Agent/MCP delegation 绑定、部署配置工具、登录身份路由 | 两个测试账号的数据、会话、工具授权隔离；失效不回退共享 Agent |
| 2 体验 | 统一连接状态/修复入口、个人会话分页搜索恢复、可用 Skills | 网页真实连接、历史恢复、换账号通过，跨页保留草稿和运行 |
| 3 关键词 | 规则版本、测试/启停 API、持久事件、关键词判断、通知与运行记录 | 受控输入闭环，重复抓取/重启/发送未知不导致自动重复通知 |
| 4 聊天 UI | MCP 准备草稿、确认卡、测试、提醒列表/详情、模板 | 聊天到启用闭环；用户确认目标的一条关键词提醒有真实回执 |
| 5 语义 | connector 领取、独立推理、结果校验、配额与恢复 | 命中/不命中/证据不足/畸形输出通过；一条语义提醒有真实回执 |
| 6 发布 | 旧 Cron 完整提示词编辑、分页/Agent 绑定，高级入口、文档、迁移发布 | 精确提交门禁、生产健康与两个账号完整网页验收通过 |

阶段 1–5 使用受控测试环境；阶段 4/5 的真实通知仅面向用户明确确认的测试目标，不提前升级生产版本。无真实回执则记录该阶段未完成，不能用 mock、配置成功或入队替代。本阶段实现失败先修复；需外部授权的验收明确保留待办，可继续独立的本地工作，不把待验收阶段标为完成。

## 目标与兼容边界

以下约定以对应 API、UI 合同与 project-defaults.yaml 的已落实内容为准；本地实现的验收证据见 WORKLOG，生产能力不能从本地配置推断。

### 身份与使用

- 已落实的个人绑定、MCP 隔离和旧会话只读边界以 [Gateway 合同](docs/contracts/api/openclaw-gateway.md#个人绑定-api-与存储global-37) 与 [OpenClaw 架构](docs/contracts/architecture/openclaw-module-boundaries.md) 为准；本计划不重复实现细节。
- Owner/Admin/Member 完成绑定后可在后续阶段建提醒，Viewer 只读；提醒权限已独立实现，现有 delegation 不自动扩权。
- /agents 管接入，工作区复用状态；聊天、读取本人内容、建立提醒、通知可用分别验证，区分未配置/待验证/就绪/失效。Feed 小窗和完整工作区继续共用连接、草稿和运行生命周期。

### 规则与确认

- 阶段 3 已落实的关键词配置、版本、测试和确认边界以[信息提醒合同](docs/contracts/api/information-automations.md)为准；snapshot `/tmp/inteliscope-agent-experience-stage3-impact.json`。global 38/39 已于阶段 6 备份迁移到原测试库。
- 阶段 4 已实现服务端可信卡片和前端确认；缺少来源复用订阅创建流程。Agent 仅准备草稿。阶段 5 已实现独立 connector 语义判断，真实模型/通知仍待验收。

### 执行与结果

- 沿用 Feed 原事务事件、订阅归属、首次基线和去重，不增加抓取流程。Worker 负责触发与批次，connector 负责独立模型分析。
- 完整要求统一判断；大批量分段后汇总，最终结论才可投递。模型或额度不可用保留进度，未知发送不自动重试。
- 阈值、四种触发、权限复验和返回形状统一维护在[信息提醒合同](docs/contracts/api/information-automations.md)，不在计划重复定义。

### 接口与兼容

- 已实现接口：/api/me/information-automations 管草稿、测试、确认启用、暂停/归档；规则下 /runs 分页展示执行和投递。wire shape 随实现进入 API 合同。
- connector 接口采用独立机器凭据，仅领取授权绑定配置/任务并提交回执；MCP 增加本人规则查询和草稿准备的独立权限，既有 delegation 不扩权，不提供模型直接启用/发送工具。
- Service 保存绑定、规则版本、事件、必要输入/判断证据及投递关联，正文复用内容存储，不复制 Gateway 对话/Tasks/Artifacts 数据库。
- /agent/automations 默认展示信息提醒，原 Gateway Cron 留作高级兼容，不把全局 Cron 当本人规则；阶段 6 已修复长 Prompt 编辑截断、分页与执行 Agent。模板只填草稿，Worktree 保留在有权限的高级入口。

## 验证与非目标

每阶段记录完成内容、验证、未提交改动、下一阶段入口与未解决事项，WORKLOG 一阶段一条。重点覆盖双账号越权/晚到响应、重复/首次内容、共享来源、重启、修改/吊销、未知投递、畸形输出、正文截断与不可信指令；UI 覆盖移动端、键盘、深浅主题、Reduced Motion、完整提示词往返、分页和草稿连续性。

检查与 preflight 以[验证流程](docs/dev/test-gate.md)为准，不因分阶段降低门禁。UI 沿用设计系统/合同，新增行为用聚焦模块，冻结文件不增长。数据库显式备份迁移，不自动扩权或重放。用户验收并批准提交/发布后，阶段 6 再执行精确 main CI、本地构建镜像并上传 VPS；两个账号隔离、真实网页操作及关键词/语义真实通知回执共同构成完成证据。

继续维护现役 Feed/History、来源、ActorOps 和通知，已有迁移按目标环境证据显式操作。不做手机短信、站外定时搜索、通用代码执行升级、敌对多租户、多 workspace、商业计费、OAuth、archive analytics、Graph、推荐/embedding、站内原文代理；不复活旧 CLI、静态站、scheduler、本地 MCP。

历史原因按[决策索引](docs/decisions/README.md)定位，旧阶段按[历史索引](archive/project-history/README.md)定向读取，不作为默认上下文。
