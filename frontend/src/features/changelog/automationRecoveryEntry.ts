import type { ChangelogEntry } from './changelogTypes'

export const automationRecoveryEntry: ChangelogEntry = {
  date: '2026-09-11', title: '自动化测试与模型刷新增加执行确认',
  summary: '测试提交前核验分析服务，模型刷新等待目录真正同步，并保留可恢复的测试记录。',
  items: [
    { title: '手动测试独立执行', description: '新安装默认只执行明确提交的手动测试；服务离线或执行关闭时说明原因，旧排队测试需重新确认。重复提交复用同一次测试，页面刷新可恢复进度，结果未知时保留核对入口。' },
    { title: '模型刷新有真实回执', description: '新增模型经过执行器发现和回传后才进入目录；明确保留管理员限制。刷新完成、无变化、失败和超时分别提示，保留原模型选择与草稿。' },
  ],
}
