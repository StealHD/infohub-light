import type { ChangelogEntry } from './changelogTypes'

export const telegramTopicsOpenclawNotificationEntry: ChangelogEntry = {
  date: '2026-09-13',
  title: '通知服务支持 Telegram 话题与自动化 OpenClaw 渠道',
  summary: '同群通知可按话题分流；自动化可只分析不通知，测试通知须主动开启。',
  items: [
    { title: '按话题发送 Telegram 通知', description: 'Telegram 服务可选填话题 ID，留空发送到默认话题；编辑可保留、更换或清除。' },
    { title: '自动化选择 OpenClaw 服务', description: '管理员从 Gateway 已配置渠道与账号创建通知服务，填写只写收件目标并保存测试；任务可选择该服务。' },
    { title: '测试通知需主动开启', description: '新建任务默认不通知；测试默认不发送，勾选后仅分析命中才发送标记为测试的通知，结果未知不自动重试。' },
    { title: '测试可使用自定义文本', description: '测试可直接输入任意示例内容；填写后仅用该文本分析，不改写信息流、任务配置或正式水位。' },
  ],
}
