export type ChangelogItem = {
  title: string
  description: string
}

export type ChangelogEntry = {
  date: string
  title: string
  summary: string
  items: ChangelogItem[]
}

export type ChangelogMonth = {
  id: `month-${number}-${string}`
  label: string
  entries: ChangelogEntry[]
}

export const changelogMonths: ChangelogMonth[] = [
  {
    id: 'month-2026-07',
    label: '2026 年 7 月',
    entries: [
      {
        date: '2026-07-28',
        title: '可直接订阅 YouTube 公开频道',
        summary: '频道链接、@handle、频道 ID 和规范 Feed 都会归一到同一来源，并继续复用现有订阅、获取、健康与通知流程。',
        items: [
          { title: '频道输入更灵活', description: '新增来源中提供“YouTube 频道”，支持公开频道链接、@handle、UC 开头的频道 ID 和规范 Feed 地址；不同写法不会重复创建同一频道。' },
          { title: '公开视频完整收录', description: '普通视频、Shorts、公开直播与回放都按频道公开 Feed 进入信息流，并统一显示为 YouTube 频道视频。' },
          { title: '首次只补一条', description: '默认开启“保留最新内容”；首次时间窗口为空时只保留最近一条，不会批量导入频道历史。' },
          { title: '无密钥安全解析', description: 'handle 仅通过固定 YouTube 公共页面进行一次有界解析，不使用 API Key、Cookie 或登录状态；失败会在创建弹窗中给出可操作提示且不会保存半成品来源。' },
          { title: '现有流程保持一致', description: '创建并订阅后不自动抓取；可继续使用“立即获取”、自动计划、来源健康和新内容通知。既有规范 YouTube RSS 会自动显示为 YouTube 频道。' },
        ],
      },
      {
        date: '2026-07-26',
        title: '状态更安静，中文输入不再误发',
        summary: '高密度状态和卡片操作改为图标与渐进披露，设置目录移到桌面侧栏，并修复 OpenClaw 中文输入法确认候选时提前发送。',
        items: [
          { title: '输入法 Enter 修复', description: '中文输入法仍在确认候选时，Enter 只完成输入，不会发送未写完的消息；普通 Enter 与 Shift+Enter 仍分别发送和换行。' },
          { title: '状态图标与说明', description: '来源健康、运行记录、自动更新、助手连接和 OpenClaw 顶栏只保留明确图标；鼠标停留或键盘聚焦时在上方显示完整说明，错误和运行轨迹仍保留文字。' },
          { title: '来源卡直接操作', description: '通知、订阅设置和编辑来源分别使用 Bell、Settings 和 Pencil 图标；“更多”只在允许分享时出现，且只保留分享。' },
          { title: '连接危险操作收口', description: '复制、重命名、吊销或删除集中到中性“更多”菜单，并按连接状态裁剪；只有最终确认按钮使用红色实心样式。浏览器解绑也改为中性 Unplug 图标并保留二次确认。' },
          { title: '订阅统计迁入概览', description: '三个订阅页签不再长期显示数量；信息概览独立加载我的订阅、来源库和最近最多 100 条运行记录，读取失败不会闪成 0，点击可直达对应页签。' },
          { title: '桌面设置悬浮目录', description: '设置正文恢复单列；桌面从左侧“设置”悬浮或键盘聚焦打开分区目录，手机和触摸设备继续使用页内选择器，分区链接支持直接定位。' },
          { title: '后台健康判定更稳', description: 'Worker 健康检查为低配服务器留出完整启动探针时间，避免进程持续更新心跳时仍被误标为不可用。' },
        ],
      },
      {
        date: '2026-07-26',
        title: '等待过程可见，关键交互更可靠',
        summary: 'OpenClaw 会立即反馈运行过程，状态和元数据不再挤成相同胶囊，并补齐移动端、信息流、订阅与设置中的高频可用性缺口。',
        items: [
          { title: 'OpenClaw 运行轨迹', description: '发送后立即显示安全的处理中状态，并按需折叠展示读取、比较和工具步骤；原始思维、工具参数、结果和敏感值不会进入页面或历史。' },
          { title: '全部与异常视图', description: '我的订阅默认显示“全部”，并固定提供只包含需关注与连续失败的“异常”；即使暂时为零也可直接进入，移动端保持一致。' },
          { title: '来源操作分层', description: '编辑来源保持为直接图标，“更多操作”只在允许分享时出现；新内容通知仍在卡片直接切换，失败会恢复原状态，设置弹窗不再重复覆盖通知选择。' },
          { title: '获取按钮不再跳动', description: '“立即获取”在提交、排队和运行期间保持文字与宽度不变，以旋转图标、禁用状态和辅助技术文案表达进度。' },
          { title: '首次窗口可选', description: 'Owner/Admin 可把 RSS 首次抓取窗口设为 7 天或 30 天；新直接 RSS 与 RSSHub 来源首次成功后自动恢复日常窗口，抓到零条也视为成功。' },
          { title: '状态与元数据分型', description: '连接、运行和来源健康使用带辅助说明的状态图标；频道、主题、范围、权限和数量改用各自的轻量语义，不再共用微型胶囊。' },
          { title: '信息流交互补全', description: '“重新载入”和“获取新内容”明确分工；收藏与忽略提供 8 秒撤销，卡片菜单保持单实例并在关闭后归还焦点，多图支持缩略图、触摸切换和局部重试。' },
          { title: '移动端账户入口', description: '底部导航新增“更多与账户”，集中提供账户、设置、文档和退出入口，并适配系统安全区。' },
          { title: '加载与设置更稳', description: '自动更新检查不再闪现假失败；设置页提供分区导航、局部重试和未保存提醒，慢请求与局部错误不会遮挡整页。' },
        ],
      },
      {
        date: '2026-07-26',
        title: '浏览器 OpenClaw 可完成受控订阅',
        summary: '直接对话与文章/任务交接采用不同安全模式，创建订阅不再被只读提示词误拦截。',
        items: [
          { title: '直接请求可生成预览', description: 'Agent 面板没有附带文章或任务时，订阅请求会按用户原话交给 OpenClaw，并继续使用 Inteliscope Skill 与 MCP 的 prepare 流程。' },
          { title: '准确确认后才写入', description: '普通请求只展示安全预览与服务端返回的准确确认短语；只有下一条消息完全匹配该短语时才可 apply，浏览器不会替用户生成或改写。' },
          { title: '上下文交接仍只读', description: '附带文章或运行记录的分析继续只读取持久化安全证据，并禁止重试、取消、修复或其他写操作。' },
        ],
      },
      {
        date: '2026-07-25',
        title: 'Bilibili 订阅接入自建 RSSHub',
        summary: 'VPS 运行一套带访问控制的 RSSHub，本地与 VPS 项目可复用，并可在设置中切换到第三方实例。',
        items: [
          { title: '服务地址可切换', description: 'Owner/Admin 可在设置页维护 RSSHub Base URL；来源身份与服务地址分离，切换自建或第三方实例无需重建订阅。' },
          { title: 'OpenClaw 自行解析账号', description: '直接提供 Bilibili 账号名称即可通过 Inteliscope MCP 查询公开候选，无需启用 Chrome 或浏览器远程调试；唯一精确同名会解析为 UID 并进入订阅预览，同名多候选必须由用户选择，不再默认要求手工查 UID。' },
          { title: '查询数据严格收口', description: '名称查询只返回最多 5 个名称、UID、官方主页和精确匹配标记，不接收账号 Cookie，也不返回签名、粉丝数、视频数或上游正文。' },
          { title: 'Skill 自动刷新', description: '重新运行本地 OpenClaw 初始化会比较已安装 Skill 与仓库版本；发现旧版时覆盖更新并重启 Gateway，新会话不会继续沿用“手填 RSSHub URL”的旧规则。' },
          { title: '鉴权公网复用', description: 'RSSHub 容器只绑定 VPS loopback，由现有 Nginx 提供 HTTPS；本地直接访问公网入口，来源测试与 Worker 抓取使用路由级 code，主密钥不进入结果、日志或 OpenClaw。' },
          { title: '既有状态原位迁移', description: '精确匹配的 Bilibili URL 可原位转成受控路由，保留来源、订阅与自动更新计划 ID，并在写入前备份配置和数据库。' },
        ],
      },
      {
        date: '2026-07-25',
        title: '共享内容隔离与安全清理',
        summary: '共享来源继续复用已获取的正文，但每位成员只得到自己的订阅投影，媒体文件也只在数据库提交成功后清理。',
        items: [
          { title: '订阅偏好重新投影', description: '复用共享来源历史内容时，标题只采用独立保存的来源原始标题，频道、主题、个人标签、优先级和分析模式全部来自当前账户的目标订阅；缺少可信原始标题的旧内容不会预填，其他成员的 AI 翻译标题、偏好、精选状态和阅读状态也不会进入当前信息流。' },
          { title: '共享获取保持中性', description: '工作区级获取缓存只保留来源内容，写入前会清除生产者的 AI 结果和用户投影；缓存命中后再按当前订阅生成展示字段。' },
          { title: '媒体提交后清理', description: '过期内容的媒体数据库记录先随维护事务删除，文件只在提交成功后以尽力而为方式清理；SQL、提交或进程中断导致回滚时文件仍然保留。' },
          { title: '连接告警可观测', description: '完整测试门禁开始统计未关闭 SQLite 连接的 ResourceWarning，当前仅观测数量，便于后续持续收敛而不改变现有发布阈值。' },
        ],
      },
      {
        date: '2026-07-24',
        title: '侧栏弹出菜单更整齐',
        summary: '头像和文档入口保持原位，点击后出现的菜单收进侧栏范围。',
        items: [
          { title: '弹层内收', description: '账户菜单和文档菜单使用一致宽度，在展开侧栏内保留稳定的左右留白。' },
          { title: '入口保持原位', description: '头像、账户栏和右侧文档图标不移动，两个菜单继续从对应入口向上展开。' },
        ],
      },
      {
        date: '2026-07-24',
        title: 'OpenClaw 安全诊断事件',
        summary: '排查任务和关键操作时可以取得更连贯的脱敏事件，同时保持日志与账户严格隔离。',
        items: [
          { title: '按关联线索排查', description: 'OpenClaw 可在明确排障请求中按最近时间、任务、来源、订阅或请求关联查看安全事件，帮助串联排队、执行、获取和通知结果。' },
          { title: '只限当前账户', description: '只读与订阅管理连接都只能取得与当前账户相关的事件；Owner 或 Admin 连接也不能代查其他成员。' },
          { title: '原始日志不展示', description: '页面不新增日志列表或日志正文；原始消息、文件路径、身份、文章内容、URL、凭据和堆栈不会交给 OpenClaw。' },
          { title: '连接配置同步', description: '只读连接现在包含 11 个安全工具，订阅管理连接包含 15 个；原有 prepare、准确确认和 apply 边界不变。' },
        ],
      },
      {
        date: '2026-07-24',
        title: '信息流更新后立即呈现',
        summary: '后台获取完成后先载入最新信息流，以实际新增数量反馈结果，并提供稳定且不触发抓取的数据刷新入口。',
        items: [
          { title: '完成后再反馈', description: '整份更新或单个来源“立即获取”成功后，会先读取最新信息流，再显示去重合并后实际新增了多少条，避免总量已经变化而卡片仍停留在旧数据。' },
          { title: '刷新与更新分工', description: '信息流新增“刷新”按钮，只读取已有最新快照且所有成员可用，不会请求上游来源；加载期间文字和位置保持不变。原“更新”继续启动后台来源抓取，并遵循现有角色权限。' },
          { title: '失败时保留内容', description: '最新快照暂时加载失败时继续保留当前可信卡片，并提示回到信息流手动刷新，不会用空白或错误页替换阅读内容。' },
          { title: '阅读位置不跳动', description: '数据刷新和后台更新都会保留当前阅读锚点；离开新鲜边缘时，新到内容继续通过“N 条新内容”提示等待查看。' },
          { title: '常用控件更顺手', description: '外观按钮移到信息概览左侧；卡片使用明确的展开/折叠线框图标，底部操作说明优先显示在按钮上方。' },
        ],
      },
      {
        date: '2026-07-24',
        title: '订阅与运行记录更清爽',
        summary: '用更清楚的来源卡、筛选下拉和自动更新开关减少订阅页的信息拥挤。',
        items: [
          { title: '频道聚焦', description: '“我的订阅”和“来源库”分别记住当前频道；搜索或筛选使频道暂时无结果时，会自动回到首个有内容的频道，桌面选中标识也保持清晰对比。' },
          { title: '来源卡片', description: '来源卡只保留名称、类型、范围、HeroUI 健康状态标签、更新摘要和主操作；低频“查看引用”入口已移除，分享与编辑继续按权限放在明确的“更多”菜单。' },
          { title: '筛选与自动更新', description: '来源筛选改为原位下拉面板；全部订阅自动更新的纯开关固定在右上角，更新周期单独位于右下角，手机端也能直接操作。' },
          { title: '紧凑运行记录', description: '任务结果与创建、完成时间集中在一行展示；技术详情和响应结构通过带箭头、明确展开反馈的独立按钮按需显示。' },
        ],
      },
      {
        date: '2026-07-24',
        title: '主流邮件服务统一发件配置',
        summary: '由工作区管理员统一配置发件服务，成员只需填写自己的收件邮箱。',
        items: [
          { title: '五种服务商预设', description: '支持 QQ、网易、Gmail、Resend 与 Amazon SES；服务器、端口和 SSL 方式由系统固定派生，不开放任意 SMTP 地址。' },
          { title: '保存、测试、启用', description: '配置或凭据变化会自动停用；只有当前配置成功发送测试邮件后才能启用，凭据与测试收件人提交后立即清空且不回显。' },
          { title: '暂停不补发', description: '邮件服务未就绪时保留用户原有邮箱通知选择，但不会产生邮件队列；恢复后只通知之后真正新增的内容，Webhook 不受影响。' },
          { title: '凭据隔离', description: '授权码、App Password、API Key 与 SES SMTP Password 只写入 SecretStore；设置页和接口只显示安全配置状态。' },
        ],
      },
      {
        date: '2026-07-24',
        title: '偏好来源新内容通知',
        summary: '为明确选择的来源增加邮箱或 Webhook 主动通知，同时把历史数据留在信息流而不补推。',
        items: [
          { title: '账户接收方式', description: '每个账户可在设置页选择邮箱或 Webhook，保存后只显示是否已配置，并可发送一条不抓取来源的模拟测试通知。' },
          { title: '按来源开启', description: '订阅设置新增“从现在开始接收新内容通知”；开启后的来源卡片会显示通知状态。' },
          { title: '旧数据保护', description: '首次快照、历史或复用内容、停用期间的内容以及 personal_only 来源不会补推，只投递启用后确认的新条目。' },
          { title: '投递与获取隔离', description: '通知在信息流结果提交后独立发送；接收端失败不会让已经成功的来源获取被重复执行。' },
        ],
      },
      {
        date: '2026-07-24',
        title: '运行诊断与阅读细节完善',
        summary: 'OpenClaw 能取得更充分的安全任务证据，图片、概览和常用控件在窄空间下也更容易操作。',
        items: [
          { title: '运行记录直接诊断', description: '从运行记录加入 OpenClaw 后会读取安全的原因、证据和恢复建议，不再只停留在任务状态摘要，也不会自动重试或修改任务；窄屏上下文保持紧凑且不横向溢出。' },
          { title: '图片全图预览', description: '多图缩略格不再裁掉竖图；点击可查看完整图片，并通过左右按钮或方向键循环切换。' },
          { title: '更大的展开区域', description: '卡片使用图标式展开提示，标签和 Footer 空白也能展开；收藏、原文、Agent 与更多操作仍保持独立。' },
          { title: '概览先利用空白', description: '手动打开信息概览时，阅读列会先使用左侧空余空间让位，到达安全边界后才覆盖卡片。' },
          { title: '管理操作反馈', description: 'Apify 额度刷新会显示忙碌状态；OpenClaw 连接按钮保持同行，MCP 配置代码块也会对齐并安全换行。' },
        ],
      },
      {
        date: '2026-07-23',
        title: '操作手册与发布入口',
        summary: '把使用说明、产品更新和正式 Release 放到随时可达的账户区域，并建立合并文档门禁。',
        items: [
          { title: '操作手册', description: '新增源码受控的操作手册，覆盖订阅、阅读、运行记录、Agent、账户设置和常见状态排查。' },
          { title: '向上账户菜单', description: '侧栏底部头像菜单改为垂直向上展开；折叠导航也能直接进入操作手册、更新日志和 Release 发布页。' },
          { title: '文档与发布菜单', description: '展开侧栏后，账户右侧提供独立的向上菜单，可在操作手册、更新日志和 GitHub Release 页面之间选择。' },
          { title: '合并自动检查', description: '每次产品代码合并都由 Test Gate 验证操作手册与更新日志已同步复核，缺少任一项时检查失败。' },
        ],
      },
      {
        date: '2026-07-23',
        title: '操作结果不再挤压页面',
        summary: '保存、更新与任务结果统一从页面顶部短暂出现，正文和列表保持原位。',
        items: [
          { title: '顶部操作反馈', description: '设置、订阅、Agent、成员和 Feed 的操作结果会以可关闭提示短暂出现，不再推动页面内容。' },
          { title: '失败可直接重试', description: '刷新或来源任务失败且允许重试时，可直接在提示中重试；重复点击不会创建并行操作。' },
          { title: '表单仍在原位修正', description: '字段校验、弹窗内错误与排队或运行状态继续显示在对应控件附近，方便就地处理。' },
        ],
      },
      {
        date: '2026-07-22',
        title: '更清晰的交互反馈',
        summary: '让常用操作更靠近触发位置，状态变化更明确，工作区切换也更平稳。',
        items: [
          { title: '近邻提示', description: '鼠标与键盘触发的说明现在优先显示在控件右侧；空间不足时会自动换向或移动，异常详情也不再跑到页面角落。' },
          { title: '上下文选中态', description: '加入 Agent 上下文的按钮默认保持中性，仅在选中后显示紫色强调，并通过按压状态向辅助技术确认结果。' },
          { title: '柔和的工作区变化', description: '左右侧栏使用一致的短过渡；关闭 Agent 面板时先停止交互，再在动画结束后卸载内容。' },
          { title: '稳定的发送位置', description: 'OpenClaw 发送按钮切换为停止状态时保持在同一位置，连续操作不再引起工具栏跳动。' },
          { title: '可预期的信息流', description: '切换发布时间、入库时间或排序方向后，信息流会回到当前排序的新鲜边缘；筛选与刷新仍保留阅读位置。' },
          { title: '明确的明暗外观', description: '页头可以显式选择白天或黑夜模式；选择会在应用加载前恢复，不再被后续系统外观变化覆盖。' },
        ],
      },
      {
        date: '2026-07-22',
        title: '更新日志上线',
        summary: '产品内可以直接查看 Inteliscope 的重要体验变化。',
        items: [
          { title: '本地版本记录', description: '更新内容与代码一同维护，按月份组织；桌面端提供右侧时间线，窄屏使用横向月份选择器。' },
        ],
      },
    ],
  },
]

export const defaultChangelogMonthId = changelogMonths[0].id

export function isChangelogMonthId(value: string): value is ChangelogMonth['id'] {
  return changelogMonths.some((month) => month.id === value)
}
