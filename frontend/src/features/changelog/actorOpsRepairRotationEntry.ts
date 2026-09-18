import type { ChangelogEntry } from './changelogTypes'

export const actorOpsRepairRotationEntry: ChangelogEntry = {
  date: '2026-09-18',
  title: 'Actor 自动修复会轮换待验证候选',
  summary: '修复任务优先验证正在等待的候选；一次实测没有取得内容证据时，下轮会尝试其他候选。',
  items: [
    {
      title: '避免重复探测同一个空结果',
      description: '已确认故障的备用 Actor 会继续等待安全的非空实测证明；维护任务不会因固定排序反复探测同一候选而让其他候选一直排不上。',
    },
  ],
}
