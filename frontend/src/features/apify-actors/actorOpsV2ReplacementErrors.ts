import { ApiError } from '../../api/client'

const ERROR_LABELS: Record<string, string> = {
  actorops_maintenance_actor_unavailable: '该 Actor 已不可用。',
  actorops_maintenance_revision_changed: '固定 Build 已不可用或版本身份已经变化。',
  actorops_v2_candidate_contract_invalid: '候选的固定输出合同与当前 Build 不一致。',
  actorops_replacement_contract_invalid: '候选与当前来源的输入或输出合同不兼容。',
  actorops_replacement_target_native_id_missing: '候选输入要求目标平台原生用户 ID，但当前来源只有账号 handle/URL。请改选支持 handle 的 Actor。',
  actorops_replacement_target_handle_missing: '候选输入要求账号 handle，但当前来源没有可验证的 handle。',
  actorops_replacement_target_url_missing: '候选输入要求账号主页 URL，但当前来源没有可验证的 URL。',
  actorops_replacement_target_context_missing: '候选输入依赖当前来源没有提供的目标字段，无法安全生成请求。',
  actorops_replacement_manifest_invalid: '候选的固定 Manifest 无效，无法安全生成请求。',
  actorops_replacement_input_contract_invalid: '候选输入模板无法转换为当前来源所需的安全请求。',
  actorops_replacement_candidate_unavailable: '该候选已确认故障，不能用于替换。',
  actorops_replacement_contract_mismatch: '返回内容无法安全映射为目标账号的更新，已停止这个候选 Actor。',
  actorops_replacement_published_at_invalid: '返回的帖子发布时间字段无法解析；请查看字段格式后使用零费用重验。',
  actorops_replacement_target_identity_mismatch: '返回的作者用户名与订阅账号不一致。',
  actorops_replacement_output_url_invalid: '返回或派生的帖子 URL 不符合当前平台地址规则。',
  actorops_replacement_output_outside_window: '返回的帖子发布时间不在本次实测窗口内。',
  actorops_replacement_nested_extraction_failed: '未能从真实 Dataset 的嵌套列表定位发布内容。',
  actorops_replacement_mixed_rows_unclassified: '真实 Dataset 混有多种记录，仍有发布型记录无法安全分类。',
  actorops_replacement_dataset_run_unbound: 'Dataset 无法与本次 Run 精确绑定，系统不会猜测或读取历史同名 Dataset。',
  actorops_replacement_dataset_expansion_overflow: '真实 Dataset 展开后超过 100 条安全验证上限。',
  actorops_replacement_observed_mapping_failed: '两轮真实字段重映射后仍无法严格证明；该 Actor 未被判定故障。',
  actorops_replacement_no_evidence: '没有取得可证明的更新内容，未自动测试其他候选 Actor。',
  actorops_replacement_plan_stale: '来源、价格或槽位已变化，请重新创建计划。',
  actorops_replacement_target_changed: '来源目标已经变化，请刷新后重新选择。',
  actorops_replacement_route_not_ready: '路线没有可用于验证的就绪来源。',
  actorops_replacement_credential_unavailable: '当前没有可用 validation 凭据，候选 Actor 没有被惩罚。',
  actorops_maintenance_pricing_unavailable: '无法确认该 Actor 的运行价格。',
  actorops_maintenance_price_cap_exceeded: '该 Actor 的价格超过当前单次费用上限。',
  actorops_maintenance_preflight_unavailable: '暂时无法读取 Apify Build 元数据，请稍后重试。',
}

const FREE_FAILURES = new Set([
  ...Object.keys(ERROR_LABELS),
].filter((code) => ![
  'actorops_replacement_contract_mismatch',
  'actorops_replacement_published_at_invalid',
  'actorops_replacement_target_identity_mismatch',
  'actorops_replacement_output_url_invalid',
  'actorops_replacement_output_outside_window',
  'actorops_replacement_nested_extraction_failed',
  'actorops_replacement_mixed_rows_unclassified',
  'actorops_replacement_dataset_run_unbound',
  'actorops_replacement_dataset_expansion_overflow',
  'actorops_replacement_observed_mapping_failed',
  'actorops_replacement_no_evidence',
  'actorops_replacement_plan_stale',
].includes(code)))

const UNKNOWN_ERROR = '替换计划未通过；没有自动测试其他候选 Actor。'

export function replacementError(code: string | null) {
  return ERROR_LABELS[code || ''] || UNKNOWN_ERROR
}

export function replacementFailureCostMessage(code: string | null) {
  return FREE_FAILURES.has(code || '')
    ? '已在创建 Attempt 和 Apify Run 前停止，费用为 $0。'
    : '可能已有运行或待对账费用，请查看运行详情。'
}

export function replacementRequestError(error: unknown, fallback: string) {
  if (!(error instanceof ApiError)) return fallback
  const message = replacementError(error.code)
  return message === UNKNOWN_ERROR ? error.message || fallback : message
}
