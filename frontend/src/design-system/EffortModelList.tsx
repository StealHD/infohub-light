import { ListBox } from '@heroui/react'

export type EffortModelOption = { id: string; name: string; source: string; supportsImages?: boolean }

export function EffortModelList({ models, selectedId, onSelect, disabled = false, label }: {
  models: EffortModelOption[]; selectedId: string | null; onSelect: (id: string) => void; disabled?: boolean; label: string
}) {
  return <ListBox autoFocus="first" aria-label={label} className="effort-model-list" selectionMode="single"
    selectedKeys={selectedId ? [selectedId] : []} disabledKeys={disabled ? models.map((model) => model.id) : []}>
    {models.map((model) => <ListBox.Item id={model.id} key={model.id} textValue={`${model.source} ${model.name}`} aria-label={`${model.source} · ${model.name}`} onPress={() => onSelect(model.id)}>
      <div className="min-w-0"><span className="type-control block [overflow-wrap:anywhere]">{model.name}</span>
        <span className="type-meta text-muted">{model.source}{model.supportsImages ? ' · 支持图片' : ''}</span></div><ListBox.ItemIndicator />
    </ListBox.Item>)}
  </ListBox>
}
