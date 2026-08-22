import { readdirSync, readFileSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const featureFile = (name: string) => readFileSync(
  fileURLToPath(new URL(name, import.meta.url)),
  'utf8',
)

const featureRoot = resolve(process.cwd(), 'src/features/openclaw')

function productionSources(directory = featureRoot): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) return productionSources(path)
    if (!/\.(?:ts|tsx)$/u.test(entry.name) || entry.name.includes('.test.')) return []
    return [path]
  })
}

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
    expect(featureFile('openclawGateway.ts')).not.toMatch(/export\s+\*/u)
    expect(featureFile('openclawGateway.ts')).not.toMatch(/\b(?:class|function)\s+/u)
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

  it('allows Workbench imports only inside the adapter boundary', () => {
    for (const path of productionSources()) {
      const source = readFileSync(path, 'utf8')
      if (!source.includes('workbench-live')) continue
      expect(relative(featureRoot, path)).toMatch(/^adapters\//u)
    }
  })

  it('keeps UI components away from Workbench, Gateway frames, and persistence', () => {
    for (const path of productionSources(join(featureRoot, 'ui'))) {
      const source = readFileSync(path, 'utf8')
      expect(source).not.toContain('workbench-live')
      expect(source).not.toContain('openclawGateway')
      expect(source).not.toContain('GatewayEvent')
      expect(source).not.toContain('sessionStorage')
    }
  })

  it('loads the Workbench adapter directly and keeps the legacy conversation as an explicit facade', () => {
    expect(featureFile('../workbench-live/LazyOpenClawConversation.tsx'))
      .toContain("../openclaw/adapters/OpenClawConversation")
    expect(featureFile('OpenClawConversation.tsx')).not.toMatch(/export\s+\*/u)
  })
})
