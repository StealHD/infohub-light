import type { ChangelogEntry } from './changelogTypes'

export const systemSettingsChangelogEntry: ChangelogEntry = {
  date: '2026-08-24',
  title: '管理员可安全热调系统参数',
  summary: '配额、任务、保留、存储和共享采集参数进入统一设置页，也可由独立授权的 OpenClaw 连接预演后修改。',
  items: [
    { title: '21 项参数集中管理', description: 'Owner/Admin 可在“设置 → 系统参数”查看有效值、环境变量、来源、范围、风险和生效时机；修改无需重启，恢复操作只删除数据库覆盖值。' },
    { title: '预演与精确确认', description: '批量修改先展示每项前后值、警告和十分钟有效期，输入页面给出的完整确认短语后才会原子应用；并发变化会要求刷新后重新预演。' },
    { title: 'OpenClaw 权限独立', description: '助手连接新增仅限 Owner/Admin 的“系统管理”类型，包含 13 个只读工具和 3 个系统参数工具，不同时获得订阅写入；服务端开关默认关闭。' },
    { title: '秘密与付费能力继续隔离', description: '密钥、Token、端点、数据库路径、Actor 费用与启用、任意环境变量不在可调范围；参数操作不会直接启动抓取、Actor、AI 或通知。' },
  ],
}
