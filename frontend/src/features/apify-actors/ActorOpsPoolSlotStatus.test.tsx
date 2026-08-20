import { screen, within } from '@testing-library/react'
import { expect, it } from 'vitest'

import { poolManagementDetail, renderPoolManagement } from './actorOpsPoolManagementTestFixtures'

it('does not present a non-runnable certified primary as running', async () => {
  const detail = poolManagementDetail()
  detail.slots[0] = { ...detail.slots[0], runnable: false }

  renderPoolManagement(detail)

  await screen.findByText('publisher-a primary')
  const primary = document.querySelector('[data-actorops-slot="primary"]')
  expect(primary).not.toBeNull()
  expect(within(primary as HTMLElement).getByText('需要处理')).toBeVisible()
  expect(primary).not.toHaveTextContent('运行中')
  expect(screen.getByText(/主用\/备用是配置优先级/)).toBeVisible()
})
