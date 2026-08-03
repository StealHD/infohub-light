import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { SettingsDisclosure } from './SettingsDisclosure'

describe('SettingsDisclosure', () => {
  it('starts collapsed, remains accessible, and preserves draft input when reopened', async () => {
    const browser = userEvent.setup()
    render(<SettingsDisclosure title="高级配置" description="默认折叠"><label>草稿<input defaultValue="保留" /></label></SettingsDisclosure>)

    const trigger = screen.getByRole('button', { name: /高级配置/ })
    const content = document.getElementById(trigger.getAttribute('aria-controls') || '')
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    expect(content).toHaveAttribute('hidden')

    await browser.click(trigger)
    const draft = screen.getByRole('textbox', { name: '草稿' })
    await browser.clear(draft)
    await browser.type(draft, '尚未保存的草稿')
    await browser.click(trigger)
    expect(content).toHaveAttribute('hidden')
    await browser.click(trigger)
    expect(screen.getByRole('textbox', { name: '草稿' })).toHaveValue('尚未保存的草稿')
  })
})
