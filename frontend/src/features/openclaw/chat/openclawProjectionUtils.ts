export function recordOf(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

export function stringOf(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}
