import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'
import { expect, it, vi } from 'vitest'
import { DesignSystemProvider } from '../../design-system'
import type { InformationRule } from '../../api/informationAutomationService'
import { InformationTaskDetails } from './InformationTaskDetails'
import { InformationTestPanel } from './InformationTestPanel'

const api = {
  subscriptions: vi.fn().mockResolvedValue({ subscriptions: [] }),
  notificationServices: vi.fn().mockResolvedValue({ services: [] }),
  informationRuns: vi.fn().mockResolvedValue({ items: [], has_more: false, next_offset: null }),
  latestFeed: vi.fn().mockResolvedValue({ items: [] }),
}
vi.mock('./useInformationContext', () => ({ useInformationContext: () => ({ api, userId: 'alice' }) }))

const rule: InformationRule = {
  id: 'iar_' + 'a'.repeat(32), version: 3, state: 'active', issue: null,
  config: {
    schema_version: 2, name: '研究提醒', source_ids: ['source'], target_id: null,
    requirement: '第一行说明\n第二行说明\n第三行说明\n第四行说明\n第五行说明',
    trigger: { kind: 'each', count: 1, max_wait_seconds: null, interval_seconds: 60, time: '09:00', weekdays: [], timezone: 'Asia/Shanghai' },
    model: { id: 'test/model', thinking: null },
  },
  created_at: '2026-09-15T00:00:00Z', updated_at: '2026-09-15T00:00:00Z', confirmed_at: null,
}

function frame(content: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<MemoryRouter><QueryClientProvider client={queryClient}><DesignSystemProvider>{content}</DesignSystemProvider></QueryClientProvider></MemoryRouter>)
}

it('uses named icon actions and preserves delete confirmation failures', async () => {
  const user = userEvent.setup()
  const onDelete = vi.fn().mockRejectedValue(new Error('删除失败，请重试。'))
  frame(<InformationTaskDetails rule={rule} creating={false} canMutate onClose={vi.fn()} onSaved={vi.fn()} onBusyChange={vi.fn()}
    testSession={{ ruleId: rule.id, version: rule.version, selection: [], customText: '', sendNotification: false, notificationTargetId: null, phase: 'idle' }}
    onTestSelect={vi.fn()} onTestTextChange={vi.fn()} onTestConfigureNotification={vi.fn()} onTestStart={vi.fn()}
    action={null} onTransition={vi.fn()} onDelete={onDelete} />)

  expect(screen.getByRole('button', { name: '编辑任务：研究提醒' })).toBeVisible()
  expect(screen.getByRole('button', { name: '暂停任务：研究提醒' })).toBeVisible()
  expect(screen.getByRole('button', { name: '归档任务：研究提醒' })).toBeVisible()
  expect(screen.getByRole('button', { name: '删除任务：研究提醒' })).toBeVisible()
  await user.hover(screen.getByRole('button', { name: '编辑任务：研究提醒' }))
  expect(await screen.findByRole('tooltip')).toHaveTextContent('编辑任务')

  await user.click(screen.getByRole('button', { name: '展开完整描述' }))
  expect(screen.getByRole('button', { name: '收起完整描述' })).toHaveAttribute('aria-expanded', 'true')
  await user.click(screen.getByRole('button', { name: '删除任务：研究提醒' }))
  await user.click(screen.getByRole('button', { name: '取消' }))
  expect(onDelete).not.toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: '删除任务：研究提醒' }))
  await user.click(screen.getByRole('button', { name: '确认删除' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('删除失败，请重试。')
  expect(screen.getByRole('dialog')).toBeVisible()
})

it('keeps test selection and submission actions right aligned', () => {
  frame(<InformationTestPanel rule={rule} dirty={false} canMutate
    session={{ ruleId: rule.id, version: rule.version, selection: [], customText: '', sendNotification: false, notificationTargetId: null, phase: 'idle' }}
    onSelect={vi.fn()} onTextChange={vi.fn()} onConfigureNotification={vi.fn()} onStart={vi.fn()} />)
  expect(screen.getByRole('button', { name: '选择文章' }).parentElement).toHaveClass('justify-between')
  expect(screen.getByRole('button', { name: '开始测试' }).parentElement).toHaveClass('justify-end')
})

it('keeps permission-disabled icon actions named and explains why they are unavailable', () => {
  frame(<InformationTaskDetails rule={rule} creating={false} canMutate={false} onClose={vi.fn()} onSaved={vi.fn()} onBusyChange={vi.fn()}
    testSession={{ ruleId: rule.id, version: rule.version, selection: [], customText: '', sendNotification: false, notificationTargetId: null, phase: 'idle' }}
    onTestSelect={vi.fn()} onTestTextChange={vi.fn()} onTestConfigureNotification={vi.fn()} onTestStart={vi.fn()}
    action={null} onTransition={vi.fn()} onDelete={vi.fn()} />)
  for (const name of ['编辑任务：研究提醒', '暂停任务：研究提醒', '归档任务：研究提醒', '删除任务：研究提醒']) {
    expect(screen.getByRole('button', { name })).toBeDisabled()
    expect(screen.getByRole('button', { name })).toHaveAttribute('title', expect.stringContaining('权限'))
  }
})
