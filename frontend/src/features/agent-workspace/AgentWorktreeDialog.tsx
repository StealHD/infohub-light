import { useEffect, useMemo, useState } from 'react'

import {
  Button,
  Form,
  FormSelect,
  Input,
  Label,
  Modal,
  StableAsyncButton,
  StatusNotice,
  TextArea,
  TextField,
  actionToast,
} from '../../design-system'
import type {
  OpenClawWorkspaceController,
  OpenClawWorkspaceProject,
  OpenClawWorktreeResult,
} from '../openclaw'
import { OpenClawWorkspaceError } from '../openclaw'

type DialogMode = 'editing' | 'creating' | 'retryable'

function publicError(reason: unknown): string {
  return reason instanceof OpenClawWorkspaceError ? reason.message : 'OpenClaw 暂时无法完成此操作，请重试。'
}

function WorktreeDialogSurface({
  open, mode, title, prompt, worktreeName, projects, projectId, branches, baseRef,
  loading, error, pendingAction, invalidName, ready,
  onOpenChange, onTitleChange, onPromptChange, onWorktreeNameChange,
  onProjectChange, onBaseRefChange, onSubmit,
}: {
  open: boolean
  mode: DialogMode
  title: string
  prompt: string
  worktreeName: string
  projects: OpenClawWorkspaceProject[]
  projectId: string
  branches: string[]
  baseRef: string
  loading: boolean
  error: string
  pendingAction: 'create' | 'retry'
  invalidName: boolean
  ready: boolean
  onOpenChange: (open: boolean) => void
  onTitleChange: (value: string) => void
  onPromptChange: (value: string) => void
  onWorktreeNameChange: (value: string) => void
  onProjectChange: (value: string) => void
  onBaseRefChange: (value: string) => void
  onSubmit: () => void
}) {
  const retryable = mode === 'retryable'
  const close = () => { if (mode !== 'creating') onOpenChange(false) }
  return <Modal isOpen={open} onOpenChange={(next) => next ? onOpenChange(true) : close()}>
    <Modal.Backdrop isDismissable={mode !== 'creating'} isKeyboardDismissDisabled={mode === 'creating'}>
      <Modal.Container size="lg"><Modal.Dialog>
        <Modal.Header><Modal.Heading>在新 Worktree 中执行</Modal.Heading></Modal.Header>
        <Modal.Body>
          <Form id="agent-worktree-form" className="grid gap-4" onSubmit={(event) => { event.preventDefault(); onSubmit() }}>
            <TextField fullWidth value={title} onChange={onTitleChange} isRequired isDisabled={retryable}>
              <Label>任务标题</Label><Input aria-label="任务标题" />
            </TextField>
            <TextField fullWidth value={prompt} onChange={onPromptChange} isRequired>
              <Label>完整提示词</Label><TextArea aria-label="完整提示词" className="min-h-32" />
            </TextField>
            <div className="grid gap-3 min-[640px]:grid-cols-2">
              <FormSelect label="Gateway 注册项目" value={projectId} options={projects.map((item) => ({ id: item.id, label: item.displayName }))} onChange={onProjectChange} isDisabled={loading || retryable} isRequired />
              <FormSelect label="基础分支" value={baseRef} options={branches.map((name) => ({ id: name, label: name }))} onChange={onBaseRefChange} isDisabled={loading || retryable} isRequired />
            </div>
            <TextField fullWidth value={worktreeName} onChange={onWorktreeNameChange} isInvalid={invalidName} isDisabled={retryable}>
              <Label>Worktree 名称（可选）</Label><Input aria-label="Worktree 名称" placeholder="例如 agent-ui" />
              <p className="type-meta mt-1 text-muted">分支由 Gateway 创建为 openclaw/&lt;name&gt;；不接受主机路径。</p>
            </TextField>
            {retryable && <StatusNotice title="Session 与 Worktree 已创建，但任务未启动" status="warning">可在同一 Session 中重试；不会重复创建 Worktree。</StatusNotice>}
            {error && <StatusNotice title="Worktree 操作失败" status="danger">{error}</StatusNotice>}
          </Form>
        </Modal.Body>
        <Modal.Footer>
          <Button variant="ghost" isDisabled={mode === 'creating'} onPress={close}>取消</Button>
          <StableAsyncButton type="submit" form="agent-worktree-form" pending={mode === 'creating'} pendingContent={pendingAction === 'retry' ? '正在重试…' : '正在创建…'} isDisabled={retryable ? !prompt.trim() : !ready}>
            {retryable ? '在原 Session 重试' : '确认创建'}
          </StableAsyncButton>
        </Modal.Footer>
      </Modal.Dialog></Modal.Container>
    </Modal.Backdrop>
  </Modal>
}

