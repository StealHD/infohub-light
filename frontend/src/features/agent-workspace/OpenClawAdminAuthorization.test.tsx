import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { DesignSystemProvider } from '../../design-system'
import { AdminAuthorizationDialog } from './OpenClawAdminAuthorization'

function Harness({ onConnect }: { onConnect: (token: string) => Promise<boolean> }) {
  const [open, setOpen] = useState(true)
  return <>
    <button type="button" onClick={() => setOpen(true)}>重新打开授权</button>
    <AdminAuthorizationDialog open={open} connecting={false} error="" onOpenChange={setOpen} onConnect={onConnect} />
  </>
}

describe('AdminAuthorizationDialog', () => {
  it('clears the one-time token and trust confirmation whenever the dialog closes', async () => {
    const browser = userEvent.setup()
    const onConnect = vi.fn().mockResolvedValue(false)
    render(<MemoryRouter><DesignSystemProvider><Harness onConnect={onConnect} /></DesignSystemProvider></MemoryRouter>)

    await browser.click(screen.getByRole('checkbox'))
    await browser.type(screen.getByLabelText('Gateway admin token'), 'one-time-secret')
    await browser.click(screen.getByRole('button', { name: '取消' }))
    await browser.click(screen.getByRole('button', { name: '重新打开授权' }))

    expect(screen.getByLabelText('Gateway admin token')).toHaveValue('')
    expect(screen.getByRole('checkbox')).not.toBeChecked()
    expect(JSON.stringify(window.localStorage)).not.toContain('one-time-secret')
  })
})
