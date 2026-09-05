import type { OpenClawWorkspaceSession } from '../workspace/openclawWorkspaceContracts'

const machineName = /^(?:Inscope|Inteliscope) · .+ · [a-f0-9-]+$/iu

function readable(value: string | undefined, key: string): string | undefined {
  const text = value?.replace(/\s+/gu, ' ').trim()
  return text && text !== key && !machineName.test(text) ? text : undefined
}

export function openClawSessionTitle(session?: OpenClawWorkspaceSession, firstQuestion?: string): string {
  if (!session) return '新对话'
  const title = readable(session.label, session.key) ?? readable(session.displayName, session.key) ?? readable(session.derivedTitle, session.key)
  if (title) return title
  const excerpt = firstQuestion?.trim() || session.lastMessagePreview?.trim()
  if (excerpt) return excerpt.replace(/\s+/gu, ' ').slice(0, 60)
  const timestamp = session.createdAt ?? session.updatedAt
  if ([session.label, session.displayName].some((value) => value && machineName.test(value)) && timestamp && Number.isFinite(timestamp)) return `对话 · ${new Date(timestamp).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })}`
  return '新对话'
}
