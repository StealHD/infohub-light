export function cleanupLabel(phase: string) {
  if (phase === 'complete') return '已撤销，历史数据保留'
  if (phase === 'failed' || phase === 'recovery') return '权限已撤销，OpenClaw 清理待完成'
  return '正在撤销 · ' + ({ queued: '等待清理', stopping: '停止成员运行', removing: '移除专属配置', verifying: '核验清理结果' }[phase] || '核对状态')
}
