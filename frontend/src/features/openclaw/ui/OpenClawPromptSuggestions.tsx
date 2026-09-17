import { lazy, Suspense } from 'react'
import { Button, Icons, PromptSuggestion, loadSpatialSuggestions } from '../../../design-system'
import type { OpenClawComposerPort } from './openclawComposerPort'

const SpatialSuggestions = lazy(loadSpatialSuggestions)

function suggestions(composer: OpenClawComposerPort) {
  if (composer.snapshot) return [
    { title: '梳理专题脉络', category: '时间线', description: '还原变化顺序，标出待核验的节点。',
      prompt: '请基于当前专题快照按时间梳理主要变化，区分已确认事实与推断，指出证据不足或需要继续核验的节点。', icon: Icons.FileText },
    { title: '对比关键分歧', category: '交叉核验', description: '比较相同信号与相互矛盾的说法。',
      prompt: '请比较当前专题快照中不同来源的关键说法，列出一致之处、分歧及各自依据，不要把未经核验的内容写成事实。', icon: Icons.GitCompareArrows },
    { title: '形成跟进清单', category: '下一步', description: '按优先级整理值得继续追踪的问题。',
      prompt: '请从当前专题快照提炼值得继续追踪的问题，按重要性排序，说明每项的现有证据、信息缺口和建议的下一步。', icon: Icons.ListChecks },
  ]
  if (composer.itemCount) return [
    { title: '综合已选内容', category: '内容综述', description: '归纳共同结论与重要差异。',
      prompt: '请综合我已选的内容，提炼共同结论和重要差异，逐项说明依据，并标明仍有争议或证据不足的地方。', icon: Icons.FileText },
    { title: '交叉核验信号', category: '信号对比', description: '识别重复出现和相互冲突的线索。',
      prompt: '请对比我已选内容中的关键信号，找出重复出现的趋势与相互冲突的说法，分别说明依据和可信度限制。', icon: Icons.GitCompareArrows },
    { title: '制定跟进问题', category: '后续行动', description: '把信息缺口转成可继续调查的问题。',
      prompt: '请根据我已选的内容整理后续调查清单：每项写明要验证的问题、已有依据、缺少的信息和优先级，不要直接修改订阅或配置。', icon: Icons.ListChecks },
  ]
  return [
    { title: '排查采集链路', category: '运行诊断', description: '串联失败任务、来源健康与记录线索。',
      prompt: '请检查我最近失败的采集任务和异常来源，结合任务诊断、来源健康与可用的操作记录，按影响范围列出可能原因、证据和下一步；证据不足时明确说明，先不要修改配置或重试。', icon: Icons.Stethoscope },
    { title: '研判近期信号', category: '信息分析', description: '从近期信息流提炼重要变化与依据。',
      prompt: '请分析我最近的信息流，按主题归纳重要变化，区分事实与推断，列出最值得关注的三个信号及依据，并指出需要进一步核验的问题。', icon: Icons.GitCompareArrows },
    { title: '优化订阅组合', category: '订阅策略', description: '找出重复、停滞和持续异常的来源。',
      prompt: '请检查我当前的订阅和来源健康，找出重复、长期无更新或持续失败的订阅，按保留、调整、排查建议分组并说明依据；先给方案，不要直接修改订阅。', icon: Icons.Rss },
  ]
}

export function OpenClawPromptSuggestions({ composer, variant }: {
  composer: OpenClawComposerPort
  variant: 'compact' | 'workspace'
}) {
  const workspace = variant === 'workspace'

  function fillSuggestion(question: string) {
    composer.setQuestion(question)
    window.requestAnimationFrame(() => {
      document.querySelector<HTMLElement>('[aria-label="发送给 OpenClaw 的问题"]')?.focus()
    })
  }

  return <PromptSuggestion className={`${workspace ? 'max-w-[var(--inteliscope-width-agent-conversation)] py-6 min-[768px]:py-12' : 'max-w-sm py-3'} mx-auto text-center`}>
    <PromptSuggestion.Header>
      {workspace && <p className="type-label mb-2 text-accent">进阶建议</p>}
      <PromptSuggestion.Title prominent={workspace}>{composer.snapshot ? '梳理当前专题' : composer.itemCount ? '深入分析已选内容' : '让 Agent 深入分析'}</PromptSuggestion.Title>
      <PromptSuggestion.Description className="mt-1">{composer.snapshot || composer.itemCount
        ? '从已有材料出发，核对证据并整理下一步。' : '从内容、订阅和运行状态出发，形成有依据的判断与方案。'}选择后可编辑，不会直接发送。</PromptSuggestion.Description>
    </PromptSuggestion.Header>
    {workspace ? <Suspense fallback={<p className="type-meta text-muted">正在准备建议…</p>}><SpatialSuggestions Button={Button} items={suggestions(composer)} onSelect={fillSuggestion} /></Suspense> : <PromptSuggestion.Items layout={workspace ? 'tiles' : 'list'} className="mt-5 text-left" aria-label="进阶建议任务">
      {suggestions(composer).map(({ title, category, prompt, description, icon: Icon }) => <PromptSuggestion.Item
        key={title} layout={workspace ? 'tile' : 'row'} aria-label={title} onPress={() => fillSuggestion(prompt)}>
        <span className={workspace ? 'flex size-8 shrink-0 items-center justify-center rounded-lg bg-default text-accent' : 'shrink-0 text-accent'}>
          <Icon size={workspace ? 17 : 16} aria-hidden="true" />
        </span>
        <span className="min-w-0 flex-1">
          {workspace && <span className="type-label block text-accent">{category}</span>}
          <PromptSuggestion.ItemTitle prominent={workspace} className={workspace ? 'mt-1' : ''}>{title}</PromptSuggestion.ItemTitle>
          <PromptSuggestion.ItemDescription prominent={workspace}>{description}</PromptSuggestion.ItemDescription>
        </span>
        <Icons.ArrowUpRight size={15} className={workspace ? 'absolute right-3 top-3 text-muted' : 'shrink-0 text-muted'} aria-hidden="true" />
      </PromptSuggestion.Item>)}
    </PromptSuggestion.Items>}
  </PromptSuggestion>
}
