import type { Key } from 'react'
import './form-select.css'

import { Description, FieldError, Label, ListBox, Select } from '@heroui/react'
import { ChevronDown } from './icons'

export type FormSelectOption = {
  id: string
  label: string
  description?: string
  isDisabled?: boolean
}

export function FormSelect({
  label,
  value,
  options,
  onChange,
  isDisabled = false,
  isRequired = false,
  description,
  errorMessage,
  className = '',
}: {
  label: string
  value: string
  options: FormSelectOption[]
  onChange: (value: string) => void
  isDisabled?: boolean
  isRequired?: boolean
  description?: string
  errorMessage?: string
  className?: string
}) {
  return <Select
    aria-label={label}
    selectedKey={value || null}
    onSelectionChange={(key: Key | null) => key !== null && onChange(String(key))}
    isDisabled={isDisabled}
    isRequired={isRequired}
    isInvalid={Boolean(errorMessage)}
    className={`min-w-0 max-w-full ${className}`}
  >
    <Label>{label}</Label>
    <Select.Trigger className="form-select-trigger type-control min-h-10 w-full min-w-0">
      <Select.Value className="min-w-0 flex-1 truncate text-left" />
      <Select.Indicator className="shrink-0"><ChevronDown size={15} aria-hidden="true" /></Select.Indicator>
    </Select.Trigger>
    <Select.Popover className="max-w-[calc(100vw-24px)]">
      <ListBox items={options}>
        {(item) => <ListBox.Item id={item.id} textValue={item.label} isDisabled={item.isDisabled} className="type-control min-w-0 whitespace-normal [overflow-wrap:anywhere]">
          <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">{item.label}</span>
          {item.description && <span className="type-meta block text-muted">{item.description}</span>}
        </ListBox.Item>}
      </ListBox>
    </Select.Popover>
    {description && <Description>{description}</Description>}
    {errorMessage && <FieldError>{errorMessage}</FieldError>}
  </Select>
}
