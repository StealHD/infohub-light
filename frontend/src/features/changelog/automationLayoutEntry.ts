import type { ChangelogEntry } from './changelogTypes'

export const automationLayoutEntry: ChangelogEntry = {
  date: '2026-09-09', title: '自动化任务采用概览优先的详情体验',
  summary: '参考熟悉的任务管理方式，先找任务、看摘要，再按需编辑或测试，减少重复信息和长表单。',
  items: [
    { title: '快速找到任务', description: '支持全部、已开启、已暂停、草稿与已归档筛选，并按名称、描述或来源搜索已加载任务。列表只呈现名称、状态、频率和下次处理时间。' },
    { title: '按需查看详情', description: '概览、测试和运行记录分开；宽屏详情可拖动并按账号记忆宽度，窄屏使用抽屉或底部面板。编辑表单按需显示，草稿和独立启用确认继续保留。' },
    { title: '减少配置步骤', description: '模型选择直接显示，不再需要先展开分组；已归档任务可恢复为未启用草稿，配置和运行记录继续保留。' },
    { title: '测试更聚焦', description: '测试文章通过独立面板从最新信息流中选择；切换任务后继续显示真实服务端进度，结论优先，逐篇依据按需展开，并始终不发送通知。' },
  ],
}
