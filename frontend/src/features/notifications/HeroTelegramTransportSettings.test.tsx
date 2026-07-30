import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { NotificationTelegramTransport } from '../../api/types'
import { actionToast, DesignSystemProvider } from '../../design-system'
import { TelegramTransportSettingsForm } from './HeroTelegramTransportSettings'

const transport = (
  overrides: Partial<NotificationTelegramTransport> = {},
): NotificationTelegramTransport => ({
  schema_version: 1,
  configured: false,
  enabled: false,
  token_configured: false,
  generation: 0,
  last_test_status: null,
  last_test_generation: null,
  last_tested_at: null,
  last_test_error_code: null,
  can_enable: false,
  ready: false,
  updated_at: null,
  ...overrides,
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((next) => {
    resolve = next
  })
  return { promise, resolve }
}

function renderForm(
  value: NotificationTelegramTransport,
  onSave = vi.fn().mockResolvedValue(value),
  onTest = vi.fn().mockResolvedValue({ sent: true, generation: value.generation }),
  onDelete = vi.fn().mockResolvedValue(undefined),
) {
  render(<MemoryRouter><DesignSystemProvider>
    <TelegramTransportSettingsForm
      settings={value}
      onSave={onSave}
      onTest={onTest}
      onDelete={onDelete}
    />
  </DesignSystemProvider></MemoryRouter>)
  return { onSave, onTest, onDelete }
}

describe('TelegramTransportSettingsForm', () => {
  beforeEach(() => actionToast.clear())

  it('keeps the Bot Token write-only and clears it when saving starts', async () => {
    const browser = userEvent.setup()
    const request = deferred<NotificationTelegramTransport>()
    const onSave = vi.fn().mockReturnValue(request.promise)
    renderForm(transport(), onSave)

    const token = screen.getByLabelText('Bot Token')
    expect(token).toHaveAttribute('type', 'password')
    await browser.type(token, '123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef')
    await browser.click(screen.getByRole('button', { name: '保存 Token' }))

    expect(onSave).toHaveBeenCalledWith({
      bot_token: '123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef',
    })
    expect(token).toHaveValue('')
    expect(document.body.textContent).not.toContain('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef')

    await act(async () => request.resolve(transport({
      configured: true,
      token_configured: true,
      generation: 1,
    })))
  })

  it('uses a one-time signed integer or @channel Chat ID and never saves it', async () => {
    const browser = userEvent.setup()
    const value = transport({
      configured: true,
      token_configured: true,
      generation: 3,
    })
    const { onSave, onTest } = renderForm(value)
    const chatId = screen.getByLabelText('一次性测试 Chat ID')
    expect(chatId).toHaveAttribute('type', 'password')

    await browser.type(chatId, '-1001234567890')
    await browser.click(screen.getByRole('button', { name: '发送 Telegram 测试' }))
    expect(onTest).toHaveBeenCalledWith('-1001234567890')
    expect(onSave).not.toHaveBeenCalled()
    expect(chatId).toHaveValue('')

    await browser.type(chatId, 'invalid chat')
    expect(screen.getByRole('button', { name: '发送 Telegram 测试' })).toBeDisabled()
  })

  it('requires a successful current-generation test before enabling and confirms deletion', async () => {
    const browser = userEvent.setup()
    const value = transport({
      configured: true,
      token_configured: true,
      generation: 2,
      can_enable: false,
    })
    const { onSave, onDelete } = renderForm(value)

    expect(screen.getByRole('switch', { name: 'Telegram 未启用' })).toBeDisabled()
    const remove = screen.getByRole('button', { name: '删除配置' })
    await browser.click(remove)
    expect(onDelete).not.toHaveBeenCalled()
    await browser.click(screen.getByRole('button', { name: '再次点击确认删除' }))
    expect(onDelete).toHaveBeenCalledOnce()
    expect(onSave).not.toHaveBeenCalled()
  })
})
