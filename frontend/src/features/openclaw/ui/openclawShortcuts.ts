export type ComposerTrigger = { start: number; end: number; prefix: '@' | '/'; query: string }
export type ComposerCommand = 'skills' | 'new' | 'model' | 'reasoning' | 'worktree' | 'status' | 'help'
export const composerCommands: { id: ComposerCommand; title: string; description: string }[] = [
  { id: 'skills', title: '/skills', description: '选择本次使用的 Skill' },
  { id: 'new', title: '/new', description: '确认新建对话，保留草稿' },
  { id: 'model', title: '/model', description: '选择当前对话模型' },
  { id: 'reasoning', title: '/reasoning', description: '选择推理档位' },
  { id: 'worktree', title: '/worktree', description: '填写独立 Worktree 任务' },
  { id: 'status', title: '/status', description: '查看连接、模型与运行状态' },
  { id: 'help', title: '/help', description: '查看使用示例' },
]
export function findComposerTrigger(text: string, caret: number): ComposerTrigger | null {
  const prefix = text.slice(0, caret)
  const match = prefix.match(/(?:^|\s)([@/])([^\s/@\\:]*)$/u)
  if (!match) return null
  return { start: caret - match[2].length - 1, end: caret, prefix: match[1] as '@' | '/', query: match[2] }
}
export function replaceComposerTrigger(text: string, range: { start: number; end: number }, insertion: string) {
  const next = text.slice(0, range.start) + insertion + text.slice(range.end)
  return next.length <= 1200 ? { text: next, caret: range.start + insertion.length } : null
}
