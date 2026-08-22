<!-- init-pro:control schema=3 profile=backend project=inteliscope-infohub-light file=docs/decisions/ -->
# Inteliscope InfoHub Light 决策索引

本目录是决策理由与兼容性取舍的唯一真源。普通任务只在需要追溯理由、状态或替代方案时读取对应记录；新增决策追加到当前 `D151–D175` 分桶，满桶后创建下一个连续分桶。

| ID | 标题 | 日期 | 记录 |
| --- | --- | --- | --- |
| D001 | 初始化控制面 | 2026-07-08 | [查看](records/D001-D025.md#d001) |
| D002 | Light Runtime 默认不启动 scheduler | 2026-07-08 | [查看](records/D001-D025.md#d002) |
| D003 | Hub taxonomy 取代单层 AI 标签 | 2026-07-08 | [查看](records/D001-D025.md#d003) |
| D004 | personal_tags 不进入 AI scoring | 2026-07-08 | [查看](records/D001-D025.md#d004) |
| D005 | Service Feed 使用结构化结果和用户 finalizer | 2026-07-10 | [查看](records/D001-D025.md#d005) |
| D006 | SQLite Queue 使用 claim token 和 heartbeat | 2026-07-10 | [查看](records/D001-D025.md#d006) |
| D007 | Feed v2 采用显式备份后重建迁移 | 2026-07-10 | [查看](records/D001-D025.md#d007) |
| D008 | 当前产品收口为信息获取与 Feed 留存 | 2026-07-11 | [查看](records/D001-D025.md#d008) |
| D009 | 每用户 opt-in 周期由现有 Worker 调度 | 2026-07-11 | [查看](records/D001-D025.md#d009) |
| D010 | RC1 采用不可变镜像和分阶段 VPS 切换 | 2026-07-12 | [查看](records/D001-D025.md#d010) |
| D011 | 本地密钥使用 write-only 文件边界并为每篇文章生成受控概括 | 2026-07-13 | [查看](records/D001-D025.md#d011) |
| D012 | 订阅级自动抓取复用现有 Worker 与单源 finalizer | 2026-07-13 | [查看](records/D001-D025.md#d012) |
| D013 | Service API 使用请求级连接，macOS bind mount 使用 DELETE journal | 2026-07-13 | [查看](records/D001-D025.md#d013) |
| D014 | 默认 Service UI 迁移为 React 三栏信息雷达 | 2026-07-13 | [查看](records/D001-D025.md#d014) |
| D015 | React Shell 与 Feed 采用受控 Material UI 视觉系统 | 2026-07-14 | [查看](records/D001-D025.md#d015) |
| D016 | Service Feed 使用确定性 Presentation v1，取消“为什么值得关注” | 2026-07-14 | [查看](records/D001-D025.md#d016) |
| D017 | Material UI 扩展到订阅控制台并采用更新前 Worker 预检 | 2026-07-14 | [查看](records/D001-D025.md#d017) |
| D018 | 订阅以频道组织，主题删除非破坏，阅读详情取消建议动作 | 2026-07-14 | [查看](records/D001-D025.md#d018) |
| D019 | 公共来源共享中性获取，用户投影与 Feed 版本继续隔离 | 2026-07-14 | [查看](records/D001-D025.md#d019) |
| D020 | 收藏与站内阅读使用稳定内容索引和受保护媒体缓存 | 2026-07-14 | [查看](records/D001-D025.md#d020) |
| D021 | 测试门禁采用确定性影响映射和限长摘要 | 2026-07-15 | [查看](records/D001-D025.md#d021) |
| D022 | Feed 通知事件化、历史内容可审计修复并切换 DeepSeek | 2026-07-15 | [查看](records/D001-D025.md#d022) |
| D023 | 来源响应只保存有界结构摘要，头像采用验证后换版 | 2026-07-16 | [查看](records/D001-D025.md#d023) |
| D024 | 每用户本地 OpenClaw 通过远程只读 MCP 访问 Inteliscope | 2026-07-16 | [查看](records/D001-D025.md#d024) |
| D025 | Next Web 工作台借鉴 Codex 视觉语言但以 Inteliscope 交互为准 | 2026-07-17 | [查看](records/D001-D025.md#d025) |
| D026 | HeroUI v3 作为独立候选原型，不与生产 MUI 混用 | 2026-07-17 | [查看](records/D026-D050.md#d026) |
| D027 | HeroUI 生产迁移采用单一设计系统边界与渐进 bootstrap | 2026-07-17 | [查看](records/D026-D050.md#d027) |
| D028 | 生产 UI 单一切换到 HeroUI，并删除双栈回滚 | 2026-07-17 | [查看](records/D026-D050.md#d028) |
| D029 | Feed 视觉确认先采用单页 Codex 风格微调 | 2026-07-18 | [查看](records/D026-D050.md#d029) |
| D030 | — Feed adopts the approved Quiet Studio variant | 2026-07-18 | [查看](records/D026-D050.md#d030) |
| D031 | Quiet Studio 采用分类导航、双向排序和确定性交接编辑器 | 2026-07-18 | [查看](records/D026-D050.md#d031) |
| D032 | 生产 UI 采用单一字体栈与可执行语义排版契约 | 2026-07-18 | [查看](records/D026-D050.md#d032) |
| D033 | Quiet Studio 成为全站自适应视觉与交互语言 | 2026-07-19 | [查看](records/D026-D050.md#d033) |
| D034 | Remote MCP 订阅写入采用服务端 proposal 与显式 opt-in delegation | 2026-07-18 | [查看](records/D026-D050.md#d034) |
| D035 | Inteliscope 浏览器直接连接用户自有 OpenClaw Gateway | 2026-07-19 | [查看](records/D026-D050.md#d035) |
| D036 | 信息工作台采用来源优先的社交卡片与可读 Agent 上下文 | 2026-07-19 | [查看](records/D026-D050.md#d036) |
| D037 | Feed 采用活跃来源的滚动时间窗口并收口侧栏/上下文可达性 | 2026-07-19 | [查看](records/D026-D050.md#d037) |
| D038 | 删除生产控制面中的历史 Material UI capability 词汇 | 2026-07-20 | [查看](records/D026-D050.md#d038) |
| D039 | 内容工作台刷新与排序动作按数据所有权分配 | 2026-07-20 | [查看](records/D026-D050.md#d039) |
| D040 | 内容格式与媒体完整性采用来源优先的统一展示投影 | 2026-07-20 | [查看](records/D026-D050.md#d040) |
| D041 | OpenClaw 浏览器对话采用真实会话模型与分离显示消息 | 2026-07-20 | [查看](records/D026-D050.md#d041) |
| D042 | Feed 右栏、当天口径、OpenClaw 运行时与媒体身份统一收口 | 2026-07-21 | [查看](records/D026-D050.md#d042) |
| D043 | Insights 脱离固定栏，Agent 宽度可调且 OpenClaw 历史只增量对账 | 2026-07-21 | [查看](records/D026-D050.md#d043) |
| D044 | 对话落盘、Agent 停靠与概览高度以运行时事实为准 | 2026-07-22 | [查看](records/D026-D050.md#d044) |
| D045 | 私人来源提升复用稳定内容，订阅停用由用户决定现有内容去向 | 2026-07-22 | [查看](records/D026-D050.md#d045) |
| D046 | 刷新接管采用静态布局壳与局部内容揭示 | 2026-07-22 | [查看](records/D026-D050.md#d046) |
| D048 | 系统主题与更新日志由前端确定性状态驱动 | 2026-07-22 | [查看](records/D026-D050.md#d048) |
| D049 | OpenClaw 会话按站点唯一命名并采用扁平时间线 | 2026-07-22 | [查看](records/D026-D050.md#d049) |
| D050 | OpenClaw 浏览器配对采用服务端优先设备移除 | 2026-07-22 | [查看](records/D026-D050.md#d050) |
| D051 | 已吊销 Remote MCP 连接通过独立动作删除单条记录 | 2026-07-23 | [查看](records/D051-D075.md#d051) |
| D052 | 成员单元格、OpenClaw 能力与 Feed 定位按真实职责拆分 | 2026-07-23 | [查看](records/D051-D075.md#d052) |
| D053 | 显式明暗模式与遮挡概览采用浏览器确定性状态 | 2026-07-23 | [查看](records/D051-D075.md#d053) |
| D054 | 设置页密钥管理采用局部失败反馈与安全额度投影 | 2026-07-23 | [查看](records/D051-D075.md#d054) |
| D055 | Apify 切换采用工作区单一有序池与 Run generation 排空屏障 | 2026-07-23 | [查看](records/D051-D075.md#d055) |
| D056 | 全站终态操作反馈使用单一顶部 Toast 队列 | 2026-07-23 | [查看](records/D051-D075.md#d056) |
| D057 | 产品操作手册与更新日志采用双源合并门禁 | 2026-07-23 | [查看](records/D051-D075.md#d057) |
| D058 | 订阅管理采用频道聚焦的紧凑列表 | 2026-07-24 | [查看](records/D051-D075.md#d058) |
| D059 | 订阅验收收口为低噪声来源卡与紧凑运行记录 | 2026-07-24 | [查看](records/D051-D075.md#d059) |
| D060 | 订阅控件位置与运行详情采用直接、柔和的交互 | 2026-07-24 | [查看](records/D051-D075.md#d060) |
| D061 | 偏好来源通知采用提交后 outbox 与双启用水位 | 2026-07-24 | [查看](records/D051-D075.md#d061) |
| D062 | Service 邮件采用工作区 Provider Registry 与测试代数门禁 | 2026-07-24 | [查看](records/D051-D075.md#d062) |
| D063 | Browser 运行记录交接直接使用安全任务诊断 | 2026-07-24 | [查看](records/D051-D075.md#d063) |
| D064 | Feed Insights 先复用居中阅读列的左侧空白 | 2026-07-24 | [查看](records/D051-D075.md#d064) |
| D065 | 诊断日志采用私有双流文件与当前用户 MCP 投影 | 2026-07-24 | [查看](records/D051-D075.md#d065) |
| D066 | Feed 数据重载与后台更新采用独立完成边界 | 2026-07-24 | [查看](records/D051-D075.md#d066) |
| D067 | RSSHub 采用单 VPS 鉴权服务与语义来源身份 | 2026-07-25 | [查看](records/D051-D075.md#d067) |
| D068 | Inteliscope 生产镜像只允许本地跨架构构建 | 2026-07-25 | [查看](records/D051-D075.md#d068) |
| D069 | RSSHub 的 Bilibili 匿名运行态由隔离浏览器刷新 | 2026-07-25 | [查看](records/D051-D075.md#d069) |
| D070 | 本地初始化主动对账仓库托管的 OpenClaw Skill | 2026-07-25 | [查看](records/D051-D075.md#d070) |
| D071 | OpenClaw 通过固定 Bilibili 公开查询把账号名称解析为 UID | 2026-07-25 | [查看](records/D051-D075.md#d071) |
| D072 | Browser OpenClaw 按附件存在性拆分直接请求与只读交接 | 2026-07-26 | [查看](records/D051-D075.md#d072) |
| D073 | RSS 首次抓取窗口以首个成功健康记录为边界 | 2026-07-26 | [查看](records/D051-D075.md#d073) |
| D074 | OpenClaw 运行反馈与紧凑 UI 按语义拆分 | 2026-07-26 | [查看](records/D051-D075.md#d074) |
| D075 | 高密度状态、危险操作与设置导航采用渐进披露 | 2026-07-26 | [查看](records/D051-D075.md#d075) |
| D076 | Browser Agent 允许桌面后台运行并保留安全来源引用 | 2026-07-27 | [查看](records/D076-D100.md#d076) |
| D077 | 核心设置原子总保存并明确高密度交互所有权 | 2026-07-27 | [查看](records/D076-D100.md#d077) |
| D078 | 历史列表以用户稳定内容索引为真源 | 2026-07-27 | [查看](records/D076-D100.md#d078) |
| D079 | 稳定内容按上海自然日分层并采用预演式冷归档 | 2026-07-27 | [查看](records/D076-D100.md#d079) |
| D080 | 信息卡片使用单张代表缩略图与有界全图预览 | 2026-07-28 | [查看](records/D076-D100.md#d080) |
| D081 | 本地 Worktree 重建分离源码根与运行时根 | 2026-07-28 | [查看](records/D076-D100.md#d081) |
| D082 | 折叠卡片前置轻量堆叠代表缩略图 | 2026-07-28 | [查看](records/D076-D100.md#d082) |
| D083 | YouTube 频道作为 RSS 存储之上的一等 setup 类型 | 2026-07-28 | [查看](records/D076-D100.md#d083) |
| D084 | 更新日志时间线由现有 HeroUI OSS 设计系统独立实现 | 2026-07-28 | [查看](records/D076-D100.md#d084) |
| D085 | 自动全局与单源独立周期按订阅互斥 | 2026-07-28 | [查看](records/D076-D100.md#d085) |
| D086 | 项目控制历史采用 schema-v3 映射与活动/归档分层 | 2026-07-28 | [查看](records/D076-D100.md#d086) |
| D087 | Agent 通用来源解析采用 registry adapter 与短期引用 | 2026-07-29 | [查看](records/D076-D100.md#d087) |
| D088 | 首批性能优化采用路由分包、轻量列表与兼容视图 | 2026-07-29 | [查看](records/D076-D100.md#d088) |
| D089 | 信息流触底文案采用共享三场景与空闲 Worker AI 缓存 | 2026-07-29 | [查看](records/D076-D100.md#d089) |
| D090 | 终页与空列表统一为轻量符号文案 | 2026-07-29 | [查看](records/D076-D100.md#d090) |
| D091 | 触底文案状态展示完整场景列表 | 2026-07-29 | [查看](records/D076-D100.md#d091) |
| D092 | X/profile 采用独立三 Actor 路由、费用熔断与工作区告警 | 2026-07-29 | [查看](records/D076-D100.md#d092) |
| D093 | Service Webhook 对飞书/Lark 自定义机器人采用原生文本消息 | 2026-07-29 | [查看](records/D076-D100.md#d093) |
| D094 | Service Webhook 采用七类显式 Provider Registry 与业务 ACK | 2026-07-30 | [查看](records/D076-D100.md#d094) |
| D095 | 高频任务观察与完整运行记录分离 | 2026-07-30 | [查看](records/D076-D100.md#d095) |
| D096 | 设置查询、内容缓存与静态传输采用显式用途边界 | 2026-07-30 | [查看](records/D076-D100.md#d096) |
| D097 | 设置分区以相邻滚动意图自然激活 | 2026-07-30 | [查看](records/D076-D100.md#d097) |
| D098 | 来源头像与内容条目选择解耦 | 2026-07-30 | [查看](records/D076-D100.md#d098) |
| D099 | 故障排查采用可串联日志、显式工作区诊断与硬合同门禁 | 2026-07-30 | [查看](records/D076-D100.md#d099) |
| D100 | Telegram 采用工作区共享 Transport 与逐渠道独立投递 | 2026-07-30 | [查看](records/D076-D100.md#d100) |
| D101 | 通知目的地统一为私有/共享目标并由业务绑定复用 | 2026-07-31 | [查看](records/D101-D125.md#d101) |
| D102 | 通知目标产品交互统一为管理员通知服务 | 2026-07-31 | [查看](records/D101-D125.md#d102) |
| D103 | Apify Actor 路由泛化为声明式三槽 ActorOps 控制面 | 2026-07-30 | [查看](records/D101-D125.md#d103) |
| D104 | Actor Discovery 输出容量以安全实测和管理员热配置决定 | 2026-08-01 | [查看](records/D101-D125.md#d104) |
| D105 | Apify 响应故障按幂等读取与候选边界隔离 | 2026-08-01 | [查看](records/D101-D125.md#d105) |
| D106 | Actor Discovery 人工选 Key 且 Canary 失败证据闭环 | 2026-08-02 | [查看](records/D101-D125.md#d106) |
| D107 | Actor Dataset 行级合同允许安全隔离账号元数据 | 2026-08-02 | [查看](records/D101-D125.md#d107) |
| D108 | ActorOps 认证流程在付费与保存前显示可达性 | 2026-08-02 | [查看](records/D101-D125.md#d108) |
| D109 | ActorOps 由服务端排槽，管理员只确认生效 | 2026-08-02 | [查看](records/D101-D125.md#d109) |
| D110 | ActorOps 允许两路 Canary 成功后快速上线 | 2026-08-02 | [查看](records/D101-D125.md#d110) |
| D111 | YouTube Items 采用静态负证据与不可变失败终止重复付费 | 2026-08-02 | [查看](records/D101-D125.md#d111) |
| D112 | Route 认证采用一次审批的串行两路批次 | 2026-08-02 | [查看](records/D101-D125.md#d112) |
| D113 | YouTube Actor 以精确视频 Schema 覆盖模糊定价事件 | 2026-08-03 | [查看](records/D101-D125.md#d113) |
| D114 | 未知启动以账号级空窗口证明自愈，费用等待远端聚合稳定 | 2026-08-03 | [查看](records/D101-D125.md#d114) |
| D115 | Settings 采用独立工作区并按路由渐进迁移 | 2026-08-03 | [查看](records/D101-D125.md#d115) |
| D116 | 密钥管理按 SecretStore 语义原生迁入 Settings Workspace | 2026-08-04 | [查看](records/D101-D125.md#d116) |
| D117 | 获取与主题按配置域迁入 Settings Workspace | 2026-08-04 | [查看](records/D101-D125.md#d117) |
| D118 | ActorOps 原生化并采用 Default 实色设置表面 | 2026-08-04 | [查看](records/D101-D125.md#d118) |
| D119 | Settings Workspace 完成存储归档原生化与通知服务表格化 | 2026-08-04 | [查看](records/D101-D125.md#d119) |
| D120 | 触底文案可绑定同 Provider 的独立 AI Key，Feed 浮层工具栏半透明化 | 2026-08-05 | [查看](records/D101-D125.md#d120) |
| D121 | AI Key 主导 Provider 与场景模型绑定 | 2026-08-06 | [查看](records/D101-D125.md#d121) |
| D122 | AI 设置以 Key 搜索和整块文案明细收敛 | 2026-08-06 | [查看](records/D101-D125.md#d122) |
| D123 | Apify Key 池以异常优先的紧凑摘要展示 | 2026-08-06 | [查看](records/D101-D125.md#d123) |
| D124 | Apify Key 采用直接可操作的独立卡片 | 2026-08-06 | [查看](records/D101-D125.md#d124) |
| D125 | OpenClaw 附带内容主动读取原网页与来源引用统一 | 2026-08-06 | [查看](records/D101-D125.md#d125) |
| D126 | OpenClaw 附件摘要采用满宽行、按需上浮与快速清空 | 2026-08-07 | [查看](records/D126-D150.md#d126) |
| D127 | OpenClaw 模型选择器按紧凑 Prompt Input 尺寸收口 | 2026-08-07 | [查看](records/D126-D150.md#d127) |
| D128 | 订阅视图固定为范围与异常，卡片状态承载条数 | 2026-08-07 | [查看](records/D126-D150.md#d128) |
| D129 | 订阅筛选取代固定视图，工具栏随列表固定 | 2026-08-07 | [查看](records/D126-D150.md#d129) |
| D130 | 订阅工具栏按滚动收为浮动胶囊 | 2026-08-07 | [查看](records/D126-D150.md#d130) |
| D131 | 来源库取消频道导航并收紧工具栏顶部态 | 2026-08-07 | [查看](records/D126-D150.md#d131) |
| D132 | OpenClaw 图片对话使用浏览器规范化与 Gateway 媒体票据 | 2026-08-07 | [查看](records/D126-D150.md#d132) |
| D133 | 正式发布复用精确 main Gate 并将 Tag 收为隔离 smoke | 2026-08-07 | [查看](records/D126-D150.md#d133) |
| D134 | 目录型控制真源与活动 Markdown 预算 | 2026-08-07 | [查看](records/D126-D150.md#d134) |
| D135 | OpenClaw Composer 采用单层输入壳与本地建议组件 | 2026-08-08 | [查看](records/D126-D150.md#d135) |
| D136 | 登录页采用响应式双栏与非持久凭据交互 | 2026-08-09 | [查看](records/D126-D150.md#d136) |
| D137 | Feed 专题速览采用浏览器本地双阅读布局与前端来源分组 | 2026-08-09 | [查看](records/D126-D150.md#d137) |
| D138 | 成员账号改名与删除采用受保护的生命周期操作 | 2026-08-10 | [查看](records/D126-D150.md#d138) |
| D139 | 专题总结采用主线提示与浏览器精确内容缓存 | 2026-08-10 | [查看](records/D126-D150.md#d139) |
| D140 | ActorOps 以持久 Pool Stage 完成第三槽与零中断 legacy 升级 | 2026-08-09 | [查看](records/D126-D150.md#d140) |
| D141 | ActorOps 由管理员选择安全候选且验证后立即可运行 | 2026-08-10 | [查看](records/D126-D150.md#d141) |
| D142 | ActorOps 验证参数按失败冻结并禁止原样重复付费 | 2026-08-10 | [查看](records/D126-D150.md#d142) |
| D143 | ActorOps legacy 默认升级原 Actor 且来源验证在审批前阻断不安全 Revision | 2026-08-10 | [查看](records/D126-D150.md#d143) |
| D144 | React、FastAPI、Worker 与 Remote MCP 成为唯一运行面 | 2026-08-11 | [查看](records/D126-D150.md#d144) |
| D145 | 提交与发布采用主动审查和前移 preflight | 2026-08-11 | [查看](records/D126-D150.md#d145) |
| D146 | 一次性 MCP 令牌采用可复制的本地写入命令 | 2026-08-11 | [查看](records/D126-D150.md#d146) |
| D147 | 新增来源采用平台别名，legacy X 只扩大当前三 Actor 召回 | 2026-08-11 | [查看](records/D126-D150.md#d147) |
| D148 | ActorOps 采用显式单路兼容、新鲜度水位与专用校验面 | 2026-08-12 | [查看](records/D126-D150.md#d148) |
| D149 | 登录、设置与 OpenClaw 视图按需加载并收紧首屏预算 | 2026-08-12 | [查看](records/D126-D150.md#d149) |
| D150 | 代码健康采用项目级旧债棘轮与单向运行时依赖 | 2026-08-12 | [查看](records/D126-D150.md#d150) |
| D151 | 手动信息流刷新按实时角色限域，并采用协作式安全停止 | 2026-08-13 | [查看](records/D151-D175.md#d151) |
| D152 | ActorOps 固定三槽采用服务端槽位操作与证据保留 | 2026-08-13 | [查看](records/D151-D175.md#d152) |
| D153 | 槽位重规划保持服务端目标可见，超额费用终态拒绝 | 2026-08-14 | [查看](records/D151-D175.md#d153) |
| D154 | ActorOps 候选先经免费可执行性证明，精确零费用中止可恢复未知启动 | 2026-08-14 | [查看](records/D151-D175.md#d154) |
| D155 | ActorOps 以认证槽位手动主用和公开 Store 质量排序收口管理员选择 | 2026-08-14 | [查看](records/D151-D175.md#d155) |
| D156 | YouTube 以来源认证 Actor 为主、Atom 仅作失败降级 | 2026-08-17 | [查看](records/D151-D175.md#d156) |
| D157 | ActorOps 只向浏览器暴露已完成实测与对账的目录 | 2026-08-18 | [查看](records/D151-D175.md#d157) |
| D158 | ActorOps 能力矩阵统一标准主备，并免费恢复中断的既有 Canary | 2026-08-18 | [查看](records/D151-D175.md#d158) |
| D159 | ActorOps 自动替换退役并回归免费发现与双确认 | 2026-08-20 | [查看](records/D151-D175.md#d159) |
| D160 | ActorOps v2 采用稳定获取优先与按订阅能力注册的适配器架构 | 2026-08-20 | [查看](records/D151-D175.md#d160) |
| D161 | global 26 只迁移已收敛摘要，不接管 v1 inflight | 2026-08-20 | [查看](records/D151-D175.md#d161) |
| D162 | ActorOps v2 数据面使用双门切换和无状态 Adapter 合同 | 2026-08-20 | [查看](records/D151-D175.md#d162) |
| D163 | ActorOps v2 对账只结算既有事实，并与 Worker claim 隔离 | 2026-08-20 | [查看](records/D151-D175.md#d163) |
| D164 | ActorOps v2 Discovery 以安全 checkpoint 和确定性优先恢复 | 2026-08-20 | [查看](records/D151-D175.md#d164) |
| D165 | ActorOps v2 站立维护采用双授权、单 Probe 与最后一路保护 | 2026-08-20 | [查看](records/D151-D175.md#d165) |
| D166 | ActorOps v2 以离线 Route CAS 和逐平台费用授权切流 | 2026-08-20 | [查看](records/D151-D175.md#d166) |
| D167 | 历史 Actor 费用以保留最坏暴露的离线证据隔离 | 2026-08-21 | [查看](records/D151-D175.md#d167) |
| D168 | ActorOps v2 管理面采用 additive facade 与默认关闭策略 CAS | 2026-08-21 | [查看](records/D151-D175.md#d168) |
| D169 | global 26 只接受单一已结算远端 Run 作为旧 Attempt 费用证明 | 2026-08-21 | [查看](records/D151-D175.md#d169) |
| D170 | 目录社交订阅缺失旧 binding 时以离线 pending bridge 修复 | 2026-08-21 | [查看](records/D151-D175.md#d170) |
| D171 | 切流只比较当前可执行 revision，并以 settled 来源证明解锁既有 binding | 2026-08-21 | [查看](records/D151-D175.md#d171) |
| D172 | 实际 Canary 的 AI 字段映射必须逐精确 Revision 证明 | 2026-08-21 | [查看](records/D151-D175.md#d172) |
| D173 | 可配置 Canary 上限与真实费用证明一致 | 2026-08-21 | [查看](records/D151-D175.md#d173) |
| D174 | ActorOps v2 管理台以脱敏主备切换与来源证据核验收口 | 2026-08-21 | [查看](records/D151-D175.md#d174) |
| D175 | ActorOps v2 公开商城快照与替换采用显式费用授权 | 2026-08-21 | [查看](records/D151-D175.md#d175) |
| D176 | ActorOps 以 global 30 完成 v2 单轨运行面 | 2026-08-23 | [查看](records/D176-D200.md#d176) |
