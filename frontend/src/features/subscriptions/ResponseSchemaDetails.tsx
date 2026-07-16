import type { Job, ResponseSchemaField, ResponseSchemaSummary, SourceResponseSchema } from '../../api/types'
import { Box, Stack, Status, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '../../ui'

type SourceName = string | { display_name?: string }

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function schemaSummary(value: unknown): ResponseSchemaSummary | null {
  if (!isRecord(value) || !Array.isArray(value.fields)) return null
  const fields = value.fields.flatMap((candidate): ResponseSchemaField[] => {
    if (!isRecord(candidate) || typeof candidate.path !== 'string' || typeof candidate.type !== 'string') return []
    return [{ path: candidate.path, type: candidate.type }]
  })
  return {
    root_type: typeof value.root_type === 'string' ? value.root_type : 'unknown',
    fields,
    truncated: value.truncated === true,
  }
}

function responseSchemas(job: Job): SourceResponseSchema[] {
  const result = job.result ?? job.result_json
  const candidates = isRecord(result) ? result.response_schemas : undefined
  if (!Array.isArray(candidates)) return []
  return candidates.flatMap((candidate): SourceResponseSchema[] => {
    if (!isRecord(candidate) || typeof candidate.source_id !== 'string') return []
    return [{
      source_id: candidate.source_id,
      catalog_type: typeof candidate.catalog_type === 'string' ? candidate.catalog_type : undefined,
      capture_status: typeof candidate.capture_status === 'string' ? candidate.capture_status : undefined,
      upstream: schemaSummary(candidate.upstream),
      normalized: schemaSummary(candidate.normalized),
      job_truncated: candidate.job_truncated === true,
    }]
  })
}

function sourceName(sourceNames: ReadonlyMap<string, SourceName>, sourceId: string): string {
  const value = sourceNames.get(sourceId)
  if (typeof value === 'string') return value
  return value?.display_name || sourceId
}

const captureLabels: Record<string, string> = {
  captured: '本次响应',
  empty: '空响应',
  cached: '复用缓存',
  unavailable: '未记录',
}

const captureMessages: Record<string, string> = {
  empty: '上游成功返回空结果，本次没有可展示字段。',
  cached: '本次使用共享缓存，未重新观察上游响应。',
  unavailable: '本次运行未能记录上游响应结构。',
}

function SchemaTable({ title, schema }: { title: string; schema?: ResponseSchemaSummary | null }) {
  return <Box sx={{ minWidth: 0 }}>
    <Typography component="h5" variant="subtitle2">{title}</Typography>
    {!schema
      ? <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>本次运行未记录该结构。</Typography>
      : <>
        <Typography variant="caption" color="text.secondary">根类型：{schema.root_type}{schema.truncated ? ' · 已截断' : ''}</Typography>
        {schema.fields.length === 0
          ? <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>没有可展示的字段。</Typography>
          : <TableContainer sx={{ mt: 0.75, maxHeight: 320 }}>
            <Table size="small" stickyHeader aria-label={`${title}字段`} sx={{ tableLayout: 'fixed' }}>
              <TableHead><TableRow><TableCell sx={{ width: '72%' }}>字段路径</TableCell><TableCell>类型</TableCell></TableRow></TableHead>
              <TableBody>{schema.fields.map((field) => <TableRow key={`${field.path}:${field.type}`}>
                <TableCell sx={{ overflowWrap: 'anywhere', fontFamily: 'monospace' }}>{field.path}</TableCell>
                <TableCell>{field.type}</TableCell>
              </TableRow>)}</TableBody>
            </Table>
          </TableContainer>}
      </>}
  </Box>
}

export function ResponseSchemaDetails({ job, sourceNames }: { job: Job; sourceNames: ReadonlyMap<string, SourceName> }) {
  const schemas = responseSchemas(job)

  return <Box component="details" sx={{ mt: 1.25 }}>
    <Typography component="summary" variant="caption" color="text.secondary" sx={{ cursor: 'pointer' }}>响应结构</Typography>
    {schemas.length === 0 && <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>本次运行未记录响应结构。</Typography>}
    <Stack spacing={2} sx={{ mt: 1.25 }}>
      {schemas.map((schema, index) => <Box key={`${schema.source_id}:${index}`} sx={{ borderTop: index ? 1 : 0, borderColor: 'divider', pt: index ? 1.5 : 0 }}>
        <Stack direction="row" spacing={0.75} useFlexGap sx={{ alignItems: 'center', flexWrap: 'wrap', mb: 1.25 }}>
          <Typography component="h4" variant="subtitle1">{sourceName(sourceNames, schema.source_id)}</Typography>
          {schema.catalog_type && <Status label={schema.catalog_type} />}
          {schema.capture_status && <Status label={captureLabels[schema.capture_status] || schema.capture_status} />}
          {schema.job_truncated && <Status label="任务结构已截断" tone="warning" />}
        </Stack>
        {schema.capture_status && captureMessages[schema.capture_status] && <Typography variant="body2" color="text.secondary" sx={{ mb: 1.25 }}>{captureMessages[schema.capture_status]}</Typography>}
        {schema.job_truncated && <Typography variant="body2" color="text.secondary" sx={{ mb: 1.25 }}>字段较多，已按安全上限截断。</Typography>}
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'minmax(0, 1fr)', md: 'repeat(2, minmax(0, 1fr))' }, gap: 2 }}>
          <SchemaTable title="上游原始结构" schema={schema.upstream} />
          <SchemaTable title="系统标准化结构" schema={schema.normalized} />
        </Box>
      </Box>)}
    </Stack>
  </Box>
}
