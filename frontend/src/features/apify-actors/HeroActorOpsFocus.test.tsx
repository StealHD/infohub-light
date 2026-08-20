import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it } from 'vitest'

import { poolManagementDetail, renderPoolManagement } from './actorOpsPoolManagementTestFixtures'

it('restores focus to the real revision rollback trigger after cancellation', async () => {
  const base = poolManagementDetail()
  const detail = {
    ...base,
    revisions: [
      ...base.revisions,
      {
        ...base.revisions[0], revision_id: 'revision-primary-old',
        build_id: 'build-primary-old', build_number: '0.9.1',
        lifecycle: 'superseded' as const, can_activate: true,
      },
    ],
  }
  renderPoolManagement(detail)
  const browser = userEvent.setup()

  await browser.click(await screen.findByRole('button', { name: /^高级设置与技术详情/ }))
  await browser.click(screen.getByRole('button', { name: /^Revision 差异与回滚/ }))
  const trigger = screen.getByRole('button', { name: /回滚到此 Revision/ })
  await browser.click(trigger)
  expect(await screen.findByRole('heading', { name: '回滚不可变 Revision' })).toBeVisible()
  await browser.click(screen.getByRole('button', { name: '取消' }))
  await waitFor(() => expect(trigger).toHaveFocus())
})
