import type { AppOutletContext } from '../../app/AppContext'
import { Icons, Link, RefreshButton, Tooltip, TooltipTriggerButton, topAnchoredTooltipProps } from '../../design-system'
import type { CardTranslationProps } from './CardTranslation'
import { useCardTranslation } from './useCardTranslation'

export default function CardTranslationContent({ card, readonly, onExpand, children, context }: CardTranslationProps & { context: AppOutletContext }) {
  const translation = useCardTranslation(context, card.id, onExpand)
  const content = card.item.presentation?.content
  const hasText = Boolean(content?.body_text?.trim() || content?.excerpt?.trim() || card.item.body_available)
  const unavailable = translation.code === 'translation_no_text'
  const label = !hasText || unavailable ? '暂无可翻译正文' : readonly ? '只读账户不可发起翻译' : '翻译正文'
  const panelId = `translation-${card.id}`
  const button = <Tooltip delay={500}>
    <TooltipTriggerButton
      className={`size-8 shrink-0 rounded-lg text-muted hover:bg-default hover:text-foreground pointer-coarse:size-11 ${translation.open ? 'bg-default text-accent' : ''}`}
      aria-label={label}
      aria-controls={panelId}
      aria-expanded={translation.open}
      disabled={readonly || !hasText || unavailable}
      pending={translation.pending}
      onClick={() => translation.activate()}
    ><Icons.Languages size={15} aria-hidden="true" /></TooltipTriggerButton>
    <Tooltip.Content {...topAnchoredTooltipProps}>{label}</Tooltip.Content>
  </Tooltip>
  const body = translation.open && <section id={panelId} data-card-actions aria-label="中文翻译" className="mx-4 my-3 min-w-0 border-t border-separator pt-3">
    <p className="type-meta mb-2 text-muted">中文翻译</p>
    {translation.pending && <p role="status" className="type-meta text-muted">
      {translation.data?.status === 'running' ? '正在翻译…' : '等待翻译…'}
    </p>}
    {translation.data?.translation && <p className="type-prose whitespace-pre-wrap break-words text-foreground">{translation.data.translation}</p>}
    {translation.data?.scope === 'excerpt' && <p className="type-meta mt-2 text-muted">仅翻译已抓取摘录</p>}
    {translation.data?.scope === 'body' && translation.data.source_truncated && <p className="type-meta mt-2 text-muted">仅翻译已抓取正文片段</p>}
    {translation.message && <div role="alert" className="flex min-w-0 flex-wrap items-center gap-2">
      <span className="type-meta min-w-0 break-words text-danger">{translation.message}</span>
      {!unavailable && <RefreshButton size="sm" variant="ghost" label="重试翻译" pending={translation.pending} onPress={() => translation.activate(true)} />}
      {translation.code === 'translation_model_unavailable' && ['owner', 'admin'].includes(context.user.role) && <Link href="/settings/ai">前往 AI 设置</Link>}
    </div>}
  </section>
  return children({ button, body })
}
