import type { ChangelogEntry } from './changelogTypes'

export const openclawModelSwitchEntry: ChangelogEntry = {
  date: '2026-09-20', title: '明确模型切换失败原因',
  summary: '模型继承未修复时保留具体原因和恢复指引，避免反复重选。',
  items: [
    { title: '保留恢复原因', description: '区分模型继承未固定、模型不匹配、无法核验、连接中断和权限不足；不再把普通分叉失败误报为对话过长。失败保留原对话、草稿和附件，不自动发送。' },
    { title: '警告持续可见', description: '模型尚未核验时，调整思考强度或 Fast 不会清除模型异常提示。' },
  ],
}
