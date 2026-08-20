import type { ChangelogEntry } from './changelogTypes'

export const actorOpsAutoPoolChangelogEntry: ChangelogEntry = {
  date: '2026-08-20',
  title: '替换或新增备用 Actor 可一键自动完成',
  summary: '管理员点一次即可让系统自动循环免费搜索、付费验证并在通过后原子生效，直到找到合格 Actor 或用尽本轮预算。',
  items: [
    { title: '一键自动走完全部流程', description: '候选列表新增“一键自动完成（含付费验证）”。系统会自动循环免费搜索、逐个付费验证候选，并在通过后立即原子写入目标槽位，无需再手动分步确认；现有线路在验证期间保持不变。' },
    { title: '失败自动换候选，不再停在候选不足', description: '一轮免费搜索没有可用候选或付费验证全部失败时，系统会自动重新免费搜索并继续验证，而不是停在“候选不足”等待手动重试。' },
    { title: '每轮预算 $0.50 封顶', description: '每次自动完成最多累计 $0.50 付费验证；用尽仍无合格 Actor 会明确停止并保留现有线路，不会无限烧钱。' },
    { title: 'YouTube 与 Instagram 单次上限提到 $0.10', description: 'YouTube 和 Instagram 线路的单次运行上限从 $0.02 提到 $0.10，更多标价在此区间的候选可进入付费验证；X 保持 $0.10 不变。' },
  ],
}
