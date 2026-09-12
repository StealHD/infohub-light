import type { ChangelogEntry } from './changelogTypes'

export const sourceIdentityRecoveryEntry: ChangelogEntry = {
  date: '2026-09-12',
  title: '来源类型与私人身份隔离修复',
  summary: '11 类订阅来源恢复正确分流；同一上游目标可由不同用户分别保存为私人来源，Web 创建失败也可安全续接。',
  items: [
    { title: '11 类来源各走正确流程', description: 'RSS/网站、Bilibili、GitHub 仓库或用户、Reddit 社区或用户、Telegram、Hacker News、X 与 Instagram 等 11 类来源不再误报需要 Web 设置，可按公开配置准备订阅；YouTube 保留官方来源解析。' },
    { title: '私人来源按用户隔离', description: '其他用户已有同一上游目标的私人来源时，当前用户可以建立自己的独立记录；双方看不到也不能接管或改写对方配置。共享范围内的重复来源仍受冲突保护。' },
    { title: '部分失败可原位恢复', description: '来源创建成功但订阅失败时保留表单和已创建来源，重试只恢复订阅。已订阅或已停用来源不会被重复创建、自动启用、改为共享或覆盖设置。' },
  ],
}
