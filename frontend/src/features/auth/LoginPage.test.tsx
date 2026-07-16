import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { ServiceApi } from '../../api/service'
import { LoginPage } from './LoginPage'

describe('LoginPage', () => {
  it('submits credentials and never persists the password in the page', async () => {
    const user = userEvent.setup()
    const onAuthenticated = vi.fn()
    const api = {
      login: vi.fn().mockResolvedValue({ authenticated: true, user: { id: 'u1', username: 'owner', role: 'owner', enabled: true } }),
    } as unknown as ServiceApi
    render(<LoginPage api={api} onAuthenticated={onAuthenticated} />)

    await user.type(screen.getByLabelText('用户名'), 'owner')
    await user.type(screen.getByLabelText('密码'), 'secret-password')
    await user.click(screen.getByRole('button', { name: '登录' }))

    expect(api.login).toHaveBeenCalledWith('owner', 'secret-password')
    expect(onAuthenticated).toHaveBeenCalled()
    expect(document.body.textContent).not.toContain('secret-password')
  })
})
