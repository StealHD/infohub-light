import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import { DesignSystemProvider } from '../../design-system'
import type { ServiceApi } from '../../api/service'
import type { InformationRule } from '../../api/informationAutomationService'
import { AgentConnectionProvider } from '../agent-connection/AgentConnectionContext'
import InformationDraftCard from './InformationDraftCard'
import { emptyInformationRule, informationDraftReferences } from './informationRuleModel'

const rule: InformationRule = { id: 'iar_' + 'a'.repeat(32), version: 1, state: 'draft', issue: null,
  config: { ...emptyInformationRule(), name: '可信服务端规则', source_ids: ['source'], target_id: 'target', requirement: 'Find research', model: { id: 'test/model', thinking: null } },
  created_at: '', updated_at: '', confirmed_at: null }
function setup(failure = false, modelStatus = 'ready') {
  const api = { informationRule: failure ? vi.fn().mockRejectedValue(new Error('private detail')) : vi.fn().mockResolvedValue(rule),
    informationModels: vi.fn().mockResolvedValue({ status: modelStatus, models: modelStatus === 'ready' ? [{ id: 'test/model', name: 'Test', thinking_levels: [] }] : [] }),
    refreshInformationModels: vi.fn().mockResolvedValue({ accepted: true }),
    agentConnection: vi.fn().mockResolvedValue({ can_chat: true }),
    subscriptions: vi.fn().mockResolvedValue({ subscriptions: [{ source_id: 'source', enabled: true, source_display_name: '研究动态' }] }),
    notificationServices: vi.fn().mockResolvedValue({ services: [{ id: 'target', name: '测试目标', available: true }] }),
    latestFeed: vi.fn().mockResolvedValue({ items: [{ id: 'article', source_id: 'source', title: 'AI 研究' }] }),
    transitionInformationRule: vi.fn().mockResolvedValue({ ...rule, state: 'active' }),
    informationTestPreview: vi.fn().mockResolvedValue({ version: 1, status: 'completed', results: [{ article_id: 'article', status: 'insufficient' }], sends_notification: false, advances_cursor: false }),
    testInformationRule: vi.fn().mockResolvedValue({ version: 1, results: [{ article_id: 'article', status: 'matched' }], sends_notification: false, advances_cursor: false }),
    updateInformationRule: vi.fn().mockImplementation(async (_id, _version, config) => ({ ...rule, version: 2, config })),
  }
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const mounted = render(<MemoryRouter><QueryClientProvider client={cache}><DesignSystemProvider>
    <AgentConnectionProvider value={{ api: { ...api, informationAutomations: async () => api } as unknown as ServiceApi, userId: 'alice' }}><InformationDraftCard ruleId={rule.id} /></AgentConnectionProvider>
  </DesignSystemProvider></QueryClientProvider></MemoryRouter>)
  return { api, ...mounted }
}
beforeEach(() => sessionStorage.clear())

it('fetches trusted data and requires a separate explicit confirmation before activation', async () => {
  const user = userEvent.setup(); const { api } = setup()
  await screen.findByDisplayValue('可信服务端规则')
  expect(api.transitionInformationRule).not.toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: '确认启用' }))
  expect(api.transitionInformationRule).not.toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: '确认并启用' }))
  await waitFor(() => expect(api.transitionInformationRule).toHaveBeenCalledExactlyOnceWith(rule.id, 1, 'enable'))
})

it('tests the saved version without activating and retains an unsaved draft across remounts', async () => {
  const user = userEvent.setup(); const first = setup()
  await screen.findByDisplayValue('可信服务端规则')
  await user.click(screen.getByRole('button', { name: '测试已保存规则' }))
  await user.click(screen.getByRole('button', { name: '选择文章' }))
  await user.click(await screen.findByRole('checkbox', { name: 'AI 研究' }))
  await user.click(screen.getByRole('button', { name: '确认选择' }))
  await user.dblClick(screen.getByRole('button', { name: '开始测试' }))
  expect(await screen.findByText('测试已完成')).toBeVisible()
  expect(first.api.testInformationRule).toHaveBeenCalledOnce()
  expect(first.api.transitionInformationRule).not.toHaveBeenCalled()
  await waitFor(() => expect(screen.getByRole('button', { name: '开始测试' })).toBeEnabled())
  await new Promise((resolve) => setTimeout(resolve, 550))
  await user.click(screen.getByRole('button', { name: '开始测试' }))
  await waitFor(() => expect(first.api.testInformationRule).toHaveBeenCalledTimes(2))
  await user.clear(screen.getByLabelText('任务名称')); await user.type(screen.getByLabelText('任务名称'), '未保存标题')
  expect(screen.getByRole('button', { name: '确认启用' })).toBeDisabled()
  first.unmount(); setup()
  expect(await screen.findByDisplayValue('未保存标题')).toBeVisible()
})

