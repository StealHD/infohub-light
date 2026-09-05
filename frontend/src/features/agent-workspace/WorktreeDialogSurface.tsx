import { useId } from 'react'
import { Button, Form, FormSelect, Input, Label, Modal, StableAsyncButton, StatusNotice, TextArea, TextField } from '../../design-system'
import type { OpenClawWorkspaceProject } from '../openclaw'
type DialogMode = 'editing' | 'creating' | 'retryable'

export function WorktreeDialogSurface({
  inline = false, open, mode, title, prompt, worktreeName, projects, projectId, branches, baseRef,
  loading, error, pendingAction, invalidName, ready,
  onOpenChange, onTitleChange, onPromptChange, onWorktreeNameChange,
  onProjectChange, onBaseRefChange, onSubmit,
}: {
  inline?: boolean
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
  const formId = useId()
  if (inline && !open) return null
  const retryable = mode === 'retryable'
  const close = () => { if (mode !== 'creating') onOpenChange(false) }
  const form = (
          <Form id={formId} className="grid gap-4" onSubmit={(event) => { event.preventDefault(); onSubmit() }}>
            <TextField fullWidth value={title} onChange={onTitleChange} isRequired isDisabled={retryable || mode === 'creating'}>
              <Label>任务标题</Label><Input aria-label="任务标题" />
            </TextField>
            <TextField fullWidth value={prompt} onChange={onPromptChange} isRequired isDisabled={mode === 'creating'}>
              <Label>完整提示词</Label><TextArea aria-label="完整提示词" className="min-h-32" />
            </TextField>
            <div className="grid gap-3 min-[640px]:grid-cols-2">
              <FormSelect label="Gateway 注册项目" value={projectId} options={projects.map((item) => ({ id: item.id, label: item.displayName }))} onChange={onProjectChange} isDisabled={loading || retryable || mode === 'creating'} isRequired />
              <FormSelect label="基础分支" value={baseRef} options={branches.map((name) => ({ id: name, label: name }))} onChange={onBaseRefChange} isDisabled={loading || retryable || mode === 'creating'} isRequired />
            </div>
            <TextField fullWidth value={worktreeName} onChange={onWorktreeNameChange} isInvalid={invalidName} isDisabled={retryable || mode === 'creating'}>
              <Label>Worktree 名称（可选）</Label><Input aria-label="Worktree 名称" placeholder="例如 agent-ui" />
              <p className="type-meta mt-1 text-muted">分支由 Gateway 创建为 openclaw/&lt;name&gt;；不接受主机路径。</p>
            </TextField>
            {retryable && <StatusNotice title="Session 与 Worktree 已创建，但任务未启动" status="warning">可在同一 Session 中重试；不会重复创建 Worktree。</StatusNotice>}
            {error && <StatusNotice title="Worktree 操作失败" status="danger">{error}</StatusNotice>}
          </Form>
  )
  const actions = <>
          <Button variant="ghost" isDisabled={mode === 'creating'} onPress={close}>取消</Button>
          <StableAsyncButton type="submit" form={formId} pending={mode === 'creating'} pendingContent={pendingAction === 'retry' ? '正在重试…' : '正在创建…'} isDisabled={retryable ? !prompt.trim() : !ready}>
            {retryable ? '在原 Session 重试' : '确认创建'}
          </StableAsyncButton>
  </>
  if (inline) return <div className="grid min-w-0 gap-4">
    <h3 className="type-control">在新 Worktree 中执行</h3>
    {form}
    <div className="flex flex-wrap justify-end gap-2">{actions}</div>
  </div>
  return <Modal isOpen={open} onOpenChange={(next) => next ? onOpenChange(true) : close()}>
    <Modal.Backdrop isDismissable={mode !== 'creating'} isKeyboardDismissDisabled={mode === 'creating'}>
      <Modal.Container size="lg"><Modal.Dialog>
        <Modal.Header><Modal.Heading>在新 Worktree 中执行</Modal.Heading></Modal.Header>
        <Modal.Body>{form}</Modal.Body>
        <Modal.Footer>{actions}</Modal.Footer>
      </Modal.Dialog></Modal.Container>
    </Modal.Backdrop>
  </Modal>
}
