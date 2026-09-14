import type { ChangelogEntry } from './changelogTypes'

export const releaseReadinessEntry: ChangelogEntry = {
  date: '2026-09-14',
  title: '深色模式操作文字更清晰',
  summary: '危险操作保持原有位置与样式，深色模式下的文字对比度提高；禁用的会话删除操作能被读屏识别并说明原因。',
  items: [
    { title: '操作位置不变', description: '会话行尾删除 X、确认框和自动化任务操作继续使用原有布局；深色模式下红色操作文字更易辨认。' },
  ],
}
