export type UnknownRecord = Record<string, unknown>
export function recordOf(value: unknown, label: string): UnknownRecord { if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label} 返回格式无效。`); return value as UnknownRecord }
export function stringOf(value: unknown, maxLength = 512): string | undefined {
  if (typeof value !== 'string') return undefined
  const normalized = Array.from(value).filter((character) => { const code = character.charCodeAt(0); return (code > 31 && code !== 127) || code === 9 || code === 10 || code === 13 }).join('').trim()
  return normalized ? normalized.slice(0, maxLength) : undefined
}
export function numberOf(value: unknown): number | undefined { return typeof value === 'number' && Number.isFinite(value) ? value : undefined }
export function arrayOf(value: unknown, label: string): unknown[] { if (!Array.isArray(value)) throw new Error(`${label} 返回格式无效。`); return value }
export function optionalStringArray(value: unknown): string[] { return Array.isArray(value) ? value.flatMap((candidate) => stringOf(candidate) ?? []) : [] }

