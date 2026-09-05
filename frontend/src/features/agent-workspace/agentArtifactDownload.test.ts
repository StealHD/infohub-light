import { describe, expect, it, vi } from 'vitest'

import type { OpenClawArtifactDownload } from '../openclaw'
import { AGENT_ARTIFACT_PREVIEW_LIMIT, artifactObjectUrl, artifactPreviewKind, artifactText, validateArtifactTemporaryUrl } from './agentArtifactDownload'

function download(mimeType: string, sizeBytes = 12): OpenClawArtifactDownload {
  return { artifact: { id: 'artifact-1', type: 'file', title: 'result', mimeType, sizeBytes, downloadMode: 'bytes', sessionKey: 'session-1' }, encoding: 'base64', data: btoa('hello') }
}

describe('Agent artifact safety', () => {
  it('previews only safe images and UTF-8 text within 2 MiB', () => {
    expect(artifactPreviewKind(download('image/png'))).toBe('image')
    expect(artifactPreviewKind(download('text/markdown'))).toBe('text')
    expect(artifactPreviewKind(download('text/html'))).toBe('download')
    expect(artifactPreviewKind(download('image/svg+xml'))).toBe('download')
    expect(artifactPreviewKind(download('application/octet-stream'))).toBe('download')
    expect(artifactPreviewKind(download('text/plain', AGENT_ARTIFACT_PREVIEW_LIMIT + 1))).toBe('download')
    const unknownSize = download('image/png')
    delete unknownSize.artifact.sizeBytes
    expect(artifactPreviewKind(unknownSize)).toBe('download')
    expect(artifactText(download('text/plain'))).toBe('hello')
  })

  it('revokes browser object URLs after the caller finishes with them', () => {
    const createObjectURL = vi.fn(() => 'blob:artifact-preview')
    const revokeObjectURL = vi.fn()
    const originalCreate = URL.createObjectURL
    const originalRevoke = URL.revokeObjectURL
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectURL })
    try {
      const object = artifactObjectUrl(download('image/png'), 'wss://agent.example.com/ws')
      expect(object.url).toBe('blob:artifact-preview')
      object.revoke()
      expect(revokeObjectURL).toHaveBeenCalledWith('blob:artifact-preview')
    } finally {
      Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: originalCreate })
      Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: originalRevoke })
    }
  })

  it('accepts only unexpired HTTP(S) URLs at the current Gateway origin', () => {
    const future = new Date(Date.now() + 60_000).toISOString()
    expect(validateArtifactTemporaryUrl('https://agent.example.com/download/1', future, 'wss://agent.example.com/ws')).toBe('https://agent.example.com/download/1')
    expect(() => validateArtifactTemporaryUrl('https://evil.example/download/1', future, 'wss://agent.example.com/ws')).toThrow('origin')
    expect(() => validateArtifactTemporaryUrl('javascript:alert(1)', future, 'wss://agent.example.com/ws')).toThrow('不安全')
    expect(() => validateArtifactTemporaryUrl('https://agent.example.com/download/1', new Date(0).toISOString(), 'wss://agent.example.com/ws')).toThrow('过期')
  })
})
