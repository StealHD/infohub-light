/// <reference types="node" />

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const frontendRoot = process.cwd()

describe('final HeroUI cutover contract', () => {
  it('has no MUI or Emotion dependency declarations', () => {
    const manifest = JSON.parse(readFileSync(resolve(frontendRoot, 'package.json'), 'utf8')) as {
      dependencies?: Record<string, string>
      devDependencies?: Record<string, string>
    }
    const packages = Object.keys({ ...manifest.dependencies, ...manifest.devDependencies })

    expect(packages.filter((name) => name.startsWith('@mui/') || name.startsWith('@emotion/'))).toEqual([])
  })

  it('keeps only the fixed-data HeroUI preview route in the Vite entry', () => {
    const main = readFileSync(resolve(frontendRoot, 'src/main.tsx'), 'utf8')
    const app = readFileSync(resolve(frontendRoot, 'src/app/App.tsx'), 'utf8')

    expect(main).toContain('/__preview/workbench-heroui')
    expect(`${main}\n${app}`).not.toContain('/__preview/workbench-live')
    expect(`${main}\n${app}`).not.toContain("'/__preview/workbench'")
  })

  it('boots production through the HeroUI design-system provider only', () => {
    const bootstrap = readFileSync(resolve(frontendRoot, 'src/AppBootstrap.tsx'), 'utf8')

    expect(bootstrap).toContain('DesignSystemProvider')
    expect(bootstrap).not.toContain('UiProvider')
    expect(bootstrap).not.toContain("from './ui'")
  })

  it('guards the fixed preview fixture with a stable marker and only matches real MUI artifacts', () => {
    const previewModel = readFileSync(resolve(frontendRoot, 'src/features/workbench-heroui/workbenchPreviewModel.ts'), 'utf8')
    const artifactChecker = readFileSync(resolve(frontendRoot, 'scripts/check-preview-build.mjs'), 'utf8')

    expect(previewModel).toContain("fixedPreviewFixtureMarker = 'inteliscope-fixed-preview-fixture-v1'")
    expect(artifactChecker).toContain('inteliscope-fixed-preview-fixture-v1')
    expect(artifactChecker).not.toMatch(/['"]Mui['"]\s*,/)
    expect(artifactChecker).toMatch(/Mui.*-/)
  })
})
