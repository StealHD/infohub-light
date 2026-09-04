import { Icons, StableAsyncButton } from '../../design-system'

export function WorkbenchPaginationFooter({ error, label, pending, onLoad }: {
  error: boolean
  label: string
  pending: boolean
  onLoad: () => Promise<unknown>
}) {
  return <div className="flex flex-col items-center gap-2 pt-1">
    {error && <p role="alert" className="type-meta text-danger">更多内容加载失败，已加载内容仍可继续查看。</p>}
    <StableAsyncButton size="sm" variant="secondary" pending={pending} pendingContent={<><Icons.LoaderCircle size={14} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />正在加载</>} onPress={onLoad}>{label}</StableAsyncButton>
  </div>
}
