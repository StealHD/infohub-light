import type { ApifyActorSlotName } from '../../api/types'
import { SettingsDisclosure } from '../../components/settings'
import { Button, Modal } from '../../design-system'
import { HeroNotice, HeroSelect } from '../admin-heroui/HeroAdminControls'
import { formatActorUsd } from './apifyActorModel'
import type { HumanActorError } from './actorOpsPresentation'
import type {
  ActorOpsActivationConfirmationView,
  ActorOpsBatchConfirmationView,
  ActorOpsRollbackConfirmationView,
  ActorOpsSourceCanaryConfirmationView,
} from './actorOpsWorkflowDialogModel'

export function HumanActorErrorNotice({ error }: { error: HumanActorError }) {
  return (
    <HeroNotice title={error.reason} status="danger" role="alert">
      <p><strong>影响：</strong>{error.impact}</p>
      <p className="mt-1"><strong>下一步：</strong>{error.next}</p>
      {error.diagnostic && (
        <SettingsDisclosure title="诊断信息" description="仅包含可安全复制的错误代码。">
          <code className="break-all type-meta">{error.diagnostic}</code>
        </SettingsDisclosure>
      )}
    </HeroNotice>
  )
}

export function ActorOpsBatchConfirmationDialog({
  view,
  error,
  pending,
  onCancel,
  onConfirm,
}: {
  view: ActorOpsBatchConfirmationView | null
  error: HumanActorError | null
  pending: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  return (
    <Modal
      isOpen={Boolean(view)}
      onOpenChange={(open) => { if (!open && !pending) onCancel() }}
    >
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">
        打开付费验证确认
      </Modal.Trigger>
      <Modal.Backdrop
        isDismissable={!pending}
        isKeyboardDismissDisabled={pending}
      >
        <Modal.Container>
          <Modal.Dialog>
            <Modal.Header>
              <Modal.Heading>
                {view?.compatibility ? '验证单路兼容 Actor' : '验证所选 Actor'}
              </Modal.Heading>
            </Modal.Header>
            <Modal.Body>
              <div className="grid gap-3" aria-busy={pending}>
                <HeroNotice
                  title="严格串行，并受总费用上限保护"
                  status="warning"
                  role="status"
                >
                  这是确认 1/2。
                  {view?.compatibility
                    ? '兼容 Canary 必须对固定公开参考账号返回真实非空内容；空结果不会通过。'
                    : '验证通过并确认生效前，当前配置不会改变；未启动或不再需要的项费用为 $0。'}
                </HeroNotice>
                {view && (
                  <>
                    <dl className="grid gap-2 rounded-control border border-separator bg-surface-secondary p-3 type-meta">
                      <div>
                        <dt className="text-muted">抓取类型</dt>
                        <dd className="mt-1">{view.routeLabel}</dd>
                      </div>
                      <div>
                        <dt className="text-muted">本批总费用上限</dt>
                        <dd className="mt-1 tabular-nums">
                          {formatActorUsd(view.maxTotalChargeUsd, true)}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-muted">来源预验证</dt>
                        <dd className="mt-1">
                          {view.sourceCount} 个已启用来源 · 最多 {view.sourceValidationCount} 次缺失验证
                        </dd>
                      </div>
                      <div>
                        <dt className="text-muted">验证边界</dt>
                        <dd className="mt-1">
                          只验证你选择的 Actor；系统不会静默换人或超出总费用上限。
                        </dd>
                      </div>
                    </dl>
                    <ol className="grid gap-2">
                      {view.items.map((item) => (
                        <li
                          key={item.key}
                          className="rounded-control border border-separator bg-surface-secondary p-3 type-meta"
                        >
                          <p className="type-control">{item.actorLabel}</p>
                          <p className="mt-1 text-muted">
                            发布者 {item.publisher} · 单次封顶{' '}
                            {formatActorUsd(item.authorizedCapUsd, true)}
                            {item.alreadyValidated ? ' · 已有成功证据可复用' : ''}
                          </p>
                          {item.validationProfile && (
                            <p className="mt-1 text-muted">
                              等待 {item.validationProfile.timeoutSeconds} 秒 · 样本{' '}
                              {item.validationProfile.sampleItems} 条 · 参数费用上限{' '}
                              {formatActorUsd(item.validationProfile.maxChargeUsd, true)}
                            </p>
                          )}
                        </li>
                      ))}
                    </ol>
                  </>
                )}
                {error && <HumanActorErrorNotice error={error} />}
              </div>
            </Modal.Body>
            <Modal.Footer>
              <Button variant="ghost" isDisabled={pending} onPress={onCancel}>取消</Button>
              <Button isDisabled={!view?.ready || pending} onPress={onConfirm}>
                {pending
                  ? '提交中…'
                  : `确认验证（最高 ${formatActorUsd(view?.maxTotalChargeUsd ?? null, true)}）`}
              </Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  )
}

export function ActorOpsActivationConfirmationDialog({
  view,
  error,
  pending,
  onCancel,
  onConfirm,
}: {
  view: ActorOpsActivationConfirmationView | null
  error: HumanActorError | null
  pending: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const heading = view?.goal === 'compatibility_single'
    ? '确认启用 1/3 兼容池'
    : view?.goal === 'complete_third'
      ? '确认补齐备用 2'
    : view?.goal === 'upgrade_legacy'
      ? '确认切换到新版主备'
      : view?.goal === 'add_slot'
        ? '确认添加 Actor'
        : view?.goal === 'replace_slot'
          ? '确认替换 Actor'
        : view?.minimumActors === 1
          ? '确认启用单路 fallback'
          : '确认启用 Actor 主备'
  const impact = view?.goal === 'compatibility_single'
    ? '启用后 X 功能可用，但只有 1 路 Actor，没有主备冗余；失败时可能暂时无法抓取。'
    : view?.minimumActors === 1
      ? '启用后 YouTube 仍优先使用公开 Atom；这个 Actor 只作为故障 fallback，不会自动补更多 Actor。'
      : '槽位和已预验证来源会在同一事务中生效；运行中的任务继续使用原配置。'
  const after = view?.goal === 'compatibility_single'
    ? '单路兼容 1/3；后续可不停机补主备'
    : view?.goal === 'complete_third'
      ? '补齐为 3/3，原主用与备用 1 不变'
    : view?.goal === 'upgrade_legacy'
        ? '零中断切换为新版 3/3 主备'
        : view?.goal === 'add_slot'
          ? '将新 Actor 原子加入指定空槽；现有主备保持运行'
          : view?.goal === 'replace_slot'
            ? '将指定槽原子替换；旧 Revision 保留为历史'
        : view?.minimumActors === 1
          ? '启用 1/3 单路 fallback；原生 Atom 继续优先'
          : '启用标准 2/3 主备；第三路可后续主动补充'

  return (
    <Modal
      isOpen={Boolean(view)}
      onOpenChange={(open) => { if (!open && !pending) onCancel() }}
    >
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">
        打开主备生效确认
      </Modal.Trigger>
      <Modal.Backdrop
        isDismissable={!pending}
        isKeyboardDismissDisabled={pending}
      >
        <Modal.Container>
          <Modal.Dialog>
            <Modal.Header><Modal.Heading>{heading}</Modal.Heading></Modal.Header>
            <Modal.Body>
              <div className="grid gap-3" aria-busy={pending}>
                <HeroNotice title="这是确认 2/2" status="warning" role="status">
                  {impact}
                </HeroNotice>
                {view && (
                  <dl className="grid gap-2 rounded-control border border-separator bg-surface-secondary p-3 type-meta">
                    <div>
                      <dt className="text-muted">当前方案</dt>
                      <dd className="mt-1">{view.currentSlotCount}/3 路</dd>
                    </div>
                    <div>
                      <dt className="text-muted">生效后</dt>
                      <dd className="mt-1">{after}</dd>
                    </div>
                    <div>
                      <dt className="text-muted">停机影响</dt>
                      <dd className="mt-1">无停机；只有下一任务读取新配置。</dd>
                    </div>
                  </dl>
                )}
                {error && <HumanActorErrorNotice error={error} />}
              </div>
            </Modal.Body>
            <Modal.Footer>
              <Button variant="ghost" isDisabled={pending} onPress={onCancel}>取消</Button>
              <Button isDisabled={!view || pending} onPress={onConfirm}>
                {pending ? '生效中…' : '确认生效'}
              </Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  )
}

export function ActorOpsSourceCanaryConfirmationDialog({
  view,
  error,
  pending,
  onCancel,
  onConfirm,
}: {
  view: ActorOpsSourceCanaryConfirmationView | null
  error: string
  pending: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  return (
    <Modal
      isOpen={Boolean(view)}
      onOpenChange={(open) => { if (!open && !pending) onCancel() }}
    >
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">
        打开来源付费验证确认
      </Modal.Trigger>
      <Modal.Backdrop
        isDismissable={!pending}
        isKeyboardDismissDisabled={pending}
      >
        <Modal.Container>
          <Modal.Dialog>
            <Modal.Header><Modal.Heading>确认来源付费验证</Modal.Heading></Modal.Header>
            <Modal.Body>
              <div className="grid gap-3">
                <HeroNotice title="只验证下一缺失槽位" status="warning" role="status">
                  精确 Build 串行执行一次；不会显示真实目标，也不会自动重试。
                </HeroNotice>
                {view && (
                  <dl className="grid gap-2 rounded-control border border-separator bg-surface-secondary p-3 type-meta">
                    <div>
                      <dt className="text-muted">Actor / Build</dt>
                      <dd className="mt-1">{view.actorLabel} · {view.buildLabel}</dd>
                    </div>
                    <div>
                      <dt className="text-muted">本次封顶</dt>
                      <dd className="mt-1">{formatActorUsd(view.capUsd, true)}</dd>
                    </div>
                  </dl>
                )}
                {error && <HeroNotice title={error} status="danger" />}
              </div>
            </Modal.Body>
            <Modal.Footer>
              <Button variant="ghost" isDisabled={pending} onPress={onCancel}>取消</Button>
              <Button isDisabled={!view || pending} onPress={onConfirm}>
                {pending ? '提交中…' : '确认付费试跑'}
              </Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  )
}

export function ActorOpsSourceActivationConfirmationDialog({
  open,
  pending,
  onCancel,
  onConfirm,
}: {
  open: boolean
  pending: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  return (
    <Modal
      isOpen={open}
      onOpenChange={(nextOpen) => { if (!nextOpen && !pending) onCancel() }}
    >
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">
        打开来源首次启用确认
      </Modal.Trigger>
      <Modal.Backdrop
        isDismissable={!pending}
        isKeyboardDismissDisabled={pending}
      >
        <Modal.Container>
          <Modal.Dialog>
            <Modal.Header><Modal.Heading>确认首次启用来源</Modal.Heading></Modal.Header>
            <Modal.Body>
              <HeroNotice title="所有当前主备均已验证" status="success" role="status">
                确认后该来源开始使用当前 Actor 主备；后续槽位变化只复验变化部分。
              </HeroNotice>
            </Modal.Body>
            <Modal.Footer>
              <Button variant="ghost" isDisabled={pending} onPress={onCancel}>取消</Button>
              <Button isDisabled={pending} onPress={onConfirm}>
                {pending ? '启用中…' : '确认首次启用'}
              </Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  )
}

const rollbackSlots: Array<{ id: ApifyActorSlotName; label: string }> = [
  { id: 'primary', label: '主用' },
  { id: 'backup_1', label: '备用 1' },
  { id: 'backup_2', label: '备用 2' },
]

export function ActorOpsRollbackConfirmationDialog({
  view,
  pending,
  onSlotChange,
  onCancel,
  onConfirm,
}: {
  view: ActorOpsRollbackConfirmationView | null
  pending: boolean
  onSlotChange: (slot: ApifyActorSlotName) => void
  onCancel: () => void
  onConfirm: () => void
}) {
  return (
    <Modal
      isOpen={Boolean(view)}
      onOpenChange={(open) => { if (!open && !pending) onCancel() }}
    >
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">
        打开 Revision 回滚确认
      </Modal.Trigger>
      <Modal.Backdrop
        isDismissable={!pending}
        isKeyboardDismissDisabled={pending}
      >
        <Modal.Container>
          <Modal.Dialog>
            <Modal.Header><Modal.Heading>回滚不可变 Revision</Modal.Heading></Modal.Header>
            <Modal.Body>
              <div className="grid gap-4">
                <HeroNotice title="回滚会创建新的 Route generation" status="warning" role="status">
                  运行中的旧任务可结束，但过期结果不能写入新缓存。
                </HeroNotice>
                <p className="type-control break-all">{view?.revisionLabel}</p>
                {view && (
                  <HeroSelect
                    label="回滚到槽位"
                    value={view.slot}
                    onChange={(value) => onSlotChange(value as ApifyActorSlotName)}
                    isDisabled={pending}
                    options={rollbackSlots}
                  />
                )}
              </div>
            </Modal.Body>
            <Modal.Footer>
              <Button variant="ghost" isDisabled={pending} onPress={onCancel}>取消</Button>
              <Button isDisabled={!view?.canConfirm || pending} onPress={onConfirm}>
                {pending ? '回滚中…' : '确认回滚'}
              </Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  )
}
