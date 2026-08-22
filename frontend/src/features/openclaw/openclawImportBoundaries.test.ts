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
  })
})
