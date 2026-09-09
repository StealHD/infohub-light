import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { DesignSystemProvider } from '../../design-system'
import type { InformationRule } from '../../api/informationAutomationService'
import { emptyInformationRule } from './informationRuleModel'
import { InformationTaskList } from './InformationTaskList'

const rules: InformationRule[] = ['active', 'paused', 'draft', 'archived'].map((state, index) => ({
  id: String(index), state: state as InformationRule['state'], version: 1, issue: null,
  config: { ...emptyInformationRule(), name: `任务 ${index}`, requirement: `研究 ${index}` },
  source_names: [`来源 ${index}`], created_at: '', updated_at: '', confirmed_at: null,
}))

it('filters actual states and searches names, descriptions and sources without selecting or mutating', async () => {
  const user = userEvent.setup(); const onSelect = vi.fn()
  render(<MemoryRouter><DesignSystemProvider><InformationTaskList rules={rules} selected={null} onSelect={onSelect} loading={false} hasMore /></DesignSystemProvider></MemoryRouter>)
  const list = screen.getByRole('list', { name: '自动化任务' })
  expect(within(list).getAllByRole('listitem')).toHaveLength(4)
  await user.click(screen.getByRole('button', { name: '已开启' }))
  expect(within(list).getAllByRole('listitem')).toHaveLength(1)
  expect(within(list).getByText('任务 0')).toBeVisible()
  await user.click(screen.getByRole('button', { name: '全部' }))
  await user.type(screen.getByRole('searchbox'), '来源 2')
  expect(within(list).getAllByRole('listitem')).toHaveLength(1)
  expect(onSelect).not.toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: '查看与编辑 任务 2' }))
  expect(onSelect).toHaveBeenCalledExactlyOnceWith('2')
  expect(screen.getByText(/搜索与筛选当前已加载任务/)).toBeVisible()
  await user.clear(screen.getByRole('searchbox')); await user.type(screen.getByRole('searchbox'), '不存在')
  expect(screen.getByText('没有匹配的任务')).toBeVisible()
})

it('shows a helpful empty state and never invents completed tasks', () => {
  render(<MemoryRouter><DesignSystemProvider><InformationTaskList rules={[]} selected={null} onSelect={vi.fn()} loading={false} hasMore={false} /></DesignSystemProvider></MemoryRouter>)
  expect(screen.getByText('还没有自动化任务')).toBeVisible()
  expect(screen.queryByRole('button', { name: '已完成' })).not.toBeInTheDocument()
})

it('surfaces the background test state on its task row', () => {
  render(<MemoryRouter><DesignSystemProvider><InformationTaskList rules={rules} selected={null} onSelect={vi.fn()} loading={false} hasMore={false}
    testStatuses={{ '0': 'judging', '1': 'submission_unknown' }} /></DesignSystemProvider></MemoryRouter>)
  expect(screen.getByText('测试分析中')).toBeVisible()
  expect(screen.getByText('测试提交结果未知')).toBeVisible()
})
