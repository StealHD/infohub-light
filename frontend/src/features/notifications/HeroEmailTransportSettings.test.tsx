import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { NotificationEmailTransport } from '../../api/types'
import { actionToast, DesignSystemProvider } from '../../design-system'
import { EmailTransportSettingsForm } from './HeroEmailTransportSettings'

const providers: NotificationEmailTransport['providers'] = [
  {
    provider: 'qq',
    label: 'QQ 邮箱',
    credential_label: 'SMTP 授权码',
    sender_hint: '填写完整 QQ 邮箱地址',
    requires_region: false,
    requires_smtp_username: false,
    smtp_port: 465,
    security: 'ssl',
  },
  {
    provider: 'netease',
    label: '网易邮箱',
    credential_label: 'SMTP 授权码',
    sender_hint: '支持 163、126 与 yeah.net',
    requires_region: false,
    requires_smtp_username: false,
    smtp_port: 465,
    security: 'ssl',
  },
  {
    provider: 'gmail',
    label: 'Gmail',
    credential_label: 'App Password',
    sender_hint: '填写完整邮箱地址',
    requires_region: false,
    requires_smtp_username: false,
    smtp_port: 465,
    security: 'ssl',
  },
  {
    provider: 'resend',
    label: 'Resend',
    credential_label: 'API Key',
    sender_hint: '使用已验证域名',
    requires_region: false,
    requires_smtp_username: false,
    smtp_port: 465,
    security: 'ssl',
  },
  {
    provider: 'amazon_ses',
    label: 'Amazon SES',
    credential_label: 'SES SMTP Password',
    sender_hint: '使用已验证地址',
    requires_region: true,
    requires_smtp_username: true,
    smtp_port: 465,
    security: 'ssl',
  },
]

function transport(
  overrides: Partial<NotificationEmailTransport> = {},
): NotificationEmailTransport {
  return {
    schema_version: 1,
    configured: false,
    provider: null,
    sender_email: null,
    sender_name: 'Inteliscope',
    region: null,
    smtp_username: null,
    enabled: false,
    credential_configured: false,
    generation: 0,
    last_test_status: null,
    last_test_generation: null,
    last_tested_at: null,
    last_test_error_code: null,
    can_enable: false,
    ready: false,
    connection: null,
    providers,
    updated_at: null,
    ...overrides,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((next) => {
    resolve = next
  })
  return { promise, resolve }
}

function renderForm(
  value: NotificationEmailTransport,
  onSave = vi.fn().mockResolvedValue(value),
  onTest = vi.fn().mockResolvedValue({
    sent: true,
    generation: value.generation,
  }),
  onDelete = vi.fn().mockResolvedValue(undefined),
) {
  render(<MemoryRouter><DesignSystemProvider>
    <EmailTransportSettingsForm
      settings={value}
      onSave={onSave}
      onTest={onTest}
      onDelete={onDelete}
    />
  </DesignSystemProvider></MemoryRouter>)
  return { onSave, onTest, onDelete }
}

describe('EmailTransportSettingsForm', () => {
  beforeEach(() => actionToast.clear())

  it('switches provider-specific fields and clears credentials immediately on save', async () => {
    const browser = userEvent.setup()
    const request = deferred<NotificationEmailTransport>()
    const onSave = vi.fn().mockReturnValue(request.promise)
    renderForm(transport(), onSave)

    await browser.click(screen.getByRole('button', { name: /邮件服务商/ }))
    await browser.click(screen.getByRole('option', { name: /Amazon SES/ }))
    expect(screen.getByLabelText('Amazon SES Region')).toBeInTheDocument()
    expect(screen.getByLabelText('SES SMTP 用户名')).toBeInTheDocument()
    expect(screen.getByLabelText('SES SMTP Password')).toHaveAttribute('type', 'password')

    await browser.type(screen.getByLabelText('发件邮箱'), 'notice@example.com')
    await browser.type(screen.getByLabelText('Amazon SES Region'), 'ap-southeast-1')
    await browser.type(screen.getByLabelText('SES SMTP 用户名'), 'ses-user')
    const credential = screen.getByLabelText('SES SMTP Password')
    await browser.type(credential, 'test-only-smtp-password')
    await browser.click(screen.getByRole('button', { name: '保存配置' }))

    expect(credential).toHaveValue('')
    expect(screen.queryByDisplayValue('test-only-smtp-password')).not.toBeInTheDocument()
    expect(onSave).toHaveBeenCalledWith({
      provider: 'amazon_ses',
      sender_email: 'notice@example.com',
      sender_name: 'Inteliscope',
      region: 'ap-southeast-1',
      smtp_username: 'ses-user',
      credential: 'test-only-smtp-password',
    })

    await act(async () => request.resolve(transport()))
  })

  it('enforces save, test, enable order and never retains the test recipient', async () => {
    const browser = userEvent.setup()
    const readyToTest = transport({
      configured: true,
      provider: 'resend',
      sender_email: 'notice@example.com',
      credential_configured: true,
      generation: 3,
      connection: {
        smtp_host: 'smtp.resend.com',
        smtp_port: 465,
        security: 'ssl',
        smtp_username: 'resend',
      },
    })
    const onTest = vi.fn().mockResolvedValue({
      sent: true,
      generation: 3,
    })
    renderForm(readyToTest, undefined, onTest)

    expect(screen.getByRole('switch', { name: '未启用' })).toBeDisabled()
    const recipient = screen.getByLabelText('测试收件邮箱')
    await browser.type(recipient, 'reader@example.com')
    await browser.click(screen.getByRole('button', { name: '发送测试邮件' }))

    expect(onTest).toHaveBeenCalledWith('reader@example.com')
    expect(recipient).toHaveValue('')
    expect(screen.queryByDisplayValue('reader@example.com')).not.toBeInTheDocument()
  })

  it('enables only a successfully tested generation and supports safe disable', async () => {
    const browser = userEvent.setup()
    const tested = transport({
      configured: true,
      provider: 'qq',
      sender_email: 'notice@qq.com',
      credential_configured: true,
      generation: 1,
      last_test_status: 'sent',
      last_test_generation: 1,
      last_tested_at: '2026-07-24T00:00:00Z',
      can_enable: true,
      connection: {
        smtp_host: 'smtp.qq.com',
        smtp_port: 465,
        security: 'ssl',
        smtp_username: 'notice@qq.com',
      },
    })
    const onSave = vi.fn().mockResolvedValue({ ...tested, enabled: true, ready: true })
    renderForm(tested, onSave)

    await browser.click(screen.getByRole('switch', { name: '未启用' }))
    await waitFor(() => expect(onSave).toHaveBeenCalledWith({ enabled: true }))
  })
})
