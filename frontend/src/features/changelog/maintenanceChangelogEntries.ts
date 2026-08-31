import type { ChangelogEntry } from './changelogTypes'

export const sourceFetchPreflightChangelogEntry = {
  date: '2026-08-30',
  title: '来源获取不再把未启动误报为失败',
  summary: '后台 Worker 未就绪时会明确说明任务没有创建，而不是把来源标成获取失败。',
  items: [
    { title: '未开始与真实失败分开', description: 'Worker 心跳过期或状态无法确认时使用“获取未开始”警告，并说明没有创建任务或产生抓取费用；只有已经进入获取链路的失败才继续显示“获取失败”。' },
  ],
} satisfies ChangelogEntry

export const codeHealthMaintenanceEntry = {
  date: '2026-08-13',
  title: '内部结构更易维护，用户流程保持不变',
  summary: '代码规模开始按现有旧债逐步收紧，数据库连接、API 边界和低频界面加载方式同步收敛；现有页面、接口、审批与数据语义不变。',
  items: [
    { title: '新增代码规模棘轮', description: '生产文件和函数采用项目适配的软线与硬线；已有巨型模块登记精确旧债，只能持平或缩小，新代码不能借用旧债额度，也不要求为了新增功能随意删除等量代码。' },
    { title: '发布前先拆分历史单体', description: '发布前发现历史 Store、测试或界面单体接近上限时，会先将独立查询、测试 fixture 或展示派生逻辑拆到专用模块，再继续发版；这只收紧内部维护边界，不改变现有页面、Actor 审批或抓取行为。' },
    { title: '连接与模块边界更可靠', description: '服务关闭和测试结束会可靠释放数据库连接；系统认证、成员管理、Feed 读取与媒体授权、Feed/来源周期、用户订阅与来源健康、存储治理、Jobs、Agent 连接、通知服务/目标/个人设置、工作区邮件/Telegram transport、Actor 告警设置/事件、Apify Key Pool、SecretStore、Catalog 只读元数据与来源成员关系 HTTP 适配，以及 ActorOps Route/Revision/Canary 安全投影与只读 route、pool、新鲜度、事件、Canary plan 和 batch 查询适配、Worker 的迁移、路由恢复、周期入队、来源与 Feed handler、Actor 校验、新鲜度、发现与 Canary handler、生命周期与媒体发布、通知 backlog、claim-token 事务终结以及 commit 后通知/终态遥测、Store/Feed 边界以及 ActorOps 展示和确认逻辑拆到更小的内部模块。未挂载的旧表单、无调用 helper 和重复请求封装已删除，后端兼容端点继续保留。' },
    { title: '低频界面改为按需加载', description: '登录、Settings 外壳与 OpenClaw 对话视图按需分包，首屏 JavaScript 门禁收紧到 240 KiB；OpenClaw 后台运行和重连状态仍由常驻外壳保持。TypeScript 会阻止未使用代码，Fast Refresh 也改为零警告门禁。' },
  ],
} satisfies ChangelogEntry

export const pageHeaderChangelogEntry = {
  date: '2026-08-26',
  title: '全站顶部标题栏统一透明圆角',
  summary: '所有已登录页面使用同一半透明胶囊标题栏，圆润边界和页面操作保持一致。',
  items: [
    { title: '全部页面使用同一玻璃表面', description: '信息流、收藏、历史、订阅、助手连接、成员、设置、手册和更新日志都使用 44 px 半透明圆角标题面，保留轻边界与背景模糊。' },
    { title: '真实内容滚动穿透', description: '52 px 避让空间归入页面滚动内容：页面位于顶部时正文不会遮挡标题，滚动后卡片会实际进入半透明胶囊背后并被模糊；订阅工具栏的首屏间距同步收紧，不再用一整条固定黑色顶栏占位。首次加载、应用外壳和设置工作区保持一致。' },
  ],
} satisfies ChangelogEntry

