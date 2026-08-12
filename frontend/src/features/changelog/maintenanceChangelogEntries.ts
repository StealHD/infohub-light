import type { ChangelogEntry } from './changelogEntries'

export const codeHealthMaintenanceEntry = {
  date: '2026-08-13',
  title: '内部结构更易维护，用户流程保持不变',
  summary: '代码规模开始按现有旧债逐步收紧，数据库连接、API 边界和低频界面加载方式同步收敛；现有页面、接口、审批与数据语义不变。',
  items: [
    { title: '新增代码规模棘轮', description: '生产文件和函数采用项目适配的软线与硬线；已有巨型模块登记精确旧债，只能持平或缩小，新代码不能借用旧债额度，也不要求为了新增功能随意删除等量代码。' },
    { title: '连接与模块边界更可靠', description: '服务关闭和测试结束会可靠释放数据库连接；系统认证、成员管理、Feed 读取与媒体授权、Feed/来源周期、存储治理、Jobs 与 Agent 连接 HTTP 适配、Worker 的迁移、路由恢复、周期入队、来源与 Feed handler、Actor 校验、新鲜度、发现与 Canary handler、生命周期与媒体发布、通知 backlog、claim-token 事务终结以及 commit 后通知/终态遥测、Store/Feed 边界以及 ActorOps 展示和确认逻辑拆到更小的内部模块。未挂载的旧表单、无调用 helper 和重复请求封装已删除，后端兼容端点继续保留。' },
    { title: '低频界面改为按需加载', description: '登录、Settings 外壳与 OpenClaw 对话视图按需分包，首屏 JavaScript 门禁收紧到 240 KiB；OpenClaw 后台运行和重连状态仍由常驻外壳保持。TypeScript 会阻止未使用代码，Fast Refresh 也改为零警告门禁。' },
  ],
} satisfies ChangelogEntry
