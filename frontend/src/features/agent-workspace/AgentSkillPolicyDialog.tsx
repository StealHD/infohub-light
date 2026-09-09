import { useEffect, useMemo, useState } from 'react'

import type { ServiceApi } from '../../api/service'
import type { AgentSkillAdministration, AgentSkillCatalogItem } from '../../api/agentSkillService'
import {
  Button, Checkbox, Input, Label, LoadingState, Modal, StableAsyncButton,
  StatusIndicator, StatusNotice, TextField, actionToast,
} from '../../design-system'

type Filter = 'all' | 'allowed' | 'closed'

function catalogState(skill: AgentSkillCatalogItem) {
  if (skill.disabled === true || skill.enabled === false) return { label: '已停用', tone: 'neutral' as const }
  if (skill.eligible === false) return { label: '条件不足', tone: 'warning' as const }
  return { label: '可使用', tone: 'success' as const }
}

export function AgentSkillPolicyDialog({ open, api, onOpenChange, onSaved }: {
  open: boolean
  api: ServiceApi
  onOpenChange: (open: boolean) => void
  onSaved: () => void
}) {
  const [data, setData] = useState<AgentSkillAdministration | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)

  useEffect(() => {
    if (!open) return
    let active = true
    void Promise.resolve().then(() => {
      if (active) { setLoading(true); setError('') }
      return api.agentSkills()
    }).then((value) => {
      if (!active) return
      setData(value)
      setSelected(new Set(value.policy.allowed_skill_keys))
    }).catch(() => {
      if (active) setError('无法读取完整 Skills 目录，请检查管理员连接后重试。')
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [api, open, reload])

  const rows = useMemo(() => {
    const search = query.trim().toLocaleLowerCase()
    return (data?.skills ?? []).filter((skill) => {
      const allowed = selected.has(skill.skillKey)
      if (filter === 'allowed' && !allowed) return false
      if (filter === 'closed' && allowed) return false
      return !search || `${skill.name ?? ''} ${skill.skillKey} ${skill.description ?? ''}`.toLocaleLowerCase().includes(search)
    })
  }, [data?.skills, filter, query, selected])

  const original = data?.policy.allowed_skill_keys ?? []
  const current = [...selected].sort()
  const changed = JSON.stringify([...original].sort()) !== JSON.stringify(current)
  const needsRetry = data?.policy.sync_state === 'failed'
    || (data?.policy.sync_state === 'pending' && !data.policy.sync_in_progress)

  async function save() {
    if (!data) return
    setSaving(true)
    setError('')
    try {
      const result = await api.updateAgentSkillPolicy(data.policy.revision, current)
      setData({ ...data, policy: result.policy })
      setConfirming(false)
      actionToast.success('Skill 开放范围已同步')
      onSaved()
      onOpenChange(false)
    } catch {
      setConfirming(false)
      setError('开放范围尚未同步。已保留选择，请刷新状态后重试。')
    } finally {
      setSaving(false)
    }
  }

  return <Modal isOpen={open} onOpenChange={(next) => !saving && onOpenChange(next)}>
    <Modal.Backdrop isDismissable={!saving} isKeyboardDismissDisabled={saving}>
      <Modal.Container size="lg"><Modal.Dialog>
        <Modal.Header><Modal.Heading>管理 Skill 开放范围</Modal.Heading></Modal.Header>
        <Modal.Body><div className="grid gap-4">
          <p className="type-body text-muted">这里是完整目录。勾选后，所有普通用户才能查看和使用对应 Skill；新发现的 Skill 默认不开放。</p>
          {data && <p className="type-meta text-muted" aria-live="polite">已开放 {selected.size} / 共 {data.skills.length} 项</p>}
          {data?.policy.sync_state === 'failed' && <StatusNotice title="上次同步失败" status="warning">新聊天仍被保护。保持当前选择并重新保存即可重试。</StatusNotice>}
          {data?.policy.sync_in_progress && <StatusNotice title="开放范围正在同步" status="default">另一项保存正在核验个人 Agent。完成后刷新状态。</StatusNotice>}
          <div className="flex min-w-0 flex-wrap gap-2">
            <TextField className="min-w-0 flex-1" value={query} onChange={setQuery}>
              <Label>搜索 Skills</Label><Input aria-label="搜索 Skills" placeholder="名称或标识" />
            </TextField>
            <div className="flex flex-wrap items-end gap-1" aria-label="开放状态筛选">
              {(['all', 'allowed', 'closed'] as const).map((value) => <Button key={value} size="sm" variant={filter === value ? 'secondary' : 'ghost'} aria-pressed={filter === value} onPress={() => setFilter(value)}>{value === 'all' ? '全部' : value === 'allowed' ? '已开放' : '未开放'}</Button>)}
            </div>
          </div>
          {loading && !data ? <LoadingState label="正在读取完整 Skills 目录" rows={4} /> : null}
          {data && <div className="max-h-[50vh] divide-y divide-separator overflow-y-auto border-y border-separator">
            {rows.map((skill) => <div key={skill.skillKey} className="flex min-w-0 flex-wrap items-center gap-3 py-3">
              <Checkbox isSelected={selected.has(skill.skillKey)} onChange={(checked) => setSelected((currentSet) => {
                const next = new Set(currentSet)
                if (checked) next.add(skill.skillKey); else next.delete(skill.skillKey)
                return next
              })}><Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control><span className="sr-only">{`开放 ${skill.name ?? skill.skillKey}`}</span></Checkbox.Content></Checkbox>
              <div className="min-w-0 flex-1">
                <p className="type-control [overflow-wrap:anywhere]">{skill.name ?? skill.skillKey}</p>
                <p className="type-meta mt-1 line-clamp-2 text-muted [overflow-wrap:anywhere]">{skill.description ?? skill.skillKey}</p>
              </div>
              <StatusIndicator {...catalogState(skill)} />
            </div>)}
            {!rows.length && <p className="type-body py-6 text-center text-muted">没有符合条件的 Skill。</p>}
          </div>}
          {confirming && <StatusNotice title="确认统一开放范围" status="warning">保存后立即影响所有普通用户的下一次 Skill 选择和调用。已开始的对话继续完成。</StatusNotice>}
          {error && <StatusNotice title="Skill 开放范围操作失败" status="danger">{error}</StatusNotice>}
        </div></Modal.Body>
        <Modal.Footer>
          <Button variant="ghost" isDisabled={saving} onPress={() => onOpenChange(false)}>取消</Button>
          {error && <Button variant="secondary" isDisabled={saving} onPress={() => setReload((value) => value + 1)}>刷新状态</Button>}
          {confirming
            ? <StableAsyncButton pending={saving} pendingContent="同步中…" onPress={() => void save()}>确认并同步</StableAsyncButton>
            : <Button isDisabled={!data || data.policy.sync_in_progress || (!changed && !needsRetry)} onPress={() => setConfirming(true)}>保存开放范围</Button>}
        </Modal.Footer>
      </Modal.Dialog></Modal.Container>
    </Modal.Backdrop>
  </Modal>
}
