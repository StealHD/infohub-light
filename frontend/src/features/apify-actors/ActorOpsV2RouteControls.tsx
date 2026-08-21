import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import { useAppContext } from '../../app/AppContext'
import { actionToast, Button, Input, Label, Modal, TextField } from '../../design-system'
import { type ActorOpsV2RouteView } from './ActorOpsV2ControlPlane'
import { actorOpsV2CandidateLabel, type ActorOpsV2CandidateView } from './actorOpsV2RouteModel'

export function ActorOpsV2RouteControls({ route }: { route: ActorOpsV2RouteView }) {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const [candidate, setCandidate] = useState<ActorOpsV2CandidateView | null>(null)
  const [verifyOpen, setVerifyOpen] = useState(false)
  const refresh = () => queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorRoutes(user.id) })
  const promote = useMutation({
    mutationFn: (target: ActorOpsV2CandidateView) => api.promoteActorOpsV2Candidate(route.route_id, target.candidate_id, {
      expected_route_generation: route.route_generation,
      expected_candidate_generation: target.generation,
      confirmation: '确认设为主用 Actor',
    }),
    onSuccess: () => {
      void refresh()
      setCandidate(null)
      actionToast.success('已切换当前主用', { description: '没有启动 Actor，也没有产生费用。' })
    },
    onError: (error) => {
      setCandidate(null)
      actionToast.danger(actionError(error, '未能切换主用，请刷新后重试。'))
    },
  })
  const verify = useMutation({
    mutationFn: () => api.verifyActorOpsV2Bindings(route.route_id, {
      expected_route_generation: route.route_generation,
      confirmation: '确认核验来源绑定',
    }),
    onSuccess: () => {
      void refresh()
      setVerifyOpen(false)
      actionToast.success('已完成来源核验', { description: '没有启动 Actor，也没有产生费用。' })
    },
    onError: (error) => {
      setVerifyOpen(false)
      actionToast.danger(actionError(error, '当前来源还不能安全启用，请稍后再核验。'))
    },
  })
  const pending = promote.isPending || verify.isPending
  if (!route.standby_candidates.length && !route.binding_summary.pending_count) return null
  return <div className="grid gap-2 border-t border-separator pt-3">
    {route.standby_candidates.map((item) => <Button
      key={item.candidate_id}
      size="sm"
      variant="secondary"
      isDisabled={pending}
      onPress={() => setCandidate(item)}
    >设为主用：{actorOpsV2CandidateLabel(item)}</Button>)}
    {route.binding_summary.pending_count > 0 && <Button
      size="sm"
      variant="secondary"
      isDisabled={pending}
      onPress={() => setVerifyOpen(true)}
    >核验待处理来源</Button>}
    <PromoteDialog target={candidate} pending={promote.isPending} onClose={() => setCandidate(null)} onConfirm={() => candidate && promote.mutate(candidate)} />
    <VerifyBindingsDialog open={verifyOpen} pending={verify.isPending} onClose={() => setVerifyOpen(false)} onConfirm={() => verify.mutate()} />
  </div>
}

function PromoteDialog({ target, pending, onClose, onConfirm }: {
  target: ActorOpsV2CandidateView | null
  pending: boolean
  onClose: () => void
  onConfirm: () => void
}) {
  return target ? <RouteControlDialog
    heading="设为当前主用"
    description={`将 ${actorOpsV2CandidateLabel(target)} 设为主用；原主用会成为同一备用位。不会启动 Actor，也不会产生费用。`}
    confirmation="确认设为主用 Actor"
    pending={pending}
    onClose={onClose}
    onConfirm={onConfirm}
  /> : null
}

function VerifyBindingsDialog({ open, pending, onClose, onConfirm }: {
  open: boolean
  pending: boolean
  onClose: () => void
  onConfirm: () => void
}) {
  return open ? <RouteControlDialog
    heading="核验待处理来源"
    description="系统只检查已保存的来源证据、目标指纹和当前主备顺序。证据不完整会保持待处理；不会抓取或启动 Actor。"
    confirmation="确认核验来源绑定"
    pending={pending}
    onClose={onClose}
    onConfirm={onConfirm}
  /> : null
}

function RouteControlDialog({ heading, description, confirmation, pending, onClose, onConfirm }: {
  heading: string
  description: string
  confirmation: '确认设为主用 Actor' | '确认核验来源绑定'
  pending: boolean
  onClose: () => void
  onConfirm: () => void
}) {
  const [value, setValue] = useState('')
  return <Modal isOpen onOpenChange={(open) => { if (!open && !pending) onClose() }}>
    <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">{heading}</Modal.Trigger>
    <Modal.Backdrop isDismissable={!pending} isKeyboardDismissDisabled={pending}><Modal.Container><Modal.Dialog>
      <Modal.Header><Modal.Heading>{heading}</Modal.Heading></Modal.Header>
      <Modal.Body><div className="grid gap-3" aria-busy={pending}>
        <p className="type-control">{description}</p>
        <TextField fullWidth value={value} onChange={setValue} isDisabled={pending}>
          <Label>确认短语</Label><Input placeholder={confirmation} />
        </TextField>
      </div></Modal.Body>
      <Modal.Footer><Button variant="ghost" isDisabled={pending} onPress={onClose}>取消</Button><Button isDisabled={pending || value !== confirmation} onPress={onConfirm}>{pending ? '处理中…' : '确认'}</Button></Modal.Footer>
    </Modal.Dialog></Modal.Container></Modal.Backdrop>
  </Modal>
}

function actionError(error: unknown, fallback: string) {
  if (!(error instanceof ApiError)) return fallback
  const labels: Record<string, string> = {
    actorops_v2_candidate_switch_conflict: '路线已更新，请刷新后再切换。',
    actorops_v2_binding_conflict: '路线已更新，请刷新后重新核验。',
    actorops_v2_binding_evidence_missing: '现有证据还不足以安全启用来源；没有执行抓取。',
    actorops_v2_unavailable: 'ActorOps v2 当前不可用。',
  }
  return labels[error.code] || fallback
}
