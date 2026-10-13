import type { ChangelogEntry } from './changelogTypes'

export const emailTransportReadyEntry: ChangelogEntry = {
  date: '2026-10-13',
  title: '邮件通知移除隐藏总开关',
  summary: '邮件配置验证通过后通道自动可用，不再被旧版独立启用状态阻断。',
  items: [
    { title: '测试结果与可用状态一致', description: '有效的已验证邮件配置无需再开启独立总开关；更换账号或凭据后仍须重新测试。' },
    { title: '通知范围继续由你选择', description: '通知服务的暂停、个人通知设置和来源铃铛继续生效；系统不会自动添加收件人、开启来源通知或创建历史补发任务。' },
  ],
}
