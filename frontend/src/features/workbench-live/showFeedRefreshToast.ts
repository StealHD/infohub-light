import { actionToast } from '../../design-system'

export type FeedRefreshState = 'idle' | 'pending' | 'queued' | 'running' | 'stopping' | 'cancelled' | 'partial' | 'failed' | 'succeeded' | 'blocked' | 'reload_failed'

export function showFeedRefreshToast(state: FeedRefreshState, options: { description: string; onRetry?: () => void }) {
  if (state === 'succeeded') actionToast.success('信息流已更新', options)
  else if (state === 'partial') actionToast.warning('信息流部分更新', options)
  else if (state === 'reload_failed') actionToast.danger('信息流加载失败', options)
  else if (state === 'blocked') actionToast.danger('信息流更新未开始', options)
  else if (state === 'failed') actionToast.danger('信息流更新失败', options)
  else if (state === 'cancelled') actionToast.info('信息流获取已停止', options)
  else actionToast.info('信息流更新状态', options)
}
