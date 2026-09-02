import type { StorageArchive } from '../../api/types'
import { ApiError } from '../../api/client'
import { Button, Modal, StableAsyncButton } from '../../design-system'
import { HeroNotice } from './HeroAdminControls'

export type ArchiveActionTarget = {
  archive: StorageArchive
  operation: 'restore' | 'delete_archive'
}

export function StorageArchivePreviewDialog({ target, pending, error, onClose, onConfirm }: {
  target: ArchiveActionTarget | null
  pending: boolean
  error: unknown
  onClose: () => void
  onConfirm: () => Promise<void>
}) {
  const errorMessage = error instanceof ApiError ? error.message : error instanceof Error && error.message ? error.message : '生成预演失败，请稍后重试。'
  return <Modal isOpen={Boolean(target)} onOpenChange={(open) => !open && onClose()}>
    <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开归档操作确认</Modal.Trigger>
    <Modal.Backdrop isDismissable={!pending} isKeyboardDismissDisabled={pending}>
      <Modal.Container size="sm"><Modal.Dialog>
        <Modal.Header><Modal.Heading>{target?.operation === 'delete_archive' ? '预演永久删除' : '预演恢复归档'}</Modal.Heading></Modal.Header>
        <Modal.Body><p className="type-body text-muted">{target?.operation === 'delete_archive'
          ? `将为 ${target.archive.id} 生成永久删除预演。执行前仍需输入精确确认文本，且服务端会重新核对归档状态。`
          : `将为 ${target?.archive.id ?? ''} 生成恢复预演；确认后不会立即修改数据。`}</p>{Boolean(error) && <HeroNotice title={errorMessage} />}</Modal.Body>
        <Modal.Footer><Button variant="ghost" isDisabled={pending} onPress={onClose}>取消</Button><StableAsyncButton variant={target?.operation === 'delete_archive' ? 'danger' : 'primary'} pending={pending} pendingContent="生成中…" onPress={onConfirm}>生成预演</StableAsyncButton></Modal.Footer>
      </Modal.Dialog></Modal.Container>
    </Modal.Backdrop>
  </Modal>
}
