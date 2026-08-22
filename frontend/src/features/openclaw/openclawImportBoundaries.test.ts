import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
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

function internalDependencies(path: string, sources: Set<string>): string[] {
  const source = readFileSync(path, 'utf8')
  const dependencies = new Set<string>()
  const imports = /(?:from\s+|import\s*(?:\(\s*)?)["'](\.[^"']+)["']/gu
  for (const match of source.matchAll(imports)) {
    const base = resolve(dirname(path), match[1])
    const target = [base, `${base}.ts`, `${base}.tsx`, join(base, 'index.ts')]
      .find((candidate) => existsSync(candidate) && sources.has(candidate))
    if (target) dependencies.add(target)
  }
  return [...dependencies]
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
      expect(source).not.toMatch(/(?:local|session)Storage/u)
      expect(source).not.toContain('indexedDB')
    }
  })

  it('loads the Workbench adapter directly and keeps the legacy conversation as an explicit facade', () => {
    expect(featureFile('../workbench-live/LazyOpenClawConversation.tsx'))
      .toContain("../openclaw/adapters/OpenClawConversation")
    expect(featureFile('OpenClawConversation.tsx')).not.toMatch(/export\s+\*/u)
  })

  it('has no circular dependencies inside OpenClaw production modules', () => {
    const sources = new Set(productionSources())
    const graph = new Map(
      [...sources].map((path) => [path, internalDependencies(path, sources)]),
    )

    function findCycle(path: string, lineage: string[]): string[] | null {
      const repeatedAt = lineage.indexOf(path)
      if (repeatedAt >= 0) return [...lineage.slice(repeatedAt), path]
      for (const dependency of graph.get(path) ?? []) {
        const cycle = findCycle(dependency, [...lineage, path])
        if (cycle) return cycle
      }
      return null
    }

    let cycle: string[] | null = null
    for (const source of sources) {
      cycle = findCycle(source, [])
      if (cycle) break
    }
    expect(cycle?.map((path) => relative(featureRoot, path)).join(' -> ') ?? null)
      .toBeNull()
  })
})
