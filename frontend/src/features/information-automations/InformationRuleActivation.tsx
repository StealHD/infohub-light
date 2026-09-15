import type { InformationRule } from '../../api/informationAutomationService'
import { Icons, StableAsyncButton, Tooltip, TooltipTriggerButton, topAnchoredTooltipProps } from '../../design-system'
import { completeRule } from './informationRuleModel'

export type InformationRuleTransitionAction = 'enable' | 'pause' | 'archive' | 'restore'
export type InformationRuleActionState = { ruleId: string; action: InformationRuleTransitionAction | 'delete' } | null

export function InformationRuleActivation({ rule, canMutate, dirty = false, action, onTransition, className = '', compact = false }: {
  rule: InformationRule; canMutate: boolean; dirty?: boolean; action: InformationRuleActionState
  onTransition: (rule: InformationRule, action: InformationRuleTransitionAction) => Promise<void>; className?: string; compact?: boolean
}) {
  const transition = rule.state === 'active' ? 'pause' : rule.state === 'paused' || rule.state === 'draft' ? 'enable' : null
  if (!transition || (rule.state === 'draft' && !completeRule(rule.config))) return null
  const pending = action?.ruleId === rule.id && action.action === transition
  const busy = Boolean(action?.ruleId === rule.id)
  const complete = completeRule(rule.config)
  const label = transition === 'enable' ? '启动' : '暂停'
  const pendingLabel = transition === 'enable' ? '正在启动…' : '正在暂停…'
  const disabledReason = !canMutate ? '当前账号没有管理权限' : dirty ? '请先保存修改' : busy ? '请等待当前操作完成' : undefined
  if (compact) return <Tooltip delay={250}><TooltipTriggerButton aria-label={`${label}任务：${rule.config.name}`}
    aria-description={disabledReason} title={disabledReason}
    pending={pending} disabled={!canMutate || dirty || busy || (transition === 'enable' && !complete)} className={`size-9 shrink-0 rounded-[var(--inteliscope-radius-control)] text-accent hover:bg-default ${className}`}
    onClick={() => onTransition(rule, transition)}>
    {pending ? <Icons.LoaderCircle size={16} className="animate-spin motion-reduce:animate-none" aria-hidden="true" /> : transition === 'enable' ? <Icons.Play size={16} aria-hidden="true" /> : <Icons.Pause size={16} aria-hidden="true" />}
  </TooltipTriggerButton><Tooltip.Content {...topAnchoredTooltipProps}>{pending ? pendingLabel : `${label}任务`}</Tooltip.Content></Tooltip>
  return <StableAsyncButton size="sm" variant="secondary" className={className} pending={pending} pendingContent={<><Icons.LoaderCircle size={15} aria-hidden="true" />{pendingLabel}</>}
    isDisabled={!canMutate || dirty || busy || (transition === 'enable' && !complete)} onPress={() => onTransition(rule, transition)}>
    {transition === 'enable' ? <Icons.Play size={15} aria-hidden="true" /> : <Icons.Pause size={15} aria-hidden="true" />}{label}
  </StableAsyncButton>
}
