import type { InformationRule } from '../../api/informationAutomationService'
import { Icons, Tooltip, TooltipTriggerButton, topAnchoredTooltipProps } from '../../design-system'
import type { InformationRuleActionState, InformationRuleTransitionAction } from './InformationRuleActivation'

export function InformationRuleArchiveAction({ rule, canMutate, dirty, action, onTransition }: {
  rule: InformationRule
  canMutate: boolean
  dirty: boolean
  action: InformationRuleActionState
  onTransition: (rule: InformationRule, action: InformationRuleTransitionAction) => Promise<void>
}) {
  const transition = rule.state === 'archived' ? 'restore' : 'archive'
  const label = transition === 'restore' ? '恢复任务' : '归档任务'
  const pending = action?.ruleId === rule.id && action.action === transition
  const disabled = !canMutate || Boolean(action?.ruleId) || (transition === 'archive' && dirty)
  const disabledReason = !canMutate
    ? '当前账号没有管理权限'
    : action?.ruleId
      ? '请等待当前操作完成'
      : transition === 'archive' && dirty
        ? '请先保存修改'
        : undefined
  const Icon = transition === 'restore' ? Icons.RotateCcw : Icons.Archive
  return <Tooltip delay={250}>
    <TooltipTriggerButton aria-label={`${label}：${rule.config.name}`} aria-description={disabledReason} title={disabledReason} pending={pending} disabled={disabled}
      className="size-9 shrink-0 rounded-[var(--inteliscope-radius-control)] text-muted hover:bg-default"
      onClick={() => onTransition(rule, transition)}>
      {pending ? <Icons.LoaderCircle size={16} className="animate-spin motion-reduce:animate-none" aria-hidden="true" /> : <Icon size={16} aria-hidden="true" />}
    </TooltipTriggerButton>
    <Tooltip.Content {...topAnchoredTooltipProps}>{pending ? (transition === 'restore' ? '正在恢复…' : '正在归档…') : label}</Tooltip.Content>
  </Tooltip>
}
