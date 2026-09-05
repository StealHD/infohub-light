import { beforeEach, describe, expect, it } from 'vitest'

import {
  readWorkspaceRoute,
  rememberWorkspaceRoute,
  validWorkspaceRoute,
  workspaceModeForPath,
} from './workspaceRoutePreference'

describe('workspace route preference', () => {
  beforeEach(() => window.localStorage.clear())

  it('classifies Agent routes as the OpenClaw workspace', () => {
    expect(workspaceModeForPath('/agent')).toBe('openclaw')
    expect(workspaceModeForPath('/agent/tasks')).toBe('openclaw')
    expect(workspaceModeForPath('/feed')).toBe('inscope')
  })

  it('remembers only allowlisted routes per user and workspace', () => {
    rememberWorkspaceRoute('one', '/saved')
    rememberWorkspaceRoute('one', '/agent/artifacts')
    rememberWorkspaceRoute('two', '/history')

    expect(readWorkspaceRoute('one', 'inscope')).toBe('/saved')
    expect(readWorkspaceRoute('one', 'openclaw')).toBe('/agent/artifacts')
    expect(readWorkspaceRoute('two', 'inscope')).toBe('/history')
    expect(readWorkspaceRoute('two', 'openclaw')).toBe('/agent')
  })

  it('rejects management and invented Agent routes', () => {
    expect(validWorkspaceRoute('inscope', '/settings')).toBe(false)
    expect(validWorkspaceRoute('openclaw', '/agent/private')).toBe(false)
  })
})
