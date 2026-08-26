import type { ChangelogEntry } from './changelogTypes'

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
  title: '顶部标题栏边界更清晰',
  summary: '信息流与管理页面的共享标题栏改为轻微内缩的圆角表面，保持原有布局和操作入口。',
  items: [
    { title: '轻微留白，不挤内容', description: '标题栏仍占用原 52 px 布局轨道，但可见表面收为 44 px，并在四周保留小幅空隙、细边框和圆角；Feed、订阅、收藏、历史、成员与助手等页面保持一致。' },
    { title: '刷新前后一致', description: '首次加载的静态界面同步使用相同边界和尺寸，认证完成后切换到应用不会出现顶部几何跳变；现有主题、标题截断和操作按钮不变。' },
  ],
} satisfies ChangelogEntry

export { systemSettingsChangelogEntry } from './systemSettingsChangelogEntry'
