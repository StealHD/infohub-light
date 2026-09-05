import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'

import {
  Button,
  Checkbox,
  Icons,
  Input,
  Label,
  LoadingState,
  Modal,
  RefreshButton,
  StableAsyncButton,
  StatusNotice,
  TextField,
  actionToast,
} from '../../design-system'
import type { OpenClawChatController, OpenClawSkillsStatus } from '../openclaw'
import { AdminAuthorizationDialog, AdminConnectedNotice } from './OpenClawAdminAuthorization'
import { useOpenClawAdminSession } from './useOpenClawAdminSession'
import { AgentSkillsStatusPanel } from './AgentSkillsStatusPanel'

type SkillConfirmation = { kind: 'toggle'; skillKey: string; enabled: boolean } | { kind: 'upload' }

function skillSlug(filename: string): string {
  return filename
    .replace(/\.zip$/iu, '')
    .toLowerCase()
    .replace(/[^a-z0-9-]+/gu, '-')
    .replace(/^-|-$/gu, '')
}

function SkillUploadDialog({
  open,
  busy,
  file,
  fileInput,
  slug,
  force,
  progress,
  onOpenChange,
  onFileChange,
  onSlugChange,
  onForceChange,
  onContinue,
}: {
  open: boolean
  busy: boolean
  file: File | null
  fileInput: RefObject<HTMLInputElement | null>
  slug: string
  force: boolean
  progress: number
  onOpenChange: (open: boolean) => void
  onFileChange: (file: File | null) => void
  onSlugChange: (slug: string) => void
  onForceChange: (force: boolean) => void
  onContinue: () => void
}) {
  return <Modal isOpen={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
    <Modal.Backdrop isDismissable={!busy} isKeyboardDismissDisabled={busy}>
      <Modal.Container size="lg"><Modal.Dialog>
        <Modal.Header><Modal.Heading>上传 ZIP Skill</Modal.Heading></Modal.Header>
        <Modal.Body><div className="grid gap-4">
          <p className="type-body text-muted">浏览器计算 SHA-256，以 512 KiB 顺序分块；commit 成功后才安装，客户端上限 20 MiB。</p>
          <label className="type-control grid min-h-28 cursor-pointer place-items-center rounded-[var(--inteliscope-radius-panel)] border border-dashed border-separator bg-default/50 p-4 text-center focus-within:outline-2 focus-within:outline-focus">
            <Icons.Archive size={24} className="text-accent" aria-hidden="true" />
            <span>{file ? file.name : '选择 ZIP Skill'}</span>
            <input ref={fileInput} type="file" accept=".zip,application/zip" className="sr-only" onChange={(event) => onFileChange(event.target.files?.[0] ?? null)} />
          </label>
          <TextField fullWidth value={slug} onChange={onSlugChange} isRequired>
            <Label>Skill 标识</Label><Input aria-label="Skill 标识" placeholder="my-skill" />
          </TextField>
          <Checkbox isSelected={force} onChange={onForceChange}><Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>强制替换同名 Skill（提交时再次确认）</Checkbox.Content></Checkbox>
          {busy && file && <p className="type-meta text-muted">已上传 {Math.round(progress / 1024)} / {Math.round(file.size / 1024)} KiB</p>}
        </div></Modal.Body>
        <Modal.Footer>
          <Button variant="ghost" isDisabled={busy} onPress={() => onOpenChange(false)}>取消</Button>
          <Button isDisabled={!file || !slug.trim()} onPress={onContinue}>继续确认</Button>
        </Modal.Footer>
      </Modal.Dialog></Modal.Container>
    </Modal.Backdrop>
  </Modal>
}

function SkillConfirmationDialog({
  confirming,
  force,
  file,
  busy,
  onClose,
  onExecute,
}: {
  confirming: SkillConfirmation | null
  force: boolean
  file: File | null
  busy: boolean
  onClose: () => void
  onExecute: () => void
}) {
  return <Modal isOpen={Boolean(confirming)} onOpenChange={(open) => !open && !busy && onClose()}>
    <Modal.Backdrop isDismissable={!busy} isKeyboardDismissDisabled={busy}><Modal.Container size="sm"><Modal.Dialog>
      <Modal.Header><Modal.Heading>确认 Gateway 写操作</Modal.Heading></Modal.Header>
      <Modal.Body><div className="grid gap-3">
        <p className="type-body text-muted">{confirming?.kind === 'upload'
          ? `${force ? '强制替换并' : ''}上传安装 ${file?.name ?? 'ZIP Skill'}？Gateway 将持久保存此更改。`
          : `${confirming?.enabled ? '启用' : '停用'} Skill “${confirming?.kind === 'toggle' ? confirming.skillKey : ''}”？`}</p>
        {confirming?.kind === 'upload' && force && <StatusNotice title="将覆盖同名 Skill" status="danger">此确认是强制替换的第二次确认，Inscope 无法回滚 Gateway 副作用。</StatusNotice>}
      </div></Modal.Body>
      <Modal.Footer><Button variant="ghost" isDisabled={busy} onPress={onClose}>返回</Button><StableAsyncButton pending={busy} pendingContent="提交中…" onPress={onExecute}>{confirming?.kind === 'upload' && force ? '确认覆盖并安装' : '确认执行'}</StableAsyncButton></Modal.Footer>
    </Modal.Dialog></Modal.Container></Modal.Backdrop>
  </Modal>
}

function useSkillsStatus(chat: OpenClawChatController) {
  const [status, setStatus] = useState<OpenClawSkillsStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const refresh = useCallback(() => setRevision((value) => value + 1), [])

  useEffect(() => chat.workspace.subscribe((event) => {
    if (event === 'skills.changed') refresh()
  }), [chat.workspace, refresh])

  useEffect(() => {
    if (chat.status !== 'connected' || !chat.workspace.capabilities()['skills.status']) return
    let active = true
    void Promise.resolve().then(() => {
      if (active) { setLoading(true); setError('') }
      return chat.workspace.skillsStatus()
    })
      .then((value) => { if (active) setStatus(value) })
      .catch(() => { if (active) setError('无法读取 Skills，请刷新重试；若仍失败，请检查 Gateway 的读取权限。') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [chat.status, chat.workspace, chat.sessionKey, revision])

  return { status, loading, error, setError, refresh }
}

export function AgentSkillsView({ chat }: { chat: OpenClawChatController }) {
  const authorization = useOpenClawAdminSession(chat.gatewayUrl)
  const fileInput = useRef<HTMLInputElement>(null)
  const { status, loading, error, setError, refresh } = useSkillsStatus(chat)
  const [file, setFile] = useState<File | null>(null)
  const [slug, setSlug] = useState('')
  const [force, setForce] = useState(false)
  const [progress, setProgress] = useState(0)
  const [busy, setBusy] = useState('')
  const [authorizationOpen, setAuthorizationOpen] = useState(false)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [confirming, setConfirming] = useState<SkillConfirmation | null>(null)

  function requestUpload() {
    if (!authorization.admin) {
      setAuthorizationOpen(true)
      return
    }
    setUploadOpen(true)
  }

  async function toggleSkill(skillKey: string, enabled: boolean) {
    if (!authorization.admin) { setAuthorizationOpen(true); return }
    setConfirming({ kind: 'toggle', skillKey, enabled })
  }

  async function executeToggle(skillKey: string, enabled: boolean) {
    if (!authorization.admin) return
    setBusy(skillKey)
    setError('')
    try {
      await authorization.admin.updateSkillEnabled(skillKey, enabled)
      actionToast.success(`Skill 已${enabled ? '启用' : '停用'}`)
      setConfirming(null)
      refresh()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy('')
    }
  }

  async function upload() {
    if (!authorization.admin || !file || !status) return
    setBusy('upload')
    setError('')
    setProgress(0)
    try {
      await authorization.admin.uploadAndInstallSkill({
        file,
        slug,
        force,
        gatewayLimit: status.maxUploadBytes,
        onProgress: setProgress,
      })
      actionToast.success('Skill 已上传并安装')
      setFile(null)
      setSlug('')
      setForce(false)
      setUploadOpen(false)
      setConfirming(null)
      if (fileInput.current) fileInput.current.value = ''
      refresh()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy('')
    }
  }

  function requestUploadConfirmation() {
    if (authorization.admin && file && status) setConfirming({ kind: 'upload' })
  }

  async function executeConfirmed() {
    if (!confirming) return
    if (confirming.kind === 'upload') await upload()
    else await executeToggle(confirming.skillKey, confirming.enabled)
  }

  const connected = chat.status === 'connected'
  const unsupported = connected && !chat.workspace.capabilities()['skills.status']

  return <div className="quiet-scroll-region h-full overflow-y-auto p-4 min-[768px]:p-6" data-agent-skills-view data-page-scroll-region>
    <div className="mx-auto grid max-w-5xl gap-4">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="type-section-title">Skills</h2>
          <p className="type-body mt-1 text-muted">查看 Agent 能做什么、哪些 Skill 可使用，以及还缺少什么条件。查看列表和详情无需管理授权。</p>
        </div>
        {authorization.admin
          ? status?.uploadedArchivesAllowed && <Button onPress={requestUpload}><Icons.Archive size={16} aria-hidden="true" />上传 ZIP</Button>
          : <Button isDisabled={!connected || unsupported} onPress={() => setAuthorizationOpen(true)}><Icons.LockKeyhole size={16} aria-hidden="true" />临时授权</Button>}
        <RefreshButton variant="ghost" label="刷新 Skills" isDisabled={!connected || unsupported} pending={loading} onPress={refresh} />
      </div>

      {authorization.admin && <AdminConnectedNotice onClose={authorization.close} />}
      {authorization.state === 'expired' && <StatusNotice title="临时管理连接已过期" status="warning">请在需要写操作时重新授权。</StatusNotice>}
      {!connected ? <StatusNotice title="连接 Gateway 后查看 Skills" status="default" />
        : unsupported ? <StatusNotice title="当前 Gateway 不支持 Skills 状态" status="warning" />
        : loading && !status ? <LoadingState label="正在读取 Skills" rows={3} />
          : status ? <AgentSkillsStatusPanel status={status} busy={busy} canUpdate={connected && (!authorization.admin || authorization.admin.capabilities()['skills.update'])} onToggle={(key, enabled) => void toggleSkill(key, enabled)} /> : null}
      {status && !status.uploadedArchivesAllowed && <p className="type-meta text-muted">当前 Gateway 未提供 ZIP 上传许可；已安装的 Skills 仍可查看和使用。</p>}
      {error && <StatusNotice title="Skills 操作失败" status="danger">{error}</StatusNotice>}
    </div>

    <SkillUploadDialog
      open={uploadOpen}
      busy={busy === 'upload'}
      file={file}
      fileInput={fileInput}
      slug={slug}
      force={force}
      progress={progress}
      onOpenChange={setUploadOpen}
      onFileChange={(next) => {
        setFile(next)
        if (next && !slug) setSlug(skillSlug(next.name))
      }}
      onSlugChange={setSlug}
      onForceChange={setForce}
      onContinue={requestUploadConfirmation}
    />

    <SkillConfirmationDialog
      confirming={confirming}
      force={force}
      file={file}
      busy={Boolean(busy)}
      onClose={() => setConfirming(null)}
      onExecute={() => void executeConfirmed()}
    />

    <AdminAuthorizationDialog
      open={authorizationOpen}
      onOpenChange={setAuthorizationOpen}
      connecting={authorization.connecting}
      error={authorization.error}
      onConnect={authorization.connect}
    />
  </div>
}
