import type { InformationTest } from '../../api/informationAutomationService'

export function previewStatus(result: InformationTest): string | null {
  const reasons: Record<string, string> = {
    preview_confirmation_required: '这是恢复前的旧测试，需要明确确认后才能执行。',
    preview_superseded: '此旧测试已被重新确认的测试替代。',
    completion_unknown: '任务已领取，但无法确认完成结果。请核对执行记录，不会自动重新推理。',
    offline: '分析服务离线，等待服务恢复。',
    connector_upgrade_required: '执行器未上报执行能力，请升级执行器。',
    execution_disabled: '当前仅同步模型目录，请管理员切换为仅手动测试模式。',
    user_concurrency: '其他分析正在占用并发，完成后继续。',
    daily_semantic_limit: '今日分析额度已用完，等待额度恢复。',
    invalid_model_output: '模型返回格式或引用未通过校验，测试已停止。请重新测试。',
    analysis_timeout: '模型调用超时，测试已停止。请稍后重试。',
    analysis_call_failed: '独立分析调用失败，测试已停止。请检查接入后重试。',
    analysis_model_unavailable: '分析已暂停：模型不可用。请刷新模型目录或更换模型后重新测试。',
    analysis_thinking_unavailable: '分析已暂停：模型不支持当前推理强度，请修改后重新测试。',
  }
  if (result.reason && reasons[result.reason]) return reasons[result.reason]
  if (result.status === 'failed') return '测试未完成，请检查判断服务后重试。'
  if (result.status === 'judging') return '模型正在分析…'
  if (result.status === 'quota_wait') return '今日判断额度已用完，测试仍在队列中。'
  return result.status === 'pending' ? '正在排队等待分析…' : null
}
