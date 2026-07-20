/// <reference types="node" />

import { spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { build } from 'vite'
import { afterEach, describe, expect, it } from 'vitest'

const frontendRoot = process.cwd()
const artifactChecker = resolve(frontendRoot, 'scripts/check-preview-build.mjs')
const temporaryRoots: string[] = []

function temporaryRoot() {
  const root = mkdtempSync(join(tmpdir(), 'inteliscope-ui-artifact-'))
  temporaryRoots.push(root)
  return root
}

function checkArtifact(buildRoot: string) {
  return spawnSync(process.execPath, [artifactChecker, '--build-root', buildRoot], { encoding: 'utf8' })
}

afterEach(() => {
  for (const root of temporaryRoots.splice(0)) rmSync(root, { recursive: true, force: true })
})

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

  it('rejects an actual MUI global-state class in a built CSS artifact', () => {
    const buildRoot = temporaryRoot()
    writeFileSync(join(buildRoot, 'app.css'), '.button.Mui-disabled{opacity:.4}\n')

    const result = checkArtifact(buildRoot)

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('MUI class marker')
  })

  it('rejects a production bundle that imports the fixed preview stories', async () => {
    const root = temporaryRoot()
    const output = join(root, 'dist')
    const entry = join(root, 'entry.ts')
    const previewModel = resolve(frontendRoot, 'src/features/workbench-heroui/workbenchPreviewModel.ts')
    mkdirSync(output, { recursive: true })
    writeFileSync(entry, [
      `import { workbenchPreviewStories } from ${JSON.stringify(previewModel)}`,
      "document.body.textContent = workbenchPreviewStories.map((story) => story.title).join(' | ')",
    ].join('\n'))

    await build({
      configFile: false,
      logLevel: 'silent',
      root,
      build: {
        emptyOutDir: true,
        minify: true,
        outDir: output,
        rollupOptions: { input: entry, output: { entryFileNames: 'fixture.js' } },
      },
    })
    const result = checkArtifact(output)

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('inteliscope-fixed-preview-fixture-v1')
  })
})
