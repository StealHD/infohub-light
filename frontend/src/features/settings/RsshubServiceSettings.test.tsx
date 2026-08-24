import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useRef } from 'react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../api/client'
import type { ServiceApi } from '../../api/service'
import type { AppOutletContext } from '../../app/AppContext'
import { DesignSystemProvider } from '../../design-system'
import { RsshubServiceSettings } from './RsshubServiceSettings'

function Harness() {
  const formRef = useRef<HTMLFormElement>(null)
  return <RsshubServiceSettings baseUrl="https://rsshub.example.test" formRef={formRef} isSaving={false} onFormChange={() => undefined} onSave={(event) => event.preventDefault()} />
}

function renderSettings(api: Partial<ServiceApi>) {
  const context = { api, user: { id: 'owner-1', username: 'owner', role: 'owner', enabled: true } } as AppOutletContext
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><DesignSystemProvider><Routes><Route element={<Outlet context={context} />}><Route path="*" element={<Harness />} /></Route></Routes></DesignSystemProvider></MemoryRouter></QueryClientProvider>)
}

describe('RsshubServiceSettings', () => {
  it('configures a write-only access key and restores focus to its clear action', async () => {
    const browser = userEvent.setup()
    const rsshubAccessKey = vi.fn().mockResolvedValue({ configured: false, management_source: 'none' })
    const saveRsshubAccessKey = vi.fn().mockResolvedValue({ configured: true, management_source: 'secret_store' })
    renderSettings({ rsshubAccessKey, saveRsshubAccessKey } as Partial<ServiceApi>)

    const manage = await screen.findByRole('button', { name: '配置访问密钥' })
    await browser.click(manage)
    await browser.type(screen.getByLabelText('访问密钥'), 'private-rsshub-key')
    await browser.click(screen.getByRole('button', { name: '保存访问密钥' }))

    await waitFor(() => expect(saveRsshubAccessKey).toHaveBeenCalledWith('private-rsshub-key'))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '配置 RSSHub 访问密钥' })).not.toBeInTheDocument())
    expect(document.body.textContent).not.toContain('private-rsshub-key')
    expect(manage).toHaveFocus()
  })

  it('keeps a failed save local and exposes a guarded removal flow for SecretStore values', async () => {
    const browser = userEvent.setup()
    const rsshubAccessKey = vi.fn().mockResolvedValue({ configured: true, management_source: 'secret_store' })
    const saveRsshubAccessKey = vi.fn().mockRejectedValue(new ApiError(400, { code: 'invalid_secret', message: '密钥格式无效。' }))
    const deleteRsshubAccessKey = vi.fn().mockResolvedValue({ configured: false, management_source: 'none' })
    renderSettings({ rsshubAccessKey, saveRsshubAccessKey, deleteRsshubAccessKey } as Partial<ServiceApi>)

    await browser.click(await screen.findByRole('button', { name: '更新访问密钥' }))
    await browser.type(screen.getByLabelText('访问密钥'), 'invalid-key')
    await browser.click(screen.getByRole('button', { name: '保存访问密钥' }))
    expect(await screen.findByText('密钥格式无效。')).toBeInTheDocument()
    expect(screen.getByLabelText('访问密钥')).toHaveValue('invalid-key')

    await browser.click(screen.getByRole('button', { name: '移除访问密钥' }))
    expect(await screen.findByRole('dialog', { name: '移除 RSSHub 访问密钥？' })).toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '确认移除' }))
    await waitFor(() => expect(deleteRsshubAccessKey).toHaveBeenCalledTimes(1))
  })

  it('does not present environment-managed keys as a removable page-managed value', async () => {
    renderSettings({ rsshubAccessKey: vi.fn().mockResolvedValue({ configured: true, management_source: 'environment' }) } as Partial<ServiceApi>)

    expect(await screen.findByText('环境托管')).toBeInTheDocument()
    expect(screen.getByText('由部署环境管理')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '配置访问密钥' })).not.toBeInTheDocument()
  })
})
