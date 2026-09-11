const messages: Record<string, string> = {
  MODEL_PARAMETER_UNSUPPORTED: '参数不兼容，请重新选择模型和推理强度。内容已保留。',
  PERSONAL_TOOLS_UNAVAILABLE: '个人数据工具未就绪，请管理员修复 Agent 接入。',
  MODEL_AUTH_FAILED: '模型认证失败，请管理员检查该模型的授权。',
  MODEL_QUOTA_LIMITED: '模型额度受限，请稍后手动重试或检查额度。',
  MODEL_CALL_TIMEOUT: '调用超时，结果可能尚未确认，请先检查运行状态。',
  MODEL_UPSTREAM_UNAVAILABLE: '模型服务暂不可用，请稍后手动重试。',
  MODEL_CONTEXT_LIMIT: '对话超出模型上下文限制，请新建对话或减少输入。',
  MODEL_REFUSED: '模型未能处理本次请求，请调整内容后重试。',
  FAILURE_REASON_UNAVAILABLE: '本次运行失败，具体原因不可用。请核对运行记录后再重试。',
  RELAY_REQUEST_FAILED: 'OpenClaw 未能完成请求，请检查运行状态后手动重试。',
}

export function openClawSafeError(code?: string): string | undefined {
  return code && Object.hasOwn(messages, code) ? messages[code] : undefined
}
