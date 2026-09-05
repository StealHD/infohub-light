import type { Key } from 'react'

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
    className={`min-w-0 ${className}`}
  >
    <Label>{label}</Label>
    <Select.Trigger className="type-control min-h-10">
      <Select.Value />
      <Select.Indicator><ChevronDown size={15} aria-hidden="true" /></Select.Indicator>
    </Select.Trigger>
    <Select.Popover>
      <ListBox items={options}>
        {(item) => <ListBox.Item id={item.id} textValue={item.label} isDisabled={item.isDisabled} className="type-control">
          <span>{item.label}</span>
          {item.description && <span className="type-meta block text-muted">{item.description}</span>}
        </ListBox.Item>}
      </ListBox>
    </Select.Popover>
    {description && <Description>{description}</Description>}
    {errorMessage && <FieldError>{errorMessage}</FieldError>}
  </Select>
}
