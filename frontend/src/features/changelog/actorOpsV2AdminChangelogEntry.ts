import type { ChangelogEntry } from './changelogTypes'

export const actorOpsV2AdminChangelogEntries: ChangelogEntry[] = [
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
