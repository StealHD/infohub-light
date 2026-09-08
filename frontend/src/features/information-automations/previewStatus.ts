import type { InformationTest } from '../../api/informationAutomationService'

export function previewStatus(result: InformationTest): string | null {
  const reasons: Record<string, string> = {
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
