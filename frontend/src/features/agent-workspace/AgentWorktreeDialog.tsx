import { useEffect, useMemo, useState } from 'react'

import { actionToast } from '../../design-system'
import { WorktreeDialogSurface } from './WorktreeDialogSurface'
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


export function AgentWorktreeDialog({
  open,
  onOpenChange,
  workspace,
  onCreated,
  initialPrompt = '',
  inline = false,
  onPendingChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  workspace: OpenClawWorkspaceController
  onCreated: (result?: OpenClawWorktreeResult) => void
  initialPrompt?: string
  inline?: boolean
  onPendingChange?: (pending: boolean) => void
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
    onPendingChange?.(true)
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
      onCreated(result)
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
    } finally { onPendingChange?.(false) }
  }

  async function retry() {
    if (!created || !retryKey || !prompt.trim()) return
    setPendingAction('retry')
    onPendingChange?.(true)
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
    } finally { onPendingChange?.(false) }
  }

  const invalidName = Boolean(worktreeName.trim() && !/^[a-z0-9][a-z0-9-]{0,47}$/u.test(worktreeName.trim()))
  const ready = Boolean(title.trim() && prompt.trim() && project && baseRef && createKey && !invalidName && !loading)
  return <WorktreeDialogSurface
    inline={inline} open={open} mode={mode} title={title} prompt={prompt} worktreeName={worktreeName}
    projects={projects} projectId={projectId} branches={branches} baseRef={baseRef}
    loading={loading} error={error} pendingAction={pendingAction} invalidName={invalidName} ready={ready}
    onOpenChange={onOpenChange} onTitleChange={setTitle} onPromptChange={setPrompt}
    onWorktreeNameChange={setWorktreeName} onProjectChange={setProjectId} onBaseRefChange={setBaseRef}
    onSubmit={() => void (mode === 'retryable' ? retry() : create())}
  />
}
