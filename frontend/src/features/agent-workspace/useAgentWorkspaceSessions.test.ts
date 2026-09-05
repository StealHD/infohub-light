import { describe, expect, it } from 'vitest'

import type { OpenClawWorkspaceSession } from '../openclaw'
import { projectTrustedSessionTree } from './useAgentWorkspaceSessions'

function session(key: string, parentSessionKey?: string): OpenClawWorkspaceSession {
  return { key, label: key, hasActiveRun: false, ...(parentSessionKey ? { parentSessionKey } : {}) }
}

describe('trusted root session tree', () => {
  it('includes parents, siblings and descendants under the fixed trusted root', () => {
    const result = projectTrustedSessionTree([
      session('root'), session('left', 'root'), session('right', 'root'), session('leaf', 'left'),
    ], 'leaf', 'root')
    expect(result.scopeKeys).toEqual(['root', 'left', 'leaf', 'right'])
    expect(result.current?.key).toBe('leaf')
  })

  it('ignores cycles and orphans instead of inferring membership from names', () => {
    const result = projectTrustedSessionTree([
      session('root'), session('good', 'root'), session('cycle-a', 'cycle-b'), session('cycle-b', 'cycle-a'), session('orphan', 'missing'), session('root-looking-name'),
    ], 'good', 'root')
    expect(result.scopeKeys).toEqual(['root', 'good'])
  })
})
