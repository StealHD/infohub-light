import { Icons, Tooltip, TooltipTriggerButton, bottomAnchoredTooltipProps } from '../../design-system'

type FeedRefreshButtonProps = {
  role: 'owner' | 'admin' | 'member' | 'viewer'
  pending: boolean
  stopping: boolean
  canStop: boolean
  onRefresh: () => void
  onStop: () => void
}

export function FeedRefreshButton(props: FeedRefreshButtonProps) {
  const busy = props.pending || props.stopping
  const label = props.stopping ? '正在安全停止获取新内容' : props.pending ? '正在提交获取新内容' : props.canStop ? '安全停止获取新内容' : '获取新内容'
  const help = props.role === 'viewer'
    ? '只读账户不可获取新内容'
    : props.stopping
      ? '正在等待任务到达安全停止边界'
      : props.pending
        ? '正在提交本次获取任务'
      : props.canStop
        ? '安全停止本次获取；已发出的调用会先结束'
        : props.role === 'member'
          ? '仅刷新你自己的私人订阅'
          : '刷新你的私人订阅及已订阅的公共来源'
  return <Tooltip delay={500}>
    <TooltipTriggerButton
      className="size-8 shrink-0 rounded-lg text-muted hover:bg-default hover:text-foreground active:scale-95 motion-reduce:transform-none"
      aria-label={label}
      disabled={props.role === 'viewer'}
      pending={busy}
      onClick={props.canStop ? props.onStop : props.onRefresh}
    >{props.stopping
      ? <Icons.LoaderCircle size={14} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
      : props.canStop
        ? <Icons.Square size={12} fill="currentColor" aria-hidden="true" />
        : <Icons.Download size={14} aria-hidden="true" />}</TooltipTriggerButton>
    <Tooltip.Content {...bottomAnchoredTooltipProps}>{help}</Tooltip.Content>
  </Tooltip>
}
