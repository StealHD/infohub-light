import type { InformationRuleConfig } from '../../api/informationAutomationService'
import { FormSelect, RefreshButton } from '../../design-system'
import { useModelRefresh } from './useModelRefresh'

export function InformationModelFields({ value, onChange, disabled, compactHeading = false }: {
  value: InformationRuleConfig; onChange: (value: InformationRuleConfig) => void; disabled: boolean; compactHeading?: boolean
}) {
  const { models, refresh, refreshing, message, error } = useModelRefresh()
  const selectedModel = models.data?.models.find((model) => model.id === value.model?.id)
  return <fieldset className="grid gap-3">{!compactHeading && <legend className="type-section-title">模型</legend>}
      <div className="flex flex-wrap items-center gap-2"><p className="type-meta text-muted">自动读取 OpenClaw 允许用于独立分析的模型。</p>
        <RefreshButton pending={refreshing || models.isFetching} aria-label="刷新模型目录" onPress={refresh} /></div>
      <FormSelect label="分析模型" value={value.model?.id || ''} isDisabled={disabled || models.data?.status !== 'ready' || !models.data.models.length}
        options={(models.data?.models || []).map((model) => ({ id: model.id, label: model.name }))}
        onChange={(id) => onChange({ ...value, model: { id, thinking: null } })} />
      {selectedModel && selectedModel.thinking_levels.length > 0 && <FormSelect label="推理强度" value={value.model?.thinking || 'default'} isDisabled={disabled}
        options={[{ id: 'default', label: '模型默认' }, ...selectedModel.thinking_levels.map((id) => ({ id, label: id }))]}
        onChange={(thinking) => onChange({ ...value, model: { id: selectedModel.id, thinking: thinking === 'default' ? null : thinking } })} />}
      <p role="status" className="type-meta text-muted">{models.isPending ? '正在加载模型目录…'
        : models.isError ? '模型目录加载失败，请刷新重试。'
        : models.data?.status === 'unavailable' ? '自动化分析尚未配置，由管理员修复接入；无需自行启动服务。'
        : models.data?.status === 'stale' ? '自动化分析目录已过期，请管理员检查分析服务，恢复后本页会自动更新。'
        : !models.data?.models.length ? 'OpenClaw 暂无获准用于独立分析的模型，请检查模型配置与授权后刷新。'
        : value.model && !selectedModel ? '所选模型已不可用，请重新选择。'
        : `已加载 ${models.data.models.length} 个模型，请选择分析模型。`}</p>
      {message && <p role="status" className="type-meta text-muted">{message}</p>}
      {models.data?.filtered_models?.map((item) => <p key={item.id} className="type-meta text-muted">{item.id}：{item.reason === "allowlist_ownership_unknown" ? "旧分析白名单归属不明，请管理员核对后明确管理方式。" : item.reason === "model_unauthorized" ? "管理员未授权此模型。" : "当前分析 Agent 不可用。"}</p>)}
      {error && <p role="alert">{error}</p>}
    </fieldset>
}
