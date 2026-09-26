import type { ChangelogEntry } from './changelogTypes'

export const automationConfiguredModelsEntry: ChangelogEntry = {
  date: '2026-09-26', title: '自动化直接使用 OpenClaw 已配置模型',
  summary: '取消额外模型白名单，新增模型无需重复授权。',
  items: [
    { title: '模型配置统一', description: '自动化接入和目录刷新会清除旧模型白名单；在 OpenClaw 配置模型后刷新目录即可选择。模型来源的认证和调用状态仍会影响执行结果。' },
  ],
}