it('does not render an editable card for an inaccessible reference or expose raw failures', async () => {
  const { api } = setup(true)
  expect(await screen.findByText(/当前账号无法读取/)).toBeVisible()
  expect(screen.queryByText('private detail')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '确认启用' })).not.toBeInTheDocument()
  expect(api.transitionInformationRule).not.toHaveBeenCalled()
  expect(informationDraftReferences(`[[information-automation:${rule.id}]] malicious config [[information-automation:other]]`)).toEqual([rule.id])
})

it('polls a semantic preview without enabling the rule', async () => {
  const user = userEvent.setup(); const { api } = setup()
  api.testInformationRule.mockResolvedValue({ version: 1, preview_id: 'preview', status: 'pending', results: [], sends_notification: false, advances_cursor: false })
  await screen.findByDisplayValue('可信服务端规则')
  await user.click(screen.getByRole('button', { name: '测试已保存规则' }))
  await user.click(screen.getByRole('button', { name: '选择文章' }))
  await user.click(await screen.findByRole('checkbox', { name: 'AI 研究' }))
  await user.click(screen.getByRole('button', { name: '确认选择' }))
  await user.click(screen.getByRole('button', { name: '开始测试' }))
  await user.click(await screen.findByRole('button', { name: '查看逐篇结果（1）' }))
  expect(await screen.findByText('AI 研究：证据不足')).toBeVisible()
  expect(api.informationTestPreview).toHaveBeenCalledOnce()
  expect(api.transitionInformationRule).not.toHaveBeenCalled()
})

it('explains missing connector metadata and enables model selection after refresh', async () => {
  const user = userEvent.setup(); const { api } = setup(false, 'unavailable')
  expect(await screen.findByText(/尚未收到独立分析 connector/)).toBeVisible()
  expect(screen.getByRole('button', { name: /分析模型/ })).toBeDisabled()
  api.informationModels.mockResolvedValue({ status: 'ready', models: [{ id: 'test/model', name: 'Test', thinking_levels: [] }] })
  await user.click(screen.getByRole('button', { name: '刷新模型目录' }))
  expect(await screen.findByText('已加载 1 个模型，请选择分析模型。')).toBeVisible()
  await user.click(screen.getByRole('button', { name: /分析模型/ }))
  expect(await screen.findByRole('option', { name: 'Test' })).toBeVisible()
  expect(api.refreshInformationModels).toHaveBeenCalledOnce()
  expect(api.transitionInformationRule).not.toHaveBeenCalled()
})

it('keeps an empty authorized catalog disabled with a specific explanation', async () => {
  const { api } = setup(false, 'unavailable')
  api.informationModels.mockResolvedValue({ status: 'ready', models: [] })
  expect(await screen.findByText(/暂无获准用于独立分析的模型/)).toBeVisible()
  expect(screen.getByRole('button', { name: /分析模型/ })).toBeDisabled()
})


it('explains blocked and failed previews rather than showing indefinite analysis', async () => {
  const { previewStatus } = await import('./previewStatus')
  const base = { version: 2, results: [], sends_notification: false as const, advances_cursor: false as const }
  expect(previewStatus({ ...base, status: 'pending', reason: 'analysis_model_unavailable' })).toContain('分析已暂停')
  expect(previewStatus({ ...base, status: 'failed', reason: 'invalid_model_output' })).toContain('格式或引用')
  expect(previewStatus({ ...base, status: 'judging' })).toBe('模型正在分析…')
})
