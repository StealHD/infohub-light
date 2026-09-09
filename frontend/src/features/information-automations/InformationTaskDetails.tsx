import { lazy, Suspense, useCallback, useRef, useState } from 'react'
import type { InformationRule, InformationRuleConfig } from '../../api/informationAutomationService'
import { Button, StableAsyncButton, StatusIndicator, Tabs } from '../../design-system'
import { InformationTaskOverview } from './InformationTaskOverview'
import { InformationTestPanel } from './InformationTestPanel'
import { InformationRuleRuns } from './InformationRuleRuns'
import { ruleStateLabels } from './informationRuleModel'
import { useInformationContext } from './useInformationContext'
import type { InformationTestSession, TestArticleSelection } from './useInformationTests'
const Editor = lazy(() => import('./InformationRuleEditor').then((module) => ({ default: module.InformationRuleEditor })))
const NewRule = lazy(() => import('./InformationNewRule').then((module) => ({ default: module.InformationNewRule })))

type Tab = 'overview' | 'test' | 'runs'

export function InformationTaskDetails({ rule, creating, canMutate, onClose, onSaved, onBusyChange, testSession, onTestSelect, onTestStart }: {
  rule?: InformationRule; creating: boolean; canMutate: boolean; onClose: () => void
  onSaved: (rule: InformationRule) => Promise<unknown>; onBusyChange: (busy: boolean) => void
  testSession?: InformationTestSession; onTestSelect: (value: TestArticleSelection[]) => void; onTestStart: () => Promise<void>
}) {
  const { api } = useInformationContext()
  const [tab, setTab] = useState<Tab>('overview')
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<InformationRuleConfig | null>(rule?.config || null)
  const [dirty, setDirty] = useState(false)
  const [action, setAction] = useState('')
  const [error, setError] = useState('')
  const lock = useRef(false)
  const handleDraftChange = useCallback((config: InformationRuleConfig, changed: boolean) => {
    setDraft(config); setDirty(changed)
  }, [])
  if (creating) return <Suspense fallback={<p role="status">正在加载新建表单…</p>}><NewRule onCancel={onClose} onBusyChange={onBusyChange} onSaved={async (saved) => { await onSaved(saved) }} /></Suspense>
  if (!rule || !draft || !testSession) return <p className="type-body text-muted">任务不在当前列表中，请关闭详情后刷新列表。</p>
  const transition = async (kind: 'pause' | 'archive' | 'restore') => {
    if (lock.current) return
    lock.current = true; setAction(kind); setError(''); onBusyChange(true)
    try { await onSaved(await api.transitionInformationRule(rule.id, rule.version, kind)) }
    catch (failure) { setError(failure instanceof Error ? failure.message : '任务状态更新失败，请重试。') }
    finally { lock.current = false; setAction(''); onBusyChange(false) }
  }
  return <div className="grid min-w-0 gap-4 [overflow-wrap:anywhere]">
    <div className="flex flex-wrap items-center gap-2"><StatusIndicator label={ruleStateLabels[rule.state]} tone={rule.state === 'active' ? 'success' : 'neutral'} />
      {dirty && <span className="type-meta text-warning">未保存</span>}<span className="min-w-0 flex-1" />
      {!editing && <Button size="sm" variant="secondary" isDisabled={!canMutate || rule.state === 'archived'} onPress={() => { setTab('overview'); setEditing(true) }}>编辑</Button>}
      {rule.state === 'active' && <StableAsyncButton size="sm" variant="secondary" pending={action === 'pause'} pendingContent="正在暂停…" isDisabled={!canMutate || dirty || Boolean(action)} onPress={() => transition('pause')}>暂停</StableAsyncButton>}
      {rule.state === 'archived'
        ? <StableAsyncButton size="sm" variant="secondary" pending={action === 'restore'} pendingContent="正在恢复…" isDisabled={!canMutate || Boolean(action)} onPress={() => transition('restore')}>恢复</StableAsyncButton>
        : <StableAsyncButton size="sm" variant="ghost" pending={action === 'archive'} pendingContent="正在归档…" isDisabled={!canMutate || dirty || Boolean(action)} onPress={() => transition('archive')}>归档</StableAsyncButton>}
    </div>
    {error && <p role="alert">{error}</p>}
    <Tabs selectedKey={tab} onSelectionChange={(key) => setTab(String(key) as Tab)}>
      <Tabs.List aria-label="任务详情页面" className="flex gap-1 border-b border-separator pb-2">
        <Tabs.Tab id="overview">概览<Tabs.Indicator /></Tabs.Tab>
        <Tabs.Tab id="test">测试<Tabs.Indicator /></Tabs.Tab>
        <Tabs.Tab id="runs">运行记录<Tabs.Indicator /></Tabs.Tab>
      </Tabs.List>
      <Tabs.Panel id="overview" className="pt-4">
      {!editing && <InformationTaskOverview rule={rule} config={draft} dirty={dirty} />}
      <div hidden={!editing} inert={!editing}><Suspense fallback={<p role="status">正在加载编辑器…</p>}><Editor rule={rule} canMutate={canMutate} onSaved={onSaved} onBusyChange={onBusyChange}
        onExit={() => setEditing(false)} onDraftChange={handleDraftChange} /></Suspense></div>
      </Tabs.Panel>
      <Tabs.Panel id="test" className="pt-4"><InformationTestPanel rule={rule} dirty={dirty} canMutate={canMutate}
        session={testSession} onSelect={onTestSelect} onStart={onTestStart} /></Tabs.Panel>
      <Tabs.Panel id="runs" className="pt-4"><InformationRuleRuns ruleId={rule.id} /></Tabs.Panel>
    </Tabs>
  </div>
}
