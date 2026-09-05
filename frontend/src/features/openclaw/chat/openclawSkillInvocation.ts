import type { OpenClawSkill } from '../workspace/openclawWorkspaceContracts'
import type { OpenClawSkillSelection } from './openclawSkillSelection'

const normalizedName = (name: string) => name.toLowerCase().replace(/[\s_]+/gu, '-')
export function skillInvocationIssue(skill: OpenClawSkill, skills: OpenClawSkill[]): string | null {
  if (!skill.enabled) return '已停用'
  if (skill.blockedByAllowlist || skill.blockedByAgentFilter) return '当前 Agent 不可用'
  if (!skill.eligible) return '条件不足'
  if (skill.userInvocable !== true || skill.commandVisible !== true || skill.modelVisible !== true) return '未证明可显式调用'
  if (!/^[a-z][a-z0-9_-]{0,63}$/u.test(skill.name)) return '名称暂不支持快捷调用'
  if (skills.filter((entry) => normalizedName(entry.name) === normalizedName(skill.name)
    || normalizedName(entry.name.toLowerCase().replace(/[^a-z0-9_]+/gu, '_')) === normalizedName(skill.name)).length !== 1) return '名称无法唯一匹配'
  return null
}

// Escape incidental references in ordinary text and untrusted material metadata.
export function escapeSkillReferences(text: string): string {
  return text.split('\n').map((line) => line.startsWith('{') ? line.replace(/\$/gu, '\\u0024') : line.replace(/\\*\$([-a-zA-Z0-9_:]+)/gu, (match) => `\\${match.replace(/^\\+/u, '')}`)).join('\n')
}

export function wrapSkillHandoff(prompt: string, skill: OpenClawSkillSelection): string {
  return `[INTELISCOPE_SKILL_HANDOFF_V1]\n${JSON.stringify({ name: skill.name })}\n$${skill.name}\n${escapeSkillReferences(prompt)}`
}
