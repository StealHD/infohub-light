/// <reference types="node" />

import { spawnSync } from 'node:child_process'
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
})
