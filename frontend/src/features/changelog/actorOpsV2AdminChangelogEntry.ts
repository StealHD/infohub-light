import type { ChangelogEntry } from './changelogTypes'

export const actorOpsV2AdminChangelogEntries: ChangelogEntry[] = [
  {
    date: '2026-08-29',
    title: 'ActorOps 用真实 Dataset 完成字段适配',
    summary: '高质量候选会先完成静态分析，再用一次已授权实测的真实输出证明系统可用；嵌套内容和父级身份不再被简单判为不兼容。',
    items: [
      { title: '候选分成三个清晰阶段', description: '商城质量筛选、系统可用性验证和稳定投入使用分别展示；静态 Schema 映射只代表准备完成，真实输出、来源身份和费用事实齐备后才显示系统可用。' },
      { title: '缺公开输出 Schema 也能受控实测', description: '系统会先证明 Actor 的精确 Build、价格和目标输入，再把候选列为“需要真实样本”；一次授权只启动一个 Actor，随后复用同一 Dataset 完成字段映射，不会因为商城 Schema 不完整直接淘汰高质量 Actor。' },
      { title: '持续向后寻找五个相关候选', description: 'X、Instagram、YouTube 会合并多组发布型搜索词，并按用户量、评分、评价、收藏和价格依次免费检查；评论、字幕、关系或预检失败的 Actor 不再挤占五个相关候选名额。' },
      { title: '平铺和嵌套 Dataset 使用同一验证流程', description: 'X、Instagram、YouTube 的发布项可从平铺行或有界嵌套数组读取，并继承直接父级或顶层的作者、账号和频道身份；跨账号内容、无法分类记录或展开溢出仍会安全阻断。' },
      { title: '字段失败自动复用已付费结果', description: '首次实测只因字段映射失败时，费用结算后会在原替换计划中复用同一 Dataset，最多两轮自动重映射和零费用重验；不会启动第二次 Actor，也不会再次要求实测授权。' },
      { title: '失败不再武断淘汰 Actor', description: '两轮适配仍无法证明时会保留 Candidate 并说明嵌套展开、混合记录、Dataset 绑定或观察映射的具体缺口；最终主用或备用应用仍由管理员确认。' },
      { title: '来源证明缺口会显示具体数量', description: '字段适配完成但尚未覆盖全部当前来源时，候选会显示还需验证几个来源；真实合同或运行故障则显示已阻断，不再混成需要样本。' },
      { title: '商城改名不会丢失已付费证明', description: '系统用 Apify 的稳定 Actor 身份关联历史实测，同时继续显示公开商城名称；仅名称或 slug 改变不会要求重新付费，Build 或 Schema 真正变化才重新验证。' },
      { title: '编辑社交来源不会误停用', description: 'X、Instagram 和 YouTube 的启用状态由系统 Binding 管理；保存名称、频道、主题或抓取设置时不再因为隐藏的启用开关而关闭来源。' },
      { title: '字段适配失败不会永久占用替换计划', description: '真实 Dataset 两轮自动映射仍无法证明时，计划会保留具体原因、Dataset、Attempt 和费用后结束；候选不会被误判故障，主用或备用可立即重新选择其他 Actor。' },
      { title: '搜索和替换合并为一个连续任务', description: 'Route 卡统一从“管理 Actor”进入，在同一 Drawer 选择主用或备用、搜索候选、完成免费预检、实测和应用；关闭或刷新后会恢复当前进度，不再需要在隐藏菜单之间来回切换。' },
      { title: '系统推荐候选并持续反馈进度', description: '候选按公开质量和已有系统证据自动推荐，仍可手动改选；Route 卡和 Drawer 会显示搜索阶段、实测来源进度、费用结算状态和下一步操作。' },
      { title: '实测与应用改为明确按钮确认', description: '免费预检通过后按钮直接显示实测最高费用，全部证明完成后按钮明确目标槽位；无需重复输入固定确认短语，服务器预算、固定授权 token 和并发校验保持不变。' },
    ],
  },
  {
    date: '2026-08-27',
    title: 'ActorOps 故障处理与稳定维护形成闭环',
    summary: '路线健康现在按每个已核验来源真正可用的 Actor 路径计算；故障、退避、后台修复、人工替换和头像映射都能从当前路线确认。',
    items: [
      { title: '明确未启动不会反复请求', description: '同一候选在 24 小时内两次证明未启动且费用均为 0 后，后续任务不再选择它；失败任务和凭证预检留下的未启动记录会按精确账本安全收敛，失效任务不能迟到启动，费用未知或缺少证据仍保持待对账。' },
      { title: '路线健康对应每个来源', description: '主备和最近成功 Actor 会结合当前 Binding、来源冷却和故障状态计算；任何来源没有路径即显示不可用，仅剩一条稳定路径则显示降级，避免“槽位有值但实际跑不了”。' },
      { title: '安全维护默认可用', description: '未曾手动调整的工作区和路线会按既有日/月预算开启后台修复；显式关闭会保留，没有可用负责人时只等待授权。修复可搜索、实测和补备用，但不会自动替换主用或备用。' },
      { title: '主用和备用均可人工替换', description: '已确认故障的槽位会直接显示替换入口；替换仍需选择候选、确认实测费用和最终确认，系统不会自动替换。' },
      { title: '空备用可以直接补充', description: '路线卡固定显示备用 1/2；空槽直接提供补充入口并复用同一候选、费用和双确认流程，应用后不会下线现有主用或其他备用。' },
      { title: '故障 Actor 可原位恢复实测', description: '管理员可通过受控 API 对仍在主用或备用槽位的已确认故障 Actor 发起一次有上限的恢复 Probe；成功只恢复调度资格，不替换槽位、不发布 Feed，费用未结或期间出现新故障会继续等待对账。' },
      { title: '实测前先核对精确 Build', description: '维护与人工替换会先免费读取候选冻结的 Build，并分别判断版本、输出合同和价格；合同失效会安排修复，价格超限或验证凭据暂不可用只会延后，不创建付费运行。' },
      { title: '不兼容候选在确认费用前拦截', description: '已确认故障候选会显示原因但不可选择；创建计划前即免费检查全部来源合同与冻结 Build。失败会立即提示中文原因和 0 Attempt、0 Run、0 费用，不再等授权后后台失败。' },
      { title: '合同问题会说明缺少什么', description: '输入合同失败会区分缺少原生目标 ID、handle、主页 URL、Manifest 无效或模板不可渲染；例如只有 X handle 时会直接提示改选支持 handle 的 Actor。' },
      { title: '候选字段按精确 Build 自动匹配', description: '免费搜索会先用确定性规则、再让 AI 逐个分析每个 Actor/Build 的公开输入输出 Schema，并把通过严格校验的映射按 exact Schema 缓存。X 高级搜索可安全编译 from:<账号>，缺帖子 URL 时可由已验证用户名和数字帖子 ID 生成标准 URL；模型不能自行拼模板。' },
      { title: '字段分析按平台理解“新发布”', description: 'X、Instagram 和 YouTube 使用各自的 Actor 类型、输入和输出字段规则；核心只要求稳定 ID、原文链接、发布时间、来源身份及标题或文字，图片是可选增强，详情继续从原文链接查看。评论、字幕、关注关系和纯资料 Actor 会标为其他用途，嵌套内容或独立 Dataset 会保留为待适配，不再武断认定 Actor 损坏。' },
      { title: 'YouTube 不再强制 Actor 重复频道 ID', description: '视频 Actor 已返回视频 ID、链接、时间和标题时，若没有重复返回频道 ID，系统会使用当前订阅已验证的频道身份完成核验；Actor 伪造的保留字段会被覆盖。maxItemsPerUrl 和常见大小写字段、缩略图别名也可直接映射。' },
      { title: 'YouTube 原生来源与 Actor 字段已贯通', description: 'YouTube 频道的 RSS url 与 Actor target 现在使用同一目标身份；常见 channelId、channelUrls、date、title 和 maxResults 可直接映射。确定性 proposal 校验失败时会继续交给 AI，不再直接卡在字段映射待处理。' },
      { title: '字段缺口会具体说明', description: '待映射候选会直接说明缺少帖子作者用户名、订阅账号输入、帖子 ID/URL/发布时间/正文，或 Actor 实际只返回用户资料/关注关系；不会再只显示“输出合同不兼容”。免费映射不会启动 Actor 或产生 Actor 实测费用。' },
      { title: '优先分析高使用量 Actor', description: '免费搜索会合并多个平台能力词并按 Actor 去重，再依据公开用户量、评分、评价数和收藏数选取少量高质量 Build；待映射候选也保留商城名称和质量资料，不再被界面误认为没有抓到。' },
      { title: '实测会检查 Actor 多返回的内容', description: '系统仍只请求一个计费结果和一次运行，但会检查 Dataset 实际返回的前四行；忽略条数限制并混入其他账号内容的 Actor 不会再仅凭第一行通过替换验证。' },
      { title: 'X 常见发布时间格式可直接映射', description: '字段映射选择 created_at 时，同时支持 ISO、Unix 秒/毫秒和 X/Twitter API 常见的带时区英文时间；有效帖子不会再只因时间格式不同被误报为输出合同不兼容。' },
      { title: '映射规则修复后可零费用重验', description: '已结算的替换实测若只因发布时间、作者身份、帖子 URL 或窗口映射失败，可直接只读原 Dataset 重验；原失败和费用保持不变，成功会生成 0 Run、0 Actor 费用的证明，并只补测仍缺少的来源。' },
      { title: '头像字段可从成功结果补齐', description: '系统会在已验证成功的输出中有界查找 HTTP(S) 头像；大对象不会因无关字段提前截断，Instagram 协作帖也不会把协作者头像映射给订阅来源。无效高优先级字段不会遮住后面的有效头像，缺少头像不影响内容结果。' },
      { title: '历史结果补头像不会重复付费', description: '已结算且仍满足身份与合同的 Dataset 可只读重放头像映射；媒体下载在 Worker 异步抓取中也能正确落盘，并只通过登录保护的本地媒体地址展示，不会新增 Apify Run。' },
    ],
  },
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
