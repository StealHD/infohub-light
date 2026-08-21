export type ActorOpsV2CandidateView = {
  candidate_id: string
  actor_id: string
  publisher: string
  build_number: string | null
  lifecycle: string
  assignment: string
  priority: number | null
  generation: number
}

export function actorOpsV2CandidateLabel(candidate: ActorOpsV2CandidateView | null) {
  if (!candidate) return '未配置'
  const publisher = candidate.publisher.replace(/[-_]+/g, ' ').replace(/\b\w/g, (value) => value.toUpperCase())
  return `${publisher} · 版本 ${candidate.build_number || '已冻结'}`
}
