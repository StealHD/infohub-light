import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const featureFile = (name: string) => readFileSync(
  fileURLToPath(new URL(name, import.meta.url)),
  'utf8',
)

describe('OpenClaw import boundaries', () => {
  it('keeps external consumers independent from the hook implementation type', () => {
    const consumers = [
      '../workbench-live/HeroWorkbenchShell.tsx',
      '../workbench-live/LazyOpenClawConversation.tsx',
      'OpenClawConversation.tsx',
    ]

    for (const consumer of consumers) {
      expect(featureFile(consumer)).not.toContain('ReturnType<typeof useOpenClawChat>')
    }
  })

  it('uses only explicit facade exports and keeps contracts free of Workbench imports', () => {
    expect(featureFile('index.ts')).not.toMatch(/export\s+\*/u)
    expect(featureFile('openclawContracts.ts')).not.toContain('workbench-live')
    expect(featureFile('useOpenClawChat.ts')).not.toContain('workbench-live')
  })

  it('keeps chat projections free of React and browser persistence', () => {
    const projections = [
      'chat/openclawEventProjection.ts',
      'chat/openclawHandoffProtocol.ts',
      'chat/openclawHistoryProjection.ts',
      'chat/openclawRuntimeProjection.ts',
    ]

    for (const projection of projections) {
      const source = featureFile(projection)
      expect(source).not.toMatch(/from ['"]react['"]/u)
      expect(source).not.toMatch(/(?:local|session)Storage/u)
      expect(source).not.toContain('workbench-live')
    }
  })
})
