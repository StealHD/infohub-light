type SourceActivation = {
  state: 'enabled' | 'preparing' | 'disabled'
  reason?: string | null
} | null | undefined

const preparingCopy: Record<string, string> = {
  actorops_v2_binding_no_runnable_candidate: '系统正在等待可运行的 Actor。',
  actorops_v2_binding_candidate_manifest_missing: '系统正在补齐 Actor 的本地证明。',
  actorops_v2_binding_candidate_manifest_invalid: 'Actor 的本地证明需要重新准备。',
  actorops_v2_binding_candidate_input_unsupported: '当前 Actor 还不能安全处理这个来源。',
  actorops_v2_route_disabled: '路线暂未启用，系统会在恢复后自动继续。',
  actorops_v2_subscription_inactive: '订阅尚未启用，来源保持准备状态。',
}

export function sourceActivationDescription(
  activation: SourceActivation,
  reusedCount: number,
) {
  const reused = reusedCount > 0 ? `已复用 ${reusedCount} 条已有内容。` : ''
  if (activation?.state === 'enabled') {
    return ['系统已完成本地核验并启用来源。', reused]
      .filter(Boolean)
      .join(' ')
  }
  if (activation?.state === 'preparing') {
    return [
      preparingCopy[activation.reason || ''] || '订阅已保存，系统仍在准备来源。',
      reused,
    ].filter(Boolean).join(' ')
  }
  return reused || undefined
}
