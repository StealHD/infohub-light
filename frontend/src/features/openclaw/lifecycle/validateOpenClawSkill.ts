import type { OpenClawLifecycleRefs } from './openclawLifecycleRefs'
import type { OpenClawSendSnapshot } from '../openclawContracts'
import { OpenClawSkillValidationError, sanitizeSkillSelection } from '../chat/openclawSkillSelection'
import { skillInvocationIssue } from '../chat/openclawSkillInvocation'
import { gatewaySupportsMethod } from '../openclawGateway'
import { projectSkillsStatus } from '../workspace/openclawWorkspaceProjection'

export { OpenClawSkillValidationError } from '../chat/openclawSkillSelection'

export async function validateOpenClawSkill(refs: OpenClawLifecycleRefs, snapshot: OpenClawSendSnapshot, gatewayUrl: string) {
  if (!snapshot.selectedSkill) return
  const selected = sanitizeSkillSelection(snapshot.selectedSkill)
  const { client, generation } = refs.connection
  const { agentId, sessionKey } = refs.session
  if (!selected || snapshot.sourceSnapshot || selected.gatewayUrl !== gatewayUrl || selected.agentId !== agentId || !client || !gatewaySupportsMethod(refs.connection.hello, 'skills.status')) throw new OpenClawSkillValidationError()
  const status = await client.request('skills.status', { agentId }).then(projectSkillsStatus).catch(() => { throw new OpenClawSkillValidationError() })
  if (refs.connection.client !== client || refs.connection.generation !== generation || refs.session.sessionKey !== sessionKey || refs.session.agentId !== agentId) throw new OpenClawSkillValidationError()
  const skill = status.skills.find((item) => item.key === selected.key && item.name === selected.name)
  if (!skill || skillInvocationIssue(skill, status.skills)) throw new OpenClawSkillValidationError()
}
