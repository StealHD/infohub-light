export type ComposerTrigger = { start: number; end: number; prefix: '@' | '/'; query: string }
export type ComposerCommand = 'skills' | 'new' | 'model' | 'reasoning' | 'worktree' | 'status' | 'help'
export const composerCommands: { id: ComposerCommand; title: string; description: string }[] = [
  { id: 'skills', title: '选择技能', description: '查看和选择可用 Skills' },
  { id: 'new', title: '新建对话', description: '开启新对话，保留草稿' },
  { id: 'model', title: '选择模型', description: '切换当前对话模型' },
  { id: 'reasoning', title: '推理强度', description: '调整思考深度' },
  { id: 'status', title: '查看状态', description: '连接、模型与运行状态' },
  { id: 'help', title: '帮助', description: '/help · 查看快捷操作说明' },
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
