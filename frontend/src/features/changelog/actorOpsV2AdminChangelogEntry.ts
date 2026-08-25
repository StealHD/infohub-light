import type { ChangelogEntry } from './changelogTypes'

export const actorOpsV2AdminChangelogEntries: ChangelogEntry[] = [
  {
    date: '2026-08-24',
    title: 'RSSHub 访问密钥可在获取页安全管理',
    summary: 'RSSHub 服务卡现在把连接状态、服务地址和边界说明分层呈现，访问密钥不再跳转到无法管理它的通用密钥页。',
    items: [
      { title: '状态与操作更清楚', description: '页面明确显示已配置、未配置或环境托管；页面托管时可直接配置、轮换或经确认移除 write-only 访问密钥，环境托管值只允许由运维处理。' },
      { title: 'Actor 商城资料可安心查看', description: 'Actor 标签悬停、聚焦或触屏点击可打开公开商城资料；浮层不会遮断标签命中或抢走指针焦点，整个标签保持稳定手型光标，可移动到浮层继续访问“打开 Apify”，离开整体区域或按 Escape 后才关闭。' },
    ],
  },
  {
    date: '2026-08-24',
    title: '桌面侧栏展开更平滑',
    summary: '展开和收起侧栏时，导航文字与账户区不再在中间宽度跳变；最终折叠与展开布局保持不变。',
    items: [
      { title: '文字始终按完整宽度排版', description: '侧栏会平滑移动外框，内部导航同时使用固定画布渐显，避免标签在动画中被压成竖排。' },
      { title: '账户入口保持稳定', description: '底部账户区固定高度，头像在展开和收起时只做连续位移；导航实际溢出时才出现可滚动区域。' },
    ],
  },
  {
    date: '2026-08-24',
    title: 'ActorOps 路由与运行日志现在分开查看',
    summary: 'Route 管理保持紧凑，告警、待处理事件和安全操作记录移到可分享的“运行日志”页签，避免在同一长页混排。',
    items: [
      { title: '待处理状态会告诉你下一步', description: '每条待处理事件都会说明原因、影响、下一步和安全入口。无法确认启动时只可打开固定 Apify 运行记录并刷新安全日志，不提供人工关闭或重复启动。' },
      { title: '操作记录更容易辨认', description: '记录会说明是主用调整、Binding 核验、候选发现、商城刷新、费用设置、替换计划还是维护策略；需要时可展开安全阶段、数量、费用、错误码和请求结果。' },
      { title: 'Route 卡更紧凑', description: '默认只看平台健康、主用/备用、最近成功、已核验数量、费用上限和操作；查看运行详情仍按需读取，同一时刻只展开一条路线。' },
    ],
  },
  {
    date: '2026-08-24',
    title: '替换 Actor 时会展示公开资料',
    summary: '管理员在选择替换候选时可直接比较 Actor 名称、公开地址、评分、收藏、用户量、发布者、维护方、价格和核验状态。',
    items: [
      { title: '不再显示难以辨认的内部标识', description: '缺少可读公开资料的候选会明确显示“商城信息待更新”，不会把平台内部的长串标识当作 Actor 名称。' },
    ],
  },
  {
    date: '2026-08-24',
    title: 'ActorOps 会识别长期旧数据并自动安排修复',
    summary: '同一个 Actor 连续返回旧内容时，系统会由备用路线交叉确认；全部路线失败时，在既有维护授权和预算内异步寻找并验证替代路线。',
    items: [
      { title: '“没有新内容”与“Actor 旧数据”分开判断', description: '自然周期连续三次无推进后才会优先请求备用 Actor；备用也无推进代表确实没有新内容，备用推进则只暂停原 Actor 在该来源的优先级六小时，不立即影响其他订阅。' },
      { title: '失败后不重复扣费', description: '双路线都已结算失败时，本次抓取会保留原信息流和水位并交给后台修复；未知费用、未授权或预算不足会明确阻断，不会重放同一次抓取或移除最后一路。' },
      { title: '管理员可查看完整安全链路', description: '展开管理员任务的 Actor 执行链路可看到候选选择、启动、结算、回退和修复阶段；不会显示账号目标、帖子正文、输入、密钥或远端运行标识。' },
    ],
  },
  {
    date: '2026-08-24',
    title: 'X 账号回复不再混入信息流',
    summary: 'X 账号订阅会在发布前识别并排除断开父帖语境的回复，同时保留原创、引用、转发和无法可靠判断关系的帖子。',
    items: [
      { title: '回复不占最终获取条数', description: '系统先验证 Actor 结果，再按结构化回复标记或父帖关系过滤，并对剩余帖子重新应用时间窗口和每次获取条数；较新的回复不会挤掉同批次较早的主帖。' },
      { title: '不靠正文猜测', description: '回复数量、正文以 @ 或 RT 开头都不会触发过滤；只有上游明确提供的关系证据才会排除，引用和转发保持现有行为。历史信息流不会被自动重抓、删除或改写。' },
    ],
  },
  {
    date: '2026-08-23',
    title: 'X 抓取会追赶水位并识别 Actor 旧缓存',
    summary: '中断超过日常窗口的更新不再永久漏过；有记录但全是旧帖的 Dataset 会切备用，明确未启动的拒绝按 0 费用收敛。',
    items: [
      { title: '从来源水位补齐更新', description: 'X、Instagram 与认证 YouTube Actor 的抓取窗口会从来源已发布水位和当前窗口的较早者开始；首次抓取也会在条数与费用上限内读取最新结果，不把 Feed 的 24 小时展示范围误当成永久获取边界。' },
      { title: '旧缓存不再显示成功 0 条', description: 'Actor 返回可识别帖子但全部早于当前窗口时，系统保留最新观察时间并和来源水位比较；倒退或可疑结果会标记 Candidate 失败并串行尝试备用，不推进水位。' },
      { title: '未启动费用按证据收敛', description: '只有 Apify 明确拒绝启动且共享账本同时证明没有远端 Run、Dataset 和费用时，Attempt 才会按 0 美元终结并继续备用；未知启动、费用不明或证据冲突仍会停止后续付费。' },
    ],
  },
  {
    date: '2026-08-23',
    title: 'ActorOps 已完成 v2 单轨化',
    summary: '现役来源、管理台、Worker 和浏览器只使用 v2；Route 只保留启用或停用，数据库升级仍需由管理员在停机窗口明确执行。',
    items: [
      { title: '旧路径不会再参与运行', description: '旧 Pool、Canary、Freshness、Discovery 和 shadow 路线不再由 API、Worker 或页面访问；历史任务和表只保留给离线审计与退役工具。' },
      { title: '新库从现役 v2 目录开始', description: '新建数据库会直接准备 X、Instagram、YouTube 的停用 Route、Binding schema、维护策略和共享告警；来源仍须完成 Binding 验证并由管理员启用。' },
      { title: '升级只在明确窗口完成', description: 'global 30 缺失时 ActorOps 会明确提示迁移需要；安装前会检查 API/Worker 已停止，先创建私有备份并验证数据库完整性；失败会恢复备份，不会调用 Actor、AI 或真实来源。' },
    ],
  },
  {
    date: '2026-08-23',
    title: 'ActorOps 历史运行可离线安全退役',
    summary: '旧任务、授权与遗留路线可在停机窗口内核查和收敛，不会重新启动 Actor、改写历史费用或影响现役来源。',
    items: [
      { title: '只结束从未启动的旧任务', description: '未开始的旧发现、验证、Canary 或新鲜度任务会明确标记为已退役；已领取、可能已启动或费用不明的记录保持隔离，只有由操作员精确确认后才可继续离线处置。' },
      { title: '先备份再核验', description: '离线操作要求 API/Worker 已停止并跨过心跳安全窗，先创建私有备份与脱敏收据；未知启动、未结费用、数据库漂移或非终态事实都会阻断，不会删除历史表或发起网络调用。' },
    ],
  },
  {
    date: '2026-08-23',
    title: 'ActorOps Worker 不再执行旧任务',
    summary: '历史验证、发现与新鲜度任务不会重新排队或重复付费；现役抓取继续由 v2 路径处理。',
    items: [
      { title: '旧任务安全结束或隔离', description: '从未启动的旧 ActorOps 任务会明确标记为已退役；可能已启动、有关联运行或费用仍待确认的记录保持隔离，等待离线核查，不会自动重试。' },
      { title: '普通来源继续工作', description: 'RSS、GitHub、单来源获取和信息流刷新不再依赖历史 ActorOps 数据库迁移或后台维护；ActorOps v2 的独立维护失败也不会阻断它们。' },
    ],
  },
  {
    date: '2026-08-22',
    title: 'ActorOps 旧管理接口正式退役',
    summary: '旧 Pool、Canary、Freshness、Discovery 与 X profile 管理接口现在明确返回已退役提示，兼容操作继续直接使用 v2 状态。',
    items: [
      { title: '兼容链接不再触发旧运行时', description: '刷新 Candidate、切换备用 Candidate、调整费用上限和启用已就绪 Binding 保留原有安全 URL，但只读写 v2 Route、Candidate、Discovery 与 Binding。' },
      { title: '旧操作返回明确结果', description: '已退役的管理 URL 需要管理员身份，并固定返回不可重试的 410；页面和普通 RSS、GitHub 获取不会被这些历史接口影响。' },
    ],
  },
  {
    date: '2026-08-22',
    title: 'ActorOps 管理视图切换到 v2',
    summary: 'Route、候选、Binding、费用与维护信息现在从 v2 事实直接投影，旧诊断记录不再混入当前控制面。',
    items: [
      { title: 'Route 状态来自当前 v2 数据', description: '管理列表和详情统一显示 v2 Route、主用/备用/最近成功候选、Binding 准备状态、Discovery、维护预算与替换计划；不会显示目标、Manifest、密钥或远端 Run/Dataset 标识。' },
      { title: '不可用状态更明确', description: '缺少所需 v2 数据库迁移会明确提示先完成迁移；其他暂时不可用也会以独立状态显示。普通 RSS、GitHub 与既有信息流不受影响。' },
      { title: '操作记录只保留安全动作', description: 'ActorOps 时间线只展示脱敏的 v2 管理动作，不再读取旧 Canary、Pool 或诊断事件。' },
    ],
  },
  {
    date: '2026-08-22',
    title: 'ActorOps 控制面不再回退旧版',
    summary: '设置页现在只调用 v2 Route、详情、替换、告警和脱敏操作记录；旧 Pool、Canary、Freshness 控制不再出现在浏览器。',
    items: [
      { title: '路线状态只有启用或停用', description: '界面只显示 active 或 disabled；遗留 shadow 值会安全显示为停用和迁移提示，不会触发旧路线或远端调用。' },
      { title: '详情按需读取且保持脱敏', description: '展开某条 Route 才读取 Candidate、Binding、Attempt、Discovery、维护与 Replacement；目标、Manifest、密钥和远端 Run/Dataset 始终不显示。' },
      { title: '迁移和退役错误可安全处理', description: '缺少 v2 migration、暂时不可用或旧接口 410 都会显示独立状态，不会造成整页崩溃，也不会影响普通 RSS 或 GitHub。' },
    ],
  },
]
