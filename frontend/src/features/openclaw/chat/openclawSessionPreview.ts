type SessionPreviewStatus = 'present' | 'missing' | 'error'

function recordOf(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

export function projectOpenClawSessionPreview(
  value: unknown,
  expectedKey: string,
): SessionPreviewStatus {
  const root = recordOf(value)
  if (!root || !Array.isArray(root.previews)) throw new Error('OpenClaw 会话验证响应无效。')
  const matches = root.previews.filter((candidate) => recordOf(candidate)?.key === expectedKey)
  if (matches.length !== 1) throw new Error('OpenClaw 会话验证响应不匹配。')
  const status = recordOf(matches[0])?.status
  if (status === 'ok' || status === 'empty') return 'present'
  if (status === 'missing' || status === 'error') return status
  throw new Error('OpenClaw 会话验证状态无效。')
}

export function openClawSessionPreviewParams(sessionKey: string): { keys: string[] } {
  return { keys: [sessionKey] }
}
