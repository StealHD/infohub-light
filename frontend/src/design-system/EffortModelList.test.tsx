import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { EffortModelList } from './EffortModelList'

it('uses the latest selection handler with cached model items and supports keyboard reselect', async () => {
  const user = userEvent.setup()
  const models = [{ id: 'source/gpt', name: 'GPT', source: 'source' }]
  const oldSelect = vi.fn(); const latestSelect = vi.fn()
  const { rerender } = render(<EffortModelList models={models} selectedId="source/gpt" onSelect={oldSelect} label="模型" />)
  rerender(<EffortModelList models={models} selectedId="source/gpt" onSelect={latestSelect} label="模型" />)
  screen.getByRole('option', { name: 'source · GPT' }).focus()
  await user.keyboard('{Enter}')
  expect(latestSelect).toHaveBeenCalledExactlyOnceWith('source/gpt')
  expect(oldSelect).not.toHaveBeenCalled()
  rerender(<EffortModelList models={models} selectedId="source/gpt" onSelect={latestSelect} label="模型" disabled />)
  await user.click(screen.getByRole('option', { name: 'source · GPT' }))
  expect(latestSelect).toHaveBeenCalledTimes(1)
})
