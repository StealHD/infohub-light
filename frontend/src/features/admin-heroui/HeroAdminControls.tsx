import type { Key, ReactNode } from 'react'

import {
  Description,
  FieldError,
  Icons,
  Label,
  ListBox,
  PageIntro,
  PageSection,
  Select,
  StatusNotice,
} from '../../design-system'

export type SelectOption = { id: string; label: string; description?: string; isDisabled?: boolean }

export function HeroSelect({ label, value, options, onChange, isDisabled = false, name, isRequired = false, description, errorMessage }: {
  label: string
  value: string
  options: SelectOption[]
  onChange: (value: string) => void
  isDisabled?: boolean
  name?: string
  isRequired?: boolean
  description?: string
  errorMessage?: string
}) {
  return <Select
    aria-label={label}
    name={name}
    selectedKey={value}
    onSelectionChange={(key: Key | null) => key !== null && onChange(String(key))}
    isDisabled={isDisabled}
    isRequired={isRequired}
    isInvalid={Boolean(errorMessage)}
    className="min-w-40"
  >
    <Label>{label}</Label>
    <Select.Trigger className="type-control">
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

export function AdminSection({ title, description, children, className = '' }: {
  title: string
  description?: string
  children: ReactNode
  className?: string
}) {
  return <PageSection title={title} description={description} className={className}>{children}</PageSection>
}
