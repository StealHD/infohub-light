import type { Job, ResponseSchemaField, ResponseSchemaSummary, SourceResponseSchema } from '../../api/types'
import { Chip } from '../../design-system'

type SourceName = string | { display_name?: string }
const record = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === 'object' && !Array.isArray(value)

function summary(value: unknown): ResponseSchemaSummary | null {
  if (!record(value) || !Array.isArray(value.fields)) return null
  const fields = value.fields.flatMap((candidate): ResponseSchemaField[] => record(candidate) && typeof candidate.path === 'string' && typeof candidate.type === 'string' ? [{ path: candidate.path, type: candidate.type }] : [])
  return { root_type: typeof value.root_type === 'string' ? value.root_type : 'unknown', fields, truncated: value.truncated === true }
}

function schemas(job: Job): SourceResponseSchema[] {
  const result = job.result ?? job.result_json
  const candidates = record(result) ? result.response_schemas : undefined
  if (!Array.isArray(candidates)) return []
  return candidates.flatMap((candidate): SourceResponseSchema[] => !record(candidate) || typeof candidate.source_id !== 'string' ? [] : [{ source_id: candidate.source_id, catalog_type: typeof candidate.catalog_type === 'string' ? candidate.catalog_type : undefined, capture_status: typeof candidate.capture_status === 'string' ? candidate.capture_status : undefined, upstream: summary(candidate.upstream), normalized: summary(candidate.normalized), job_truncated: candidate.job_truncated === true }])
}

const labels: Record<string, string> = { captured: '本次响应', empty: '空响应', cached: '复用缓存', unavailable: '未记录', truncated: '已截断' }
const messages: Record<string, string> = { empty: '上游成功返回空结果，本次没有可展示字段。', cached: '本次使用共享缓存，未重新观察上游响应。', unavailable: '本次运行未能记录上游响应结构。', truncated: '字段较多，已按安全上限截断。' }

function SchemaTable({ title, schema }: { title: string; schema?: ResponseSchemaSummary | null }) {
  return <section className="min-w-0"><h5 className="type-control">{title}</h5>{!schema ? <p className="type-body mt-2 text-muted">本次运行未记录该结构。</p> : <><p className="type-meta mt-1 text-muted">根类型：{schema.root_type}{schema.truncated ? ' · 已截断' : ''}</p>{schema.fields.length ? <div className="mt-2 max-h-72 overflow-auto"><table className="type-meta w-full table-fixed text-left"><thead><tr className="border-b border-separator"><th className="w-[72%] py-2">字段路径</th><th>类型</th></tr></thead><tbody>{schema.fields.map((field) => <tr key={`${field.path}:${field.type}`} className="border-b border-separator"><td className="overflow-wrap-anywhere py-2 font-mono">{field.path}</td><td>{field.type}</td></tr>)}</tbody></table></div> : <p className="type-body mt-2 text-muted">没有可展示的字段。</p>}</>}</section>
}

export function HeroResponseSchemaDetails({ job, sourceNames }: { job: Job; sourceNames: ReadonlyMap<string, SourceName> }) {
  const values = schemas(job)
  return <details className="mt-3"><summary className="type-meta cursor-pointer text-muted">响应结构</summary>{!values.length && <p className="type-body mt-2 text-muted">本次运行未记录响应结构。</p>}<div className="mt-3 grid gap-4">{values.map((schema, index) => {
    const source = sourceNames.get(schema.source_id)
    const name = typeof source === 'string' ? source : source?.display_name || schema.source_id
    return <section key={`${schema.source_id}:${index}`} className="min-w-0 border-t border-separator pt-3"><div className="flex flex-wrap items-center gap-2"><h4 className="type-control">{name}</h4>{schema.catalog_type && <Chip size="sm" variant="soft"><Chip.Label>{schema.catalog_type}</Chip.Label></Chip>}{schema.capture_status && <Chip size="sm" variant="soft"><Chip.Label>{labels[schema.capture_status] || '未记录'}</Chip.Label></Chip>}</div>{schema.capture_status && messages[schema.capture_status] && <p className="type-body mt-2 text-muted">{messages[schema.capture_status]}</p>}{schema.job_truncated && <p className="type-body mt-2 text-muted">字段较多，已按安全上限截断。</p>}<div className="mt-3 grid min-w-0 gap-4 min-[760px]:grid-cols-2"><SchemaTable title="上游原始结构" schema={schema.upstream} /><SchemaTable title="系统标准化结构" schema={schema.normalized} /></div></section>
  })}</div></details>
}
