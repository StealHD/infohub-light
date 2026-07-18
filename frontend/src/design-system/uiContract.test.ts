/// <reference types="node" />

import { spawnSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const checker = resolve(process.cwd(), 'scripts/check-ui-contract.mjs')

function checkSource(file: string, source: string) {
  return spawnSync(process.execPath, [checker, '--check-source', file], {
    encoding: 'utf8',
    input: source,
  })
}

function checkLint(file: string, source: string) {
  return spawnSync('npx', ['eslint', '--no-ignore', '--stdin', '--stdin-filename', file], {
    cwd: process.cwd(), encoding: 'utf8', input: source,
  })
}

describe('HeroUI import contract', () => {
  it('rejects direct HeroUI imports from production feature code', () => {
    const result = checkSource(
      'src/features/feed/DirectHeroCard.tsx',
      "import { Card } from '@heroui/react'\nexport const DirectHeroCard = Card\n",
    )

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('HeroUI 必须通过 src/design-system 引入')
  })

  it('keeps the fixed-data HeroUI prototype as the sole feature exception', () => {
    const result = checkSource(
      'src/features/workbench-heroui/PrototypeCard.tsx',
      "import { Card } from '@heroui/react'\nexport const PrototypeCard = Card\n",
    )

    expect(result.status).toBe(0)
    expect(result.stderr).toBe('')
  })

  it('rejects nested design-system providers from feature code', () => {
    const result = checkSource(
      'src/features/admin-heroui/NestedProvider.tsx',
      "import { DesignSystemProvider } from '../../design-system'\nexport const NestedProvider = DesignSystemProvider\n",
    )

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('DesignSystemProvider 只能由 AppBootstrap 挂载')
  })

  it.each([
    ["import { Button } from '@mui/material'", 'MUI/Emotion 已从源码移除'],
    ["import styled from '@emotion/styled'", 'MUI/Emotion 已从源码移除'],
    ["export const color = '#663399'", '业务页面不得定义原始颜色值'],
    ["export const route = '/__preview/workbench-live'", '已删除的验收路由或 MUI 原型文案'],
    ["export const copy = '切换到 MUI 版'", '已删除的验收路由或 MUI 原型文案'],
  ])('rejects removed UI technology and visual constants: %s', (source, message) => {
    const result = checkSource('src/features/feed/Violation.tsx', source)

    expect(result.status).toBe(1)
    expect(result.stderr).toContain(message)
  })

  it.each([
    "import styles from './Feed.module.css'\nexport const value = styles.root\n",
    "import './Feed.module.css'\nexport const value = true\n",
    "export const styles = import('./Feed.module.css')\n",
  ])('rejects default and side-effect CSS Module imports from business code', (source) => {
    const result = checkSource('src/features/feed/FeedSurface.tsx', source)

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('Shell 与业务页不得使用页面级 CSS Modules')
  })

  it.each([
    ["import(`@heroui/react`)", 'HeroUI 必须通过 src/design-system 引入'],
    ["import(`@mui/material`)", 'MUI/Emotion 已从源码移除'],
    ["import(`./Feed.module.css`)", 'Shell 与业务页不得使用页面级 CSS Modules'],
  ])('rejects static template-literal imports in the executable checker: %s', (source, message) => {
    const result = checkSource('src/features/feed/TemplateImport.tsx', source)

    expect(result.status).toBe(1)
    expect(result.stderr).toContain(message)
  })

  it.each([
    "import(`@heroui/react`)",
    "import(`@mui/material`)",
    "import(`@emotion/styled`)",
    "import(`./Feed.module.css`)",
  ])('rejects static template-literal UI imports in ESLint: %s', (source) => {
    const result = checkLint('src/features/feed/TemplateImport.tsx', source)

    expect(result.status).toBe(1)
  })

  it('rejects visual constants in business CSS', () => {
    const result = checkSource(
      'src/features/feed/feed-surface.css',
      '.feed-surface { box-shadow: var(--shadow-raised); border-radius: 18px; }\n',
    )

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('视觉常量必须来自设计系统主题')
  })

  it.each([
    'oklch(62% 0.18 250)',
    'lab(62% 18 -35)',
    'lch(62% 42 250)',
    'color(display-p3 0.2 0.4 0.8)',
  ])('rejects the modern raw CSS color %s', (color) => {
    const result = checkSource('src/features/feed/feed-surface.css', `.feed-surface { color: ${color}; }\n`)

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('业务页面不得定义原始颜色值')
  })

  it.each([
    'text-sm',
    'text-[13px]',
    'font-semibold',
    'leading-5',
    'leading-[1.38]',
    'tracking-wide',
  ])('rejects arbitrary typography utility %s from production business code', (utility) => {
    const result = checkSource(
      'src/features/feed/ArbitraryTypography.tsx',
      `export const Example = () => <span className="${utility}">内容</span>\n`,
    )

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('业务文字必须使用设计系统语义排版')
  })

  it('allows semantic typography classes from the design-system scale', () => {
    const result = checkSource(
      'src/features/feed/SemanticTypography.tsx',
      'export const Example = () => <span className="type-control text-muted">内容</span>\n',
    )

    expect(result.status).toBe(0)
    expect(result.stderr).toBe('')
  })

  it('defines one application font stack and the complete semantic typography scale', () => {
    const theme = readFileSync(resolve(process.cwd(), 'src/design-system/theme.css'), 'utf8')

    expect(theme).toContain('--inteliscope-font-ui:')
    for (const role of ['display', 'section-title', 'page-title', 'card-title', 'body', 'control', 'meta', 'label', 'micro', 'prose']) {
      expect(theme).toContain(`.type-${role}`)
    }
  })

  it('maps HeroUI text-bearing primitives onto the semantic scale', () => {
    const theme = readFileSync(resolve(process.cwd(), 'src/design-system/theme.css'), 'utf8')

    expect(theme).toMatch(/:where\([^)]*\.button[^)]*\.select__trigger[^)]*\)\s*\{[^}]*font-size:\s*var\(--inteliscope-type-control-size\)/s)
    expect(theme).toMatch(/:where\([^)]*\.card__title[^)]*\.modal__heading[^)]*\)\s*\{[^}]*font-size:\s*var\(--inteliscope-type-page-title-size\)/s)
    expect(theme).toMatch(/:where\([^)]*\.card__description[^)]*\)\s*\{[^}]*font-size:\s*var\(--inteliscope-type-body-size\)/s)
    expect(theme).toMatch(/:where\([^)]*\.chip__label[^)]*\)\s*\{[^}]*font-size:\s*var\(--inteliscope-type-micro-size\)/s)
  })

  it('owns the adaptive Quiet Studio widths and compact select value typography', () => {
    const theme = readFileSync(resolve(process.cwd(), 'src/design-system/theme.css'), 'utf8')

    expect(theme).toContain('--inteliscope-width-reading: 820px')
    expect(theme).toContain('--inteliscope-width-admin: 1180px')
    expect(theme).toContain('--inteliscope-width-auth: 420px')
    expect(theme).toMatch(/\.quiet-compact-select[^}]*\.select__value[^}]*\{[^}]*font-size:\s*var\(--inteliscope-type-control-size\)/s)
  })
})
