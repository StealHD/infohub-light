const messages: Record<string, string> = {
  MODEL_PARAMETER_UNSUPPORTED: '参数不兼容，请重新选择模型和推理强度。内容已保留。',
  PERSONAL_TOOLS_UNAVAILABLE: '个人数据工具未就绪，请管理员修复 Agent 接入。',
  MODEL_AUTH_FAILED: '模型认证失败，请管理员检查该模型的授权。',
  MODEL_QUOTA_LIMITED: '模型额度受限，请稍后手动重试或检查额度。',
  MODEL_CALL_TIMEOUT: '调用超时，结果可能尚未确认，请先检查运行状态。',
  RELAY_REQUEST_FAILED: 'OpenClaw 未能完成请求，请检查运行状态后手动重试。',
}

export function openClawSafeError(code?: string): string | undefined {
  return code && Object.hasOwn(messages, code) ? messages[code] : undefined
}
