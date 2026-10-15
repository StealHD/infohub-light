import type { ChangelogEntry } from './changelogTypes'

export const agentSessionCleanupEntry: ChangelogEntry = {
  date: '2026-10-13',
  title: '会话恢复与自动清理',
  summary: '刷新保持选中的会话，修正普通新会话的模型继承校验，并分批清理长期闲置会话。',
  items: [
    { title: '刷新恢复准确', description: '切换后正确保存当前会话；删除旧会话后刷新不再额外生成同名新对话，切换、发送和删除共用操作保护。' },
    { title: '模型状态可靠', description: '普通新会话关联主会话时核对模型后恢复使用；真正无法确认的继承仍提示处理，不隐藏风险。' },
    { title: '闲置会话自动清理', description: '连接托管工作区时，空白会话闲置 7 天、其他会话闲置 90 天后分批永久删除；保留正在使用、运行中、主会话、自动任务、工作树及被引用的父会话。可在全部会话中关闭。' },
  ],
}
