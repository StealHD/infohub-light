import { describe, expect, it } from 'vitest'
import { projectSkillsStatus } from './openclawWorkspaceProjection'

// OpenClaw 2026.8.1 buildWorkspaceSkillStatus wire shape, with synthetic values.
const skill = { skillKey: 'report-key', name: '报告助手', description: '整理阅读报告', disabled: false, eligible: true,
  blockedByAllowlist: false, blockedByAgentFilter: false, missing: { bins: [], anyBins: [], env: [], config: [], os: [] },
  install: [], filePath: '/private/SECRET_SENTINEL', apiKey: 'SECRET_SENTINEL' }

describe('skills.status installed Gateway compatibility', () => {
  it('reads disabled and exact skillKey without projecting paths or secrets', () => {
    const result = projectSkillsStatus({ skills: [skill] })
    expect(result.skills[0]).toMatchObject({ key: 'report-key', enabled: true, eligible: true })
    expect(JSON.stringify(result)).not.toContain('SECRET_SENTINEL')
    expect(result.uploadedArchivesAllowed).toBe(false)
  })
  it('preserves disabled, agent-filtered, and missing requirement states', () => {
    const result = projectSkillsStatus({ skills: [{ ...skill, disabled: true, eligible: false,
      blockedByAgentFilter: true, missing: { bins: ['tool'], anyBins: ['a', 'b'], env: ['REPORT_TOKEN'], config: ['feature.enabled'], os: ['darwin'] },
      install: [{ id: 'brew', label: '安装命令工具', kind: 'brew', bins: ['tool'] }] }] })
    expect(result.skills[0]).toMatchObject({ enabled: false, eligible: false, blockedByAgentFilter: true,
      missingBins: ['tool'], missingAnyBins: ['a', 'b'], missingConfig: ['feature.enabled'], missingOs: ['darwin'], installOptions: ['安装命令工具'] })
  })
  it.each([{ disabled: undefined }, { disabled: 'false' }, { eligible: undefined }, { enabled: true, disabled: true }])('rejects unproven or contradictory boolean fields: %j', (patch) => {
    expect(() => projectSkillsStatus({ skills: [{ ...skill, ...patch }] })).toThrow()
  })
})
