import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import type { FeedItem, Subscription } from '../../api/types'
import { DesignSystemProvider } from '../../design-system'
import { InformationArticlePicker } from './InformationArticlePicker'
import { InformationSourcePicker } from './InformationSourcePicker'
import { informationSourceLabel } from './informationSourceLabel'

const source = (id: string, name: string, sourceType = 'rss'): Subscription => ({
  id, user_id: 'alice', source_id: id, source_display_name: name, source_type: sourceType, enabled: true,
})

function shell(node: ReactNode) {
  return render(<MemoryRouter><DesignSystemProvider>{node}</DesignSystemProvider></MemoryRouter>)
}

it('normalizes platform names and commits source changes only after confirmation', async () => {
  const user = userEvent.setup(); const onChange = vi.fn()
  const sources = [source('x', 'X · @author', 'twitter'), source('rss', 'OpenAI News')]
  expect(informationSourceLabel(sources[0])).toBe('X · @author')
  shell(<InformationSourcePicker value={['x']} sources={sources} disabled={false} onChange={onChange} />)
  await user.click(screen.getByRole('button', { name: '选择订阅源' }))
  await user.click(screen.getByRole('checkbox', { name: 'rss · OpenAI News' }))
  await user.click(screen.getByRole('button', { name: '取消' }))
  expect(onChange).not.toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: '选择订阅源' }))
  expect(screen.getByRole('checkbox', { name: 'rss · OpenAI News' })).not.toBeChecked()
  await user.click(screen.getByRole('checkbox', { name: 'rss · OpenAI News' }))
  await user.click(screen.getByRole('button', { name: '确认选择' }))
  expect(onChange).toHaveBeenCalledExactlyOnceWith(['x', 'rss'])
})

it('pages latest-feed article choices ten at a time and preserves cancel semantics', async () => {
  const user = userEvent.setup(); const onConfirm = vi.fn()
  const articles = Array.from({ length: 12 }, (_, index) => ({ id: `article-${index}`, title: `文章 ${index}` })) as FeedItem[]
  shell(<InformationArticlePicker open articles={articles} value={[]} onClose={vi.fn()} onConfirm={onConfirm} />)
  expect(screen.getAllByRole('checkbox')).toHaveLength(10)
  await user.click(screen.getByRole('button', { name: '下一页' }))
  expect(screen.getAllByRole('checkbox')).toHaveLength(2)
  await user.click(screen.getByRole('checkbox', { name: '文章 10' }))
  await user.click(screen.getByRole('button', { name: '确认选择' }))
  expect(onConfirm).toHaveBeenCalledExactlyOnceWith([{ id: 'article-10', title: '文章 10' }])
})
