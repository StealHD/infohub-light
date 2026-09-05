import { useEffect, useState } from 'react'

import {
  Button,
  EmptyState,
  FormSelect,
  Icons,
  LoadingState,
  Modal,
  StableAsyncButton,
  StatusNotice,
  actionToast,
} from '../../design-system'
import type {
  OpenClawArtifact,
  OpenClawArtifactDownload,
  OpenClawChatController,
  OpenClawWorkspaceSession,
} from '../openclaw'
import {
  artifactPreviewKind,
  artifactPreviewObjectUrl,
  artifactText,
  triggerArtifactDownload,
} from './agentArtifactDownload'

type Preview = {
  download: OpenClawArtifactDownload
  kind: 'image' | 'text'
  value: string
  revoke: () => void
}

function readableBytes(value?: number): string {
  if (value === undefined) return '大小未知'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KiB`
  return `${(value / 1024 / 1024).toFixed(1)} MiB`
}

export function AgentArtifactsView({
  chat,
  trustedSessions,
  variant = 'page',
}: {
  chat: OpenClawChatController
  trustedSessions: OpenClawWorkspaceSession[]
  variant?: 'page' | 'inspector'
}) {
  const [sessionKey, setSessionKey] = useState(chat.sessionKey ?? '')
  const [resource, setResource] = useState<{ scopeKey: string; items: OpenClawArtifact[] }>({ scopeKey: '', items: [] })
  const [loading, setLoading] = useState(false)
  const [busyId, setBusyId] = useState('')
  const [error, setError] = useState('')
  const [preview, setPreview] = useState<Preview | null>(null)
  const [revision, setRevision] = useState(0)

  useEffect(() => chat.workspace.subscribe((event) => {
    if (event === 'artifact' || event === 'task' || event === 'sessions.changed') setRevision((value) => value + 1)
  }), [chat.workspace])
  useEffect(() => () => preview?.revoke(), [preview])

  const effectiveSessionKey = trustedSessions.some((session) => session.key === sessionKey)
    ? sessionKey
    : trustedSessions[0]?.key ?? ''

  useEffect(() => {
    if (!effectiveSessionKey || chat.status !== 'connected' || !chat.workspace.capabilities()['artifacts.list']) return
    let active = true
    void Promise.resolve().then(() => {
      if (active) {
        setLoading(true)
        setError('')
        setResource({ scopeKey: effectiveSessionKey, items: [] })
      }
      return chat.workspace.listArtifacts({ sessionKey: effectiveSessionKey })
    })
      .then((value) => { if (active) setResource({ scopeKey: effectiveSessionKey, items: value }) })
      .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : String(reason)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [chat.status, chat.workspace, effectiveSessionKey, revision])

  function closePreview() {
    setPreview(null)
  }

  async function download(artifact: OpenClawArtifact, previewRequested: boolean) {
    if (!effectiveSessionKey || resource.scopeKey !== effectiveSessionKey || artifact.sessionKey !== effectiveSessionKey) {
      setError('Artifact 来源已变化，请等待当前 Session 列表刷新。')
      return
    }
    setBusyId(artifact.id)
    setError('')
    try {
      const result = await chat.workspace.downloadArtifact(artifact.id, { sessionKey: effectiveSessionKey })
      const kind = artifactPreviewKind(result)
      if (previewRequested && kind === 'text') {
        setPreview({ download: result, kind, value: artifactText(result), revoke: () => undefined })
      } else if (previewRequested && kind === 'image') {
        const object = artifactPreviewObjectUrl(result, chat.gatewayUrl)
        setPreview({ download: result, kind, value: object.url, revoke: object.revoke })
      } else {
        triggerArtifactDownload(result, chat.gatewayUrl)
        actionToast.success('产物下载已开始')
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusyId('')
    }
  }

  const artifacts = resource.scopeKey === effectiveSessionKey ? resource.items : []
  const connected = chat.status === 'connected'
  const unsupported = connected && !chat.workspace.capabilities()['artifacts.list']
  const compact = variant === 'inspector'

  return <div className="quiet-scroll-region h-full overflow-y-auto" data-agent-artifacts-view data-agent-resource-variant={variant}>
    <div className={compact ? '' : 'mx-auto max-w-5xl p-4 min-[768px]:p-6'}>
      <div className={`flex flex-wrap items-center gap-3 ${compact ? 'border-b border-separator px-4 py-4' : 'mb-4'}`}>
        <div className="min-w-0 flex-1">
          {!compact && <h2 className="type-page-title">Artifacts</h2>}
          <p className="type-body mt-1 text-muted">文件直接来自 Gateway，不进入 Inscope 存储。</p>
        </div>
        <FormSelect
          label="Artifact Session"
          value={effectiveSessionKey}
          options={trustedSessions.map((session) => ({ id: session.key, label: session.label }))}
          onChange={setSessionKey}
          isDisabled={loading}
          className="w-52"
        />
      </div>
      <div className={compact ? 'p-4' : ''}>
        {!connected ? <StatusNotice title="连接 Gateway 后查看 Artifacts" status="default">当前连接未就绪；已有可信内容不会被错误归入其他 Session。</StatusNotice>
          : unsupported ? <StatusNotice title="当前 Gateway 不支持 Artifacts" status="warning">缺少 artifacts.list；聊天仍可继续使用。</StatusNotice>
          : loading && !artifacts.length ? <LoadingState label="正在读取 Artifacts" rows={4} />
            : artifacts.length ? <div className="divide-y divide-separator border-y border-separator">
              {artifacts.map((artifact) => <div key={artifact.id} className="flex min-w-0 flex-wrap items-center gap-3 py-3">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-[var(--inteliscope-radius-control)] bg-default text-accent"><Icons.FileText size={18} /></span>
                <div className="min-w-0 flex-1">
                  <strong className="type-control block truncate">{artifact.title}</strong>
                  <span className="type-meta text-muted">{artifact.mimeType ?? artifact.type} · {readableBytes(artifact.sizeBytes)}</span>
                </div>
                {artifact.downloadMode === 'unsupported' ? <span className="type-meta text-muted">不可下载</span> : <div className="flex gap-1">
                  {artifactPreviewKind({ artifact }) !== 'download' && <StableAsyncButton size="sm" variant="ghost" pending={busyId === artifact.id} pendingContent="读取中…" onPress={() => void download(artifact, true)}>预览</StableAsyncButton>}
                  <Button size="sm" variant="secondary" isDisabled={Boolean(busyId)} onPress={() => void download(artifact, false)}><Icons.Download size={15} />下载</Button>
                </div>}
              </div>)}
            </div>
              : <EmptyState title="没有 Artifacts" description="当前 Session 尚未产生带可信 provenance 的文件或媒体。" />}
        {error && <div className="mt-3"><StatusNotice title="Artifact 操作失败" status="danger">{error}</StatusNotice></div>}
      </div>
    </div>

    <Modal isOpen={Boolean(preview)} onOpenChange={(open) => !open && closePreview()}>
      <Modal.Backdrop><Modal.Container size="lg"><Modal.Dialog>
        <Modal.Header><Modal.Heading>{preview?.download.artifact.title ?? 'Artifact 预览'}</Modal.Heading></Modal.Header>
        <Modal.Body>{preview?.kind === 'image'
          ? <img src={preview.value} alt={preview.download.artifact.title} className="mx-auto max-h-[65dvh] max-w-full object-contain" />
          : <pre className="type-body max-h-[65dvh] overflow-auto whitespace-pre-wrap rounded-[var(--inteliscope-radius-control)] bg-default p-4">{preview?.value}</pre>}
        </Modal.Body>
        <Modal.Footer><Button onPress={closePreview}>关闭</Button></Modal.Footer>
      </Modal.Dialog></Modal.Container></Modal.Backdrop>
    </Modal>
  </div>
}
