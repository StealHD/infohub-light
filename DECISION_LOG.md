# Inteliscope InfoHub Light 决策记录

## 1. 文档目的
本文件记录重要架构决策、范围裁剪和兼容性约束，用于避免后续 AI 协作过程中反复偏航。

## 2. 决策记录格式
每条记录建议包含：

1. 决策编号
2. 决策主题
3. 决策日期
4. 当前状态
5. 决策内容
6. 原因
7. 影响范围
8. 后续待验证事项

## 3. 已确认决策
### D001 初始化控制面
- 决策日期：2026-07-08
- 当前状态：已确认
- 决策内容：项目采用 `AGENTS.md`、`PLAN.md`、`API_CONTRACT.md`、`ARCHITECTURE_CONTRACT.md`、`DECISION_LOG.md`、`CONTEXT_READ_RULES.md`、`WORKLOG.md` 和 `project-defaults.yaml` 维护 AI 协作控制面。
- 原因：减少上下文漂移，明确唯一真源，并保留每次任务的简洁执行记录。
- 影响范围：全部控制文件。
- 后续待验证事项：后续是否需要新增领域专用合同文件。

### D002 Light Runtime 默认不启动 scheduler
- 决策日期：2026-07-08
- 当前状态：已确认
- 决策内容：light worktree 默认通过 `docker-compose.light.yml` 只启动 `horizon-web`，scheduler 需要显式 profile。
- 原因：这是私人信息 Hub 的本地迭代环境，默认启动后台抓取、AI、推送会带来成本和副作用。
- 影响范围：`scripts/up-latest.sh`、`docker-compose.light.yml`、运行验证流程。
- 后续待验证事项：每次修改 runtime 脚本后检查 `horizon-light-scheduler` 未被默认启动。

### D003 Hub taxonomy 取代单层 AI 标签
- 决策日期：2026-07-08
- 当前状态：已确认
- 决策内容：新实现优先使用 `channel/topics/signal_strength/signal_type/entities`；`category/tags` 保留为兼容 alias。
- 原因：当前阅读筛选需要按主题快速定位内容，长期归档分析需要更稳定的一等字段。
- 影响范围：`ContentItem`、source config、AI prompt/cache、static payload、UI filter、SQLite archive。
- 后续待验证事项：真实来源中 `其他` 占比、空 topics、弱信号占比是否可接受。

### D004 personal_tags 不进入 AI scoring
- 决策日期：2026-07-08
- 当前状态：已确认
- 决策内容：`personal_tags` 只表示用户偏好和私人 feed 信号，不发送给 AI scoring prompt。
- 原因：用户偏好会污染内容主题判断，也会增加不必要的 prompt 成本。
- 影响范围：scraper metadata、orchestrator partition、AI prompt、static payload。
- 后续待验证事项：personal-only feed 仍能进入历史和私人 feed。
