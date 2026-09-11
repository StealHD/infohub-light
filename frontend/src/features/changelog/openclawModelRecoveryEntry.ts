import type { ChangelogEntry } from './changelogTypes'

export const openclawModelRecoveryEntry: ChangelogEntry = {
  date: '2026-09-11', title: '修复聊天模型继承与失败反馈',
  summary: '切换模型保留上下文，修复默认模型分叉错用父模型的问题。',
  items: [
    { title: '模型切换保护', description: '主动切换模型保留原上下文、草稿和附件，不增加成功提示。无法确认实际选择时保留原对话并显示失败原因，不自动发送。' },
    { title: '失败原因可恢复', description: '区分模型限流、服务暂不可用、认证失败和超时；保留部分回复、实际模型证据及运行编号，刷新后仍可核对。缺失的原因明确显示未知。' },
  ],
}