export function AgentWorktreeDialog({
  open,
  onOpenChange,
  workspace,
  onCreated,
  initialPrompt = '',
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  workspace: OpenClawWorkspaceController
  onCreated: () => void
  initialPrompt?: string
}) {
  const [title, setTitle] = useState('')
  const [prompt, setPrompt] = useState('')
  const [worktreeName, setWorktreeName] = useState('')
  const [projects, setProjects] = useState<OpenClawWorkspaceProject[]>([])
  const [projectId, setProjectId] = useState('')
  const [branches, setBranches] = useState<string[]>([])
  const [baseRef, setBaseRef] = useState('')
  const [loading, setLoading] = useState(false)
  const [mode, setMode] = useState<DialogMode>('editing')
  const [error, setError] = useState('')
  const [created, setCreated] = useState<OpenClawWorktreeResult | null>(null)
  const [createKey, setCreateKey] = useState('')
  const [retryKey, setRetryKey] = useState('')
  const [pendingAction, setPendingAction] = useState<'create' | 'retry'>('create')
  const project = useMemo(() => projects.find((candidate) => candidate.id === projectId), [projectId, projects])

  useEffect(() => {
    if (!open) return
    let active = true
    void Promise.resolve().then(() => {
      if (!active) return
      setTitle(''); setPrompt(initialPrompt); setWorktreeName(''); setProjects([]); setProjectId(''); setBranches([]); setBaseRef('')
      setMode('editing'); setError(''); setCreated(null); setCreateKey(crypto.randomUUID()); setRetryKey(''); setPendingAction('create')
    })
    return () => { active = false }
  }, [open, initialPrompt])

  useEffect(() => {
    if (!open) return
    let active = true
    void Promise.resolve().then(() => {
      if (active) setLoading(true)
      return workspace.listProjects()
    })
      .then((next) => {
        if (!active) return
        setProjects(next)
        setProjectId(next[0]?.id ?? '')
      })
      .catch((reason) => { if (active) setError(publicError(reason)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [open, workspace])

  useEffect(() => {
    if (!open || !project) return
    let active = true
    void Promise.resolve().then(() => {
      if (active) { setLoading(true); setBranches([]); setBaseRef('') }
      return workspace.listBranches(project)
    })
      .then((result) => {
        if (!active) return
        const names = result.branches.map((branch) => branch.name)
        setBranches(names)
        setBaseRef(result.defaultBranch && names.includes(result.defaultBranch)
          ? result.defaultBranch
          : result.headBranch && names.includes(result.headBranch)
            ? result.headBranch
            : names[0] ?? '')
      })
      .catch((reason) => { if (active) setError(publicError(reason)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [open, project, workspace])

  async function create() {
    if (!project || !createKey) return
    setPendingAction('create')
    setMode('creating')
    setError('')
    try {
      const result = await workspace.createWorktreeSession({
        title,
        prompt,
        projectId: project.id,
        projectRepoRoot: project.repoRoot,
        baseRef,
        idempotencyKey: createKey,
        ...(worktreeName.trim() ? { worktreeName } : {}),
      })
      onCreated()
      if (!result.runStarted) {
        setCreated(result)
        setRetryKey(crypto.randomUUID())
        setMode('retryable')
        return
      }
      actionToast.success('Worktree 任务已创建', { description: result.worktree?.branch ?? '任务已进入运行队列' })
      onOpenChange(false)
    } catch (reason) {
      setError(publicError(reason))
      setMode('editing')
    }
  }

  async function retry() {
    if (!created || !retryKey || !prompt.trim()) return
    setPendingAction('retry')
    setMode('creating')
    setError('')
    try {
      await workspace.retryWorktreeRun(created.sessionKey, prompt, retryKey)
      actionToast.success('已在原 Session 中启动任务')
      onCreated()
      onOpenChange(false)
    } catch (reason) {
      setError(publicError(reason))
      setMode('retryable')
    }
  }

  const invalidName = Boolean(worktreeName.trim() && !/^[a-z0-9][a-z0-9-]{0,47}$/u.test(worktreeName.trim()))
  const ready = Boolean(title.trim() && prompt.trim() && project && baseRef && createKey && !invalidName && !loading)
  return <WorktreeDialogSurface
    open={open} mode={mode} title={title} prompt={prompt} worktreeName={worktreeName}
    projects={projects} projectId={projectId} branches={branches} baseRef={baseRef}
    loading={loading} error={error} pendingAction={pendingAction} invalidName={invalidName} ready={ready}
    onOpenChange={onOpenChange} onTitleChange={setTitle} onPromptChange={setPrompt}
    onWorktreeNameChange={setWorktreeName} onProjectChange={setProjectId} onBaseRefChange={setBaseRef}
    onSubmit={() => void (mode === 'retryable' ? retry() : create())}
  />
}
