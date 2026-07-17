/// <reference types="node" />

import { spawnSync } from 'node:child_process'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const checker = resolve(process.cwd(), 'scripts/check-ui-contract.mjs')

function checkHeroUiSource(file: string, source: string) {
  return spawnSync(process.execPath, [checker, '--check-heroui-source', file], {
    encoding: 'utf8',
    input: source,
  })
}

describe('HeroUI import contract', () => {
  it('rejects direct HeroUI imports from production feature code', () => {
    const result = checkHeroUiSource(
      'src/features/feed/DirectHeroCard.tsx',
      "import { Card } from '@heroui/react'\nexport const DirectHeroCard = Card\n",
    )

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('HeroUI 必须通过 src/design-system 引入')
  })

  it('keeps the fixed-data HeroUI prototype as the sole feature exception', () => {
    const result = checkHeroUiSource(
      'src/features/workbench-heroui/PrototypeCard.tsx',
      "import { Card } from '@heroui/react'\nexport const PrototypeCard = Card\n",
    )

    expect(result.status).toBe(0)
    expect(result.stderr).toBe('')
  })
})
