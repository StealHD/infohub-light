import { useState, type Key, type ReactNode } from 'react'

import {
  ComboBox,
  Description,
  FieldError,
  Icons,
  Input,
  Label,
  ListBox,
  PageIntro,
  PageSection,
  Select,
  StatusNotice,
} from '../../design-system'

export type SelectOption = {
  id: string
  label: string
  description?: string
  searchText?: string
  isDisabled?: boolean
}

export function HeroSelect({
  label,
  value,
  options,
  onChange,
  isDisabled = false,
  name,
  isRequired = false,
  description,
  errorMessage,
  hideLabel = false,
  className = '',
  triggerClassName = '',
}: {
  label: string
  value: string
  options: SelectOption[]
  onChange: (value: string) => void
  isDisabled?: boolean
  name?: string
  isRequired?: boolean
  description?: string
  errorMessage?: string
  hideLabel?: boolean
  className?: string
  triggerClassName?: string
}) {
  return <Select
    aria-label={label}
    name={name}
    selectedKey={value}
    onSelectionChange={(key: Key | null) => key !== null && onChange(String(key))}
    isDisabled={isDisabled}
    isRequired={isRequired}
    isInvalid={Boolean(errorMessage)}
    className={`min-w-40 ${className}`}
  >
    {!hideLabel && <Label>{label}</Label>}
    <Select.Trigger className={`type-control ${triggerClassName}`}>
      <Select.Value />
      <Select.Indicator><Icons.ChevronDown size={15} aria-hidden="true" /></Select.Indicator>
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

export function HeroAutocomplete({
  label,
  value,
  options,
  onChange,
  isDisabled = false,
  name,
  isRequired = false,
  placeholder,
  className = '',
}: {
  label: string
  value: string
  options: SelectOption[]
  onChange: (value: string) => void
  isDisabled?: boolean
  name?: string
  isRequired?: boolean
  placeholder?: string
  className?: string
}) {
  const selected = options.find((option) => option.id === value)
  const selectedLabel = selected?.label ?? ''
  const [query, setQuery] = useState<string | null>(null)
  const inputValue = query ?? selectedLabel
  const normalizedQuery = (query ?? '').trim().toLocaleLowerCase()
  const visibleOptions = normalizedQuery
    ? options.filter((option) => `${option.label} ${option.searchText ?? ''}`.toLocaleLowerCase().includes(normalizedQuery))
    : options

  return <ComboBox
    name={name}
    selectedKey={value || null}
    inputValue={inputValue}
    onInputChange={(nextValue) => setQuery(selectedLabel && nextValue.startsWith(selectedLabel)
      ? nextValue.slice(selectedLabel.length).trimStart()
      : nextValue)}
    onSelectionChange={(key: Key | null) => {
      if (key === null) return
      const nextValue = String(key)
      onChange(nextValue)
      setQuery(null)
    }}
    isDisabled={isDisabled}
    isRequired={isRequired}
    menuTrigger="focus"
    className={`min-w-40 ${className}`}
  >
    <Label>{label}</Label>
    <ComboBox.InputGroup>
      <Input placeholder={placeholder ?? `搜索${label}`} onBlur={() => setQuery(null)} />
      <ComboBox.Trigger aria-label={`选择${label}`}><Icons.ChevronDown size={15} aria-hidden="true" /></ComboBox.Trigger>
    </ComboBox.InputGroup>
    <ComboBox.Popover>
      <ListBox items={visibleOptions}>
        {(item) => <ListBox.Item id={item.id} textValue={item.label} isDisabled={item.isDisabled} className="type-control">
          <span>{item.label}</span>
          {item.description && <span className="type-meta block text-muted">{item.description}</span>}
        </ListBox.Item>}
      </ListBox>
    </ComboBox.Popover>
    {selected?.description && <Description>{selected.description}</Description>}
  </ComboBox>
}

export function HeroNotice({ title, children, status = 'danger', role = 'alert' }: {
  title: string
  children?: ReactNode
  status?: 'default' | 'accent' | 'success' | 'warning' | 'danger'
  role?: 'alert' | 'status'
}) {
  return <StatusNotice title={title} status={status} role={role}>{children}</StatusNotice>
}

export function AdminPageHeader({ description, actions }: { description: string; actions?: ReactNode }) {
  return <PageIntro description={description} actions={actions} />
}

export function AdminSection({ title, description, children, className = '', id }: {
  title: string
  description?: string
  children: ReactNode
  className?: string
  id?: string
}) {
  return <PageSection id={id} title={title} description={description} className={className}>{children}</PageSection>
}