export const subscriptionCommandBarChangelogEntry = {
  date: '2026-08-26',
  title: '订阅页顶部操作收为一体式工具条',
  summary: '页签、搜索、筛选和新增来源改为一个连续的胶囊操作面，功能、权限和移动端布局保持不变。',
  items: [
    { title: '层级更集中', description: '参考轻量开发者工具栏的连续圆角结构，页签与搜索成为内嵌分组，“新增来源”保留为唯一强调动作，减少原先多个控件漂在同一横线上的松散感。' },
    { title: '标题栏与全站一致', description: '订阅页使用半透明圆角标题面，外侧轨道不再绘制独立背景；首次加载和应用接管后的几何保持一致。' },
    { title: '滚动与窄屏不变', description: '工具条仍会在滚动后轻微收窄并保持半透明；手机继续使用两行布局，搜索占据剩余宽度，筛选和新增来源不被压缩或隐藏。' },
  ],
} satisfies ChangelogEntry

export const sourceAvatarAutoRefreshChangelogEntry = {
  date: '2026-08-30',
  title: '订阅源头像会自动跟随来源更新',
  summary: '正常获取发现可信的新头像后会静默验证并替换，X、Instagram 等付费来源不会因此增加一次 Actor 调用。',
  items: [
    { title: '全部可信来源使用同一更新流程', description: 'X、Instagram、RSS、GitHub、Reddit、YouTube 等来源只要在正常获取中提供与订阅身份一致的头像证据，就会更新登录保护的本地头像；没有新内容也不影响头像识别。' },
    { title: '失败时继续使用旧头像', description: '新候选超时、格式异常或校验失败不会影响内容获取、来源健康、信息流、AI 或通知，页面继续显示上一个可用头像或平台标识。' },
    { title: '完成获取后页面自动换图', description: '来源或信息流获取完成后会重新读取当前头像；内容变化使用新的媒体地址，不需要刷新浏览器或清理缓存。' },
  ],
} satisfies ChangelogEntry

export const instagramSourceAvatarChangelogEntry = {
  date: '2026-08-25',
  title: 'Instagram 来源头像更稳定',
  summary: 'Instagram 获取会在不增加额外 Actor 调用的前提下，尽力保存已验证的来源头像；没有可用头像时继续显示 IG 标识。',
  items: [
    { title: '过期内容也可补齐头像', description: '即使本次没有进入信息流的新帖子，只要正常获取结果包含与所订阅账号一致的有效头像，系统也会通过受保护媒体地址更新来源头像。' },
    { title: '头像异常不影响获取', description: '上游头像字段缺失或格式异常时，内容获取和主备 Actor 切换仍可继续；界面使用 IG 标识作为稳定降级。' },
  ],
} satisfies ChangelogEntry

export const feedSourceLabelChangelogEntry = {
  date: '2026-08-30',
  title: '社交来源名称不再显示成网址',
  summary: '信息流与 Agent 上下文会忽略误写入名称字段的帖子网址，并继续显示可读的平台与账号名称。',
  items: [
    { title: '帖子链接不再占用名称位置', description: '当社交内容的来源名或作者名意外是完整网址时，卡片头部和 Agent 上下文不会渲染该网址；已有可读账号名保持不变。' },
    { title: '缺少名称时使用账号兜底', description: '如果名称字段都只有网址，界面会从经过验证的来源或原文地址提取账号 handle；无法安全识别时只显示平台名称。' },
  ],
} satisfies ChangelogEntry

export const youtubeSourceLabelChangelogEntry = {
  date: '2026-08-31',
  title: 'YouTube 信息流恢复频道名称',
  summary: 'YouTube 视频不再把底层 RSS 类型显示成来源名，既有条目和后续获取都会使用当前频道名称。',
  items: [
    { title: '既有条目立即修正', description: '历史条目仍保存为 RSS 时，信息流、收藏、历史和详情会按来源编号读取当前频道名称，不需要重新抓取或改写旧数据。' },
    { title: '后续获取写入规范名称', description: 'Actor 与公开 Feed 路径统一把频道名称写入展示字段；RSS 仍只作为内部采集类型，不再出现在卡片名称位置。' },
  ],
} satisfies ChangelogEntry

export { systemSettingsChangelogEntry } from './systemSettingsChangelogEntry'
