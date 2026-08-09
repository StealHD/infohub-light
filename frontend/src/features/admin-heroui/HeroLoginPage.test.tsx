import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../api/client'
import type { ServiceApi } from '../../api/service'
import { DesignSystemProvider } from '../../design-system'
import { HeroLoginPage } from './HeroLoginPage'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((next, fail) => {
    resolve = next
    reject = fail
  })
  return { promise, resolve, reject }
}

function renderLogin(api: ServiceApi, onAuthenticated = vi.fn()) {
  render(
    <MemoryRouter>
      <DesignSystemProvider>
        <HeroLoginPage api={api} onAuthenticated={onAuthenticated} />
      </DesignSystemProvider>
    </MemoryRouter>,
  )
  return { onAuthenticated }
}

describe('HeroLoginPage', () => {
  it('renders the responsive Quiet Studio layout and an accessible password reveal control', async () => {
    const browser = userEvent.setup()
    const api = { login: vi.fn() } as unknown as ServiceApi
    renderLogin(api)

    expect(screen.getByRole('heading', { name: '登录私人信息雷达' })).toBeInTheDocument()
    expect(screen.getByText('专注你真正关心的信息')).toBeInTheDocument()
    expect(document.querySelector('[data-login-layout="quiet-studio-split"]')).toBeInTheDocument()
    expect(document.querySelector('[data-login-brand]')).toBeInTheDocument()
    expect(document.querySelector('[data-login-form]')).toBeInTheDocument()

    const username = screen.getByLabelText('用户名')
    const password = screen.getByLabelText('密码')
    expect(username).toHaveFocus()
    expect(password).toHaveAttribute('type', 'password')

    const reveal = screen.getByRole('button', { name: '显示密码' })
    expect(reveal).toHaveAttribute('aria-pressed', 'false')
    await browser.click(reveal)
    expect(password).toHaveAttribute('type', 'text')
    expect(screen.getByRole('button', { name: '隐藏密码' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('trims the username, keeps API failures local, and clears and re-hides the password', async () => {
    const browser = userEvent.setup()
    const login = vi.fn().mockRejectedValue(new ApiError(401, { code: 'invalid_credentials', message: '账号或密码错误' }))
    const api = { login } as unknown as ServiceApi
    renderLogin(api)

    await browser.type(screen.getByLabelText('用户名'), '  owner  ')
    await browser.type(screen.getByLabelText('密码'), 'wrong-secret')
    await browser.click(screen.getByRole('button', { name: '显示密码' }))
    await browser.click(screen.getByRole('button', { name: '登录' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('账号或密码错误')
    expect(screen.getByRole('form')).toHaveAttribute('aria-describedby', 'hero-login-error')
    expect(screen.getByLabelText('密码')).toHaveValue('')
    expect(screen.getByLabelText('密码')).toHaveAttribute('type', 'password')
    expect(login).toHaveBeenCalledWith('owner', 'wrong-secret')

    await browser.type(screen.getByLabelText('密码'), 'n')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('locks a pending submission against replay and reports successful authentication once', async () => {
    const browser = userEvent.setup()
    const pending = deferred<Awaited<ReturnType<ServiceApi['login']>>>()
    const login = vi.fn().mockReturnValue(pending.promise)
    const api = { login } as unknown as ServiceApi
    const { onAuthenticated } = renderLogin(api)

    await browser.type(screen.getByLabelText('用户名'), 'owner')
    await browser.type(screen.getByLabelText('密码'), 'correct-secret')
    await browser.click(screen.getByRole('button', { name: '登录' }))

    expect(screen.getByRole('form')).toHaveAttribute('aria-busy', 'true')
    expect(screen.getByLabelText('用户名')).toBeDisabled()
    expect(screen.getByLabelText('密码')).toBeDisabled()
    expect(screen.getByRole('button', { name: '显示密码' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '登录中…' })).toBeDisabled()
    await browser.click(screen.getByRole('button', { name: '登录中…' }))
    expect(login).toHaveBeenCalledTimes(1)

    await act(async () => {
      pending.resolve({
        authenticated: true,
        user: { id: 'owner-id', username: 'owner', role: 'owner', enabled: true },
      })
      await pending.promise
    })

    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledTimes(1))
    expect(screen.getByRole('form')).not.toHaveAttribute('aria-busy')
  })
})
