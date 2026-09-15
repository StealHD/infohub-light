import { lazy, Suspense, useCallback, useState } from 'react'
import type { InformationRule, InformationRuleConfig } from '../../api/informationAutomationService'
import { Icons, StatusIndicator, Tabs, Tooltip, TooltipTriggerButton, topAnchoredTooltipProps } from '../../design-system'
import { InformationRuleActivation, type InformationRuleActionState, type InformationRuleTransitionAction } from './InformationRuleActivation'
import { InformationRuleDelete } from './InformationRuleDelete'
import { InformationRuleArchiveAction } from './InformationRuleArchiveAction'
import { InformationTaskOverview } from './InformationTaskOverview'
import { InformationTestPanel } from './InformationTestPanel'
import { InformationRuleRuns } from './InformationRuleRuns'
import { ruleStateLabels } from './informationRuleModel'
import type { InformationTestSession, TestArticleSelection } from './useInformationTests'
const Editor = lazy(() => import('./InformationRuleEditor').then((module) => ({ default: module.InformationRuleEditor })))
const NewRule = lazy(() => import('./InformationNewRule').then((module) => ({ default: module.InformationNewRule })))

type Tab = 'overview' | 'test' | 'runs'

export function InformationTaskDetails({ rule, creating, canMutate, onClose, onSaved, onBusyChange, onDirtyChange, testSession, onTestSelect, onTestTextChange, onTestConfigureNotification, onTestStart, action, onTransition, onDelete, transitionError }: {
  rule?: InformationRule; creating: boolean; canMutate: boolean; onClose: () => void
  onSaved: (rule: InformationRule) => Promise<unknown>; onBusyChange: (busy: boolean) => void
  onDirtyChange?: (dirty: boolean) => void
  testSession?: InformationTestSession; onTestSelect: (value: TestArticleSelection[]) => void
  onTestTextChange: (value: string) => void; onTestConfigureNotification: (send: boolean, target: string | null) => void; onTestStart: () => Promise<void>
  action: InformationRuleActionState; onTransition: (rule: InformationRule, action: InformationRuleTransitionAction) => Promise<void>
  onDelete: (rule: InformationRule) => Promise<void>; transitionError?: string
}) {
  const [tab, setTab] = useState<Tab>('overview')
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<InformationRuleConfig | null>(rule?.config || null)
  const [dirty, setDirty] = useState(false)
  const handleDraftChange = useCallback((config: InformationRuleConfig, changed: boolean) => {
    setDraft(config); setDirty(changed); onDirtyChange?.(changed)
  }, [onDirtyChange])
  if (creating) return <Suspense fallback={<p role="status">正在加载新建表单…</p>}><NewRule onCancel={onClose} onBusyChange={onBusyChange} onSaved={async (saved) => { await onSaved(saved) }} /></Suspense>
  if (!rule || !draft || !testSession) return <p className="type-body text-muted">任务不在当前列表中，请关闭详情后刷新列表。</p>
  const pending = action?.ruleId === rule.id
  const editDisabledReason = !canMutate
    ? '当前账号没有编辑权限'
    : rule.state === 'archived'
      ? '请先恢复任务'
      : pending
        ? '请等待当前操作完成'
        : undefined
  return <div className="grid min-w-0 gap-4 [overflow-wrap:anywhere]">
    <div className="flex flex-wrap items-center gap-2"><StatusIndicator label={ruleStateLabels[rule.state]} tone={rule.state === 'active' ? 'success' : 'neutral'} />
      {dirty && <span className="type-meta text-warning">未保存</span>}<span className="min-w-0 flex-1" />
      {!editing && <Tooltip delay={250}><TooltipTriggerButton aria-label={`编辑任务：${rule.config.name}`} aria-description={editDisabledReason} title={editDisabledReason} disabled={Boolean(editDisabledReason)}
        className="size-9 shrink-0 rounded-[var(--inteliscope-radius-control)] text-accent hover:bg-default"
        onClick={() => { setTab('overview'); setEditing(true) }}><Icons.Pencil size={16} aria-hidden="true" /></TooltipTriggerButton>
        <Tooltip.Content {...topAnchoredTooltipProps}>编辑任务</Tooltip.Content></Tooltip>}
      <InformationRuleActivation compact rule={rule} canMutate={canMutate} dirty={dirty} action={action} onTransition={onTransition} />
      <InformationRuleArchiveAction rule={rule} canMutate={canMutate} dirty={dirty} action={action} onTransition={onTransition} />
      <InformationRuleDelete compact rule={rule} canMutate={canMutate} dirty={dirty} action={action} onDelete={onDelete} />
    </div>
    {transitionError && <p role="alert">{transitionError}</p>}
    <Tabs selectedKey={tab} onSelectionChange={(key) => setTab(String(key) as Tab)}>
      <Tabs.List aria-label="任务详情页面" className="flex gap-1 border-b border-separator pb-2">
        <Tabs.Tab id="overview">概览<Tabs.Indicator /></Tabs.Tab>
        <Tabs.Tab id="test">测试<Tabs.Indicator /></Tabs.Tab>
        <Tabs.Tab id="runs">运行记录<Tabs.Indicator /></Tabs.Tab>
      </Tabs.List>
      <Tabs.Panel id="overview" className="pt-4">
      {!editing && <InformationTaskOverview rule={rule} config={draft} dirty={dirty} onViewRuns={() => setTab('runs')} />}
      <div hidden={!editing} inert={!editing}><Suspense fallback={<p role="status">正在加载编辑器…</p>}><Editor rule={rule} canMutate={canMutate} onSaved={onSaved} onBusyChange={onBusyChange}
        onExit={() => setEditing(false)} onDraftChange={handleDraftChange} /></Suspense></div>
      </Tabs.Panel>
      <Tabs.Panel id="test" className="pt-4"><InformationTestPanel rule={rule} dirty={dirty} canMutate={canMutate}
        session={testSession} onSelect={onTestSelect} onTextChange={onTestTextChange} onConfigureNotification={onTestConfigureNotification} onStart={onTestStart} /></Tabs.Panel>
      <Tabs.Panel id="runs" className="pt-4"><InformationRuleRuns ruleId={rule.id} /></Tabs.Panel>
    </Tabs>
  </div>
}
