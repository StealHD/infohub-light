import type { Key, ReactNode } from 'react'

import {
  Alert,
  Card,
  Description,
  FieldError,
  Icons,
  Label,
  ListBox,
  Select,
} from '../../design-system'

export type SelectOption = { id: string; label: string }

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
    <Select.Trigger>
      <Select.Value />
      <Select.Indicator><Icons.ChevronDown size={15} aria-hidden="true" /></Select.Indicator>
    </Select.Trigger>
    <Select.Popover>
      <ListBox items={options}>
        {(item) => <ListBox.Item id={item.id} textValue={item.label}>{item.label}</ListBox.Item>}
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
  return <Alert status={status} role={role}>
    <Alert.Content><Alert.Title>{title}</Alert.Title>{children && <Alert.Description>{children}</Alert.Description>}</Alert.Content>
  </Alert>
}

export function AdminPageHeader({ title, description, actions }: { title: string; description: string; actions?: ReactNode }) {
  return <header className="flex flex-col gap-4 min-[640px]:flex-row min-[640px]:items-center min-[640px]:justify-between">
    <div><h1 className="type-display">{title}</h1><p className="type-body mt-1 text-muted">{description}</p></div>
    {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
  </header>
}

export function AdminSection({ title, description, children, className = '' }: {
  title: string
  description?: string
  children: ReactNode
  className?: string
}) {
  return <Card variant="secondary" className={`p-4 min-[640px]:p-5 ${className}`}>
    <Card.Header className="px-0 pt-0"><div><Card.Title className="type-page-title">{title}</Card.Title>{description && <Card.Description className="type-body mt-1">{description}</Card.Description>}</div></Card.Header>
    <Card.Content className="px-0 pb-0">{children}</Card.Content>
  </Card>
}
