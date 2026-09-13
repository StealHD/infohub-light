import type { InformationRuleConfig } from '../../api/informationAutomationService'
import { FormSelect, RefreshButton } from '../../design-system'
import { useModelRefresh } from './useModelRefresh'

export function InformationModelFields({ value, onChange, disabled, compactHeading = false }: {
  value: InformationRuleConfig; onChange: (value: InformationRuleConfig) => void; disabled: boolean; compactHeading?: boolean
}) {
  const { models, refresh, refreshing, message, error } = useModelRefresh()
  const selectedModel = models.data?.models.find((model) => model.id === value.model?.id)
  return <fieldset className="grid gap-3">{!compactHeading && <legend className="type-section-title">模型</legend>}
      <div className="flex flex-wrap items-center gap-2"><p className="type-meta text-muted">直接读取当前用户 OpenClaw 已配置且可用的模型。</p>
        <RefreshButton pending={refreshing || models.isFetching} aria-label="刷新模型目录" onPress={refresh} /></div>
      <FormSelect label="分析模型" value={value.model?.id || ''} isDisabled={disabled || models.data?.status !== 'ready' || !models.data.models.length}
        options={(models.data?.models || []).map((model) => ({ id: model.id, label: model.name }))}
        onChange={(id) => onChange({ ...value, model: { id, thinking: null } })} />
      {selectedModel && selectedModel.thinking_levels.length > 0 && <FormSelect label="推理强度" value={value.model?.thinking || 'default'} isDisabled={disabled}
        options={[{ id: 'default', label: '模型默认' }, ...selectedModel.thinking_levels.map((id) => ({ id, label: id }))]}
        onChange={(thinking) => onChange({ ...value, model: { id: selectedModel.id, thinking: thinking === 'default' ? null : thinking } })} />}
      <p role="status" className="type-meta text-muted">{models.isPending ? '正在加载模型目录…'
        : models.isError ? '模型目录加载失败，请刷新重试。'
        : models.data?.status === 'unavailable' ? '尚未读取模型目录；点击刷新将直接读取本机 OpenClaw 配置。'
        : models.data?.status === 'stale' ? '模型目录已过期，请刷新以重新读取 OpenClaw 配置。'
        : !models.data?.models.length ? 'OpenClaw 当前没有可用模型，请检查你的模型配置后刷新。'
        : value.model && !selectedModel ? '所选模型已不可用，请重新选择。'
        : `已加载 ${models.data.models.length} 个模型，请选择分析模型。`}</p>
      {message && <p role="status" className="type-meta text-muted">{message}</p>}
      {models.data?.filtered_models?.map((item) => <p key={item.id} className="type-meta text-muted">{item.id}：{item.reason === "allowlist_ownership_unknown" ? "OpenClaw 配置限制了此模型。" : item.reason === "model_unauthorized" ? "管理员未授权此模型。" : "当前分析 Agent 不可用。"}</p>)}
      {error && <p role="alert">{error}</p>}
    </fieldset>
}
