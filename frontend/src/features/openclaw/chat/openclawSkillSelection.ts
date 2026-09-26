export type OpenClawSkillSelection = { key: string; name: string; gatewayUrl: string; agentId: string }
export class OpenClawSkillValidationError extends Error {}
const referenceName = /^[a-z][a-z0-9_-]{0,63}$/u

export function sanitizeSkillSelection(value: unknown): OpenClawSkillSelection | undefined {
  if (!value || typeof value !== 'object') return
  const item = value as Record<string, unknown>
  if (!['key', 'name', 'gatewayUrl', 'agentId'].every((key) => typeof item[key] === 'string' && item[key].length > 0 && item[key].length <= 256 && !Array.from(item[key]).some((char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127))) return
  if (!sanitizeSkillName(item.name)) return
  try {
    const url = new URL(String(item.gatewayUrl))
    if (!['ws:', 'wss:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) return
  } catch { return }
  return { key: String(item.key), name: String(item.name), gatewayUrl: String(item.gatewayUrl), agentId: String(item.agentId) }
}

export const SKILL_HANDOFF_MARKER = '[INTELISCOPE_SKILL_HANDOFF_V1]'

export const sanitizeSkillName = (value: unknown): string | undefined =>
  typeof value === 'string' && referenceName.test(value) ? value : undefined

export function readSkillHandoff(text: string): { text: string; skillName?: string } {
  let body = text.trim()
  let expandedName: string | undefined
  if (body.startsWith('Use the following explicitly referenced skills for this request. Read each skill\'s SKILL.md before acting:\n')) {
    const match = body.match(/^Use the following explicitly referenced skills for this request\. Read each skill's SKILL\.md before acting:\n- ([a-z][a-z0-9_-]{0,63})\n\nUser request:\n([\s\S]*)$/u)
    if (!match) return { text: '' }
    expandedName = match[1]
    body = match[2]
  }
  if (!body.startsWith(SKILL_HANDOFF_MARKER)) return { text: body }
  const match = body.match(/^\[INTELISCOPE_SKILL_HANDOFF_V1\]\n([^\n]+)\n\$([a-z][a-z0-9_-]{0,63})\n(\[INTELISCOPE_HANDOFF_V8\][\s\S]*)$/u)
  if (!match || (expandedName && expandedName !== match[2])) return { text: '' }
  try { if (JSON.parse(match[1]).name !== match[2]) return { text: '' } } catch { return { text: '' } }
  return { text: match[3], skillName: match[2] }
}

export const unwrapSkillHandoff = (text: string): string => readSkillHandoff(text).text
