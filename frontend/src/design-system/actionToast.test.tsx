import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { actionToast, DesignSystemProvider } from '.'

describe('actionToast', () => {
  it('renders outside page flow and invokes its retry action at most once', async () => {
    const retry = vi.fn()
    const browser = userEvent.setup()
    render(<MemoryRouter><DesignSystemProvider>
      <main data-page-frame="reading">
        <button type="button" onClick={() => actionToast.danger('更新失败', {
          description: '请稍后重试。',
          onRetry: retry,
        })}>触发反馈</button>
      </main>
    </DesignSystemProvider></MemoryRouter>)

    await browser.click(screen.getByRole('button', { name: '触发反馈' }))
    const toastTitle = await screen.findByText('更新失败')
    const toastRegion = toastTitle.closest('[data-slot="toast-region"]')
    expect(toastRegion).not.toBeNull()
    expect(toastRegion?.closest('[data-page-frame]')).toBeNull()

    const retryButton = screen.getByRole('button', { name: '重试' })
    fireEvent.click(retryButton)
    fireEvent.click(retryButton)
    expect(retry).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(screen.queryByText('更新失败')).not.toBeInTheDocument())
  })
})
