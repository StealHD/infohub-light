import { useState } from 'react'
import { Button, EmptyState, Modal, OverflowValue, StatusIndicator } from '../../design-system'
import type { OpenClawSkill, OpenClawSkillsStatus } from '../openclaw/workspace/openclawWorkspaceContracts'

function skillState(skill: OpenClawSkill) {
  if (!skill.enabled) return { label: '已停用', tone: 'neutral' as const }
  if (skill.blockedByAllowlist || skill.blockedByAgentFilter) return { label: '当前 Agent 不可用', tone: 'warning' as const }
  return skill.eligible ? { label: '可使用', tone: 'success' as const } : { label: '条件不足', tone: 'warning' as const }
}

export function AgentSkillsStatusPanel({ status, busy, canUpdate, onToggle, readOnly = false,
  title = '已发现 Skills', emptyTitle = '没有 Skills',
  emptyDescription = 'Gateway 尚未发现 Skill。安装后刷新此列表即可查看。' }: {
  readOnly?: boolean
  status: OpenClawSkillsStatus
  busy: string
  canUpdate: boolean
  onToggle: (key: string, enabled: boolean) => void
  title?: string
  emptyTitle?: string
  emptyDescription?: string
}) {
  const [detailKey, setDetailKey] = useState('')
  const detail = status.skills.find((skill) => skill.key === detailKey) ?? null
  return <>
    <section className="border-y border-separator" aria-label={title}>
      <div className="flex items-center gap-3 border-b border-separator py-3">
        <h3 className="type-page-title min-w-0 flex-1">{title}</h3>
        <span className="type-meta text-muted">{status.skills.length} 项</span>
      </div>
      {status.skills.length ? <div className="divide-y divide-separator">
        {status.skills.map((skill) => <div key={skill.key} className="flex min-w-0 flex-wrap items-center gap-3 py-4">
          <div className="min-w-0 flex-1">
            <OverflowValue value={skill.name} ariaLabel="Skill 名称" className="type-control" />
            <p className="type-meta mt-1 line-clamp-2 text-muted [overflow-wrap:anywhere]">{skill.description ?? '查看详情，了解此 Skill 的使用条件。'}</p>
          </div>
          <StatusIndicator {...skillState(skill)} />
          <Button size="sm" variant="ghost" aria-label={`查看 ${skill.name} 详情`} onPress={() => setDetailKey(skill.key)}>详情</Button>
          {!readOnly && <Button size="sm" variant="secondary" isDisabled={Boolean(busy) || !canUpdate} onPress={() => onToggle(skill.key, !skill.enabled)}>{skill.enabled ? '停用' : '启用'}</Button>}
        </div>)}
      </div> : <EmptyState title={emptyTitle} description={emptyDescription} />}
    </section>
    <Modal isOpen={Boolean(detail)} onOpenChange={(open) => !open && setDetailKey('')}>
      <Modal.Backdrop><Modal.Container size="lg"><Modal.Dialog>
        <Modal.Header><Modal.Heading>Skill 详情</Modal.Heading></Modal.Header>
        <Modal.Body>{detail && <div className="grid gap-4 [overflow-wrap:anywhere]">
          <h3 className="type-page-title">{detail.name}</h3>
          <p className="type-body text-muted">{detail.description ?? '此 Skill 没有提供说明。'}</p>
          <StatusIndicator {...skillState(detail)} />
          <p className="type-body">使用方式：回到对话，描述要完成的工作；Agent 会根据已启用 Skill 的说明选择是否使用。启用不代表会立即运行。</p>
          <dl className="type-body grid gap-2">
            <div><dt className="type-control">命令工具</dt><dd>{detail.missingBins.join('、') || '无缺失'}</dd></div>
            <div><dt className="type-control">任选其一的工具</dt><dd>{detail.missingAnyBins?.join(' / ') || '无缺失'}</dd></div>
            <div><dt className="type-control">环境变量名称</dt><dd>{detail.missingEnv.join('、') || '无缺失'}</dd></div>
            <div><dt className="type-control">配置条件</dt><dd>{detail.missingConfig?.join('、') || '无缺失'}</dd></div>
            <div><dt className="type-control">系统条件</dt><dd>{detail.missingOs?.join('、') || '无缺失'}</dd></div>
          </dl>
          {detail.blockedByAllowlist && <p className="type-body text-warning">此 Skill 被 Gateway 允许列表限制。</p>}
          {detail.blockedByAgentFilter && <p className="type-body text-warning">此 Skill 未分配给当前 Agent。</p>}
          {detail.installOptions.length > 0 && <p className="type-meta text-muted">Gateway 提供的安装条件：{detail.installOptions.join('、')}。请在 OpenClaw 中配置。</p>}
        </div>}</Modal.Body>
        <Modal.Footer><Button onPress={() => setDetailKey('')}>关闭</Button></Modal.Footer>
      </Modal.Dialog></Modal.Container></Modal.Backdrop>
    </Modal>
  </>
}
