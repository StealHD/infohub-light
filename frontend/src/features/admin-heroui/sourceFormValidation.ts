import type { SourceTypeDefinition } from '../../api/types'

export function validateRegistryFields(
  definition: SourceTypeDefinition,
  form: FormData,
  registryValues: Record<string, unknown>,
) {
  const errors: Record<string, string> = {}
  for (const field of definition.fields) {
    const raw = String(field.options?.length ? registryValues[field.name] ?? '' : form.get(field.name) ?? '').trim()
    const isBoolean = field.input_type === 'checkbox' || field.input_type === 'boolean'
    if (field.required && (isBoolean ? !form.has(field.name) : !raw)) {
      errors[field.name] = `${field.label}不能为空。`
      continue
    }
    if (!raw || isBoolean) continue
    if (field.input_type === 'url') {
      try {
        new URL(raw)
      } catch {
        errors[field.name] = `${field.label}必须是有效 URL。`
      }
    }
    if (field.input_type === 'number') {
      const value = Number(raw)
      if (!Number.isFinite(value)) errors[field.name] = `${field.label}必须是有效数字。`
      else if (!Number.isInteger(value)) errors[field.name] = `${field.label}必须是整数。`
      else if (field.min !== null && field.min !== undefined && value < field.min) errors[field.name] = `${field.label}不能小于 ${field.min}。`
      else if (field.max !== null && field.max !== undefined && value > field.max) errors[field.name] = `${field.label}不能大于 ${field.max}。`
    }
  }
  return errors
}
