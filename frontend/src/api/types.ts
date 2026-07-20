export type UserRole = 'owner' | 'admin' | 'member' | 'viewer'

export type User = {
  id: string
  username: string
  display_name?: string
  role: UserRole
  enabled: boolean
  workspace_id?: string
}

export type AuthStatus = {
  authenticated: boolean
  user: User | null
}

export type AgentDelegationAccess = 'read' | 'subscriptions_write'

export type AgentDelegationScope = 'inteliscope:read' | 'inteliscope:subscriptions:write'

export type AgentDelegation = {
  id: string
  name: string
  client_type: 'openclaw'
  access: AgentDelegationAccess
  scopes: AgentDelegationScope[]
  token_prefix: string
  created_at: string
  expires_at: string
  last_used_at: string | null
  revoked_at: string | null
  status: 'active' | 'expired' | 'revoked'
}

export type AgentDelegationsResponse = {
  enabled: boolean
  subscription_writes_enabled: boolean
  mcp_url: string
  openclaw_chat: {
    enabled: boolean
    default_gateway_url: string
    protocol_version: 4
    target_version: string
  }
  token_ttl_days: 90
  max_active: 5
  connections: AgentDelegation[]
}

export type AgentDelegationCreated = {
  connection: AgentDelegation
  token: string
}

export type UserItemState = {
  is_read: boolean
  is_saved: boolean
  is_later: boolean
  dismissed: boolean
  read_at?: string | null
  saved_at?: string | null
  later_at?: string | null
  dismissed_at?: string | null
}

export type FeedItem = {
  id: string
  title: string
  url: string
  source?: string
  source_type?: string
  source_id?: string
  source_ids?: string[]
  subscription_id?: string
  subscription_ids?: string[]
  summary_zh?: string
  action_suggestion?: string
  score?: number
  scoring_disabled?: boolean
  signal_strength?: string
  signal_type?: string
  channel?: string
  category?: string
  topics?: string[]
  tags?: string[]
  published_at?: string
  fetched_at?: string
  images?: string[]
  media_urls?: string[]
  image_url?: string
  user_state?: UserItemState
  presentation?: FeedPresentation
}

export type ContentFormat = 'article' | 'video' | 'image' | 'gallery' | 'audio' | 'social_post' | 'discussion' | 'release' | 'other'
export type ContentFormatOrigin = 'upstream' | 'deterministic' | 'ai' | 'fallback'

export type FeedPresentation = {
  version: 1 | 2
  source: { id: string; catalog_type: string; platform: string; name: string; avatar_url?: string }
  author: { name: string; kind: 'person' | 'account' | 'channel' | 'organization' | 'unknown' }
  timing: { published_at: string; fetched_at: string }
  links: { canonical_url: string; source_url: string }
  content: {
    title: string
    title_origin: 'native' | 'generated'
    excerpt: string
    content_kind: 'feed_summary' | 'release_notes' | 'event_description' | 'post_body' | 'message' | 'caption' | 'discussion' | 'metadata_only'
    excerpt_truncated: boolean
    format?: ContentFormat
    format_origin?: ContentFormatOrigin
    body_text?: string
    body_truncated?: boolean
    body_completeness?: 'captured' | 'excerpt_only'
    unresolved_reason?: string
  }
  media?: {
    images: Array<{
      asset_id?: string
      url: string
      width?: number
      height?: number
      alt: string
    }>
    count: number
    total_image_count?: number
    truncated?: boolean
  }
  taxonomy: {
    channel: string
    configured_topics: string[]
    inferred_topics: string[]
    topics: string[]
    entities: string[]
  }
  engagement: {
    native_score: number | null
    likes: number | null
    comments: number | null
    reposts: number | null
    shares: number | null
    upvote_ratio: number | null
  }
  analysis: {
    status: 'ai' | 'fallback' | 'personal_only' | 'disabled'
    score: number
    signal_strength: string
    signal_type: string
    summary_zh: string
    action_suggestion?: string
  }
}

export type RunIssue = {
  stage?: string
  code?: string
  message?: string
  retryable?: boolean
  source_id?: string
}

export type SourceOutcome = {
  source_id: string
  subscription_id?: string | null
  source_key?: string
  analysis_mode?: string
  status: 'succeeded' | 'failed'
  fetched_count: number
  issue?: RunIssue | null
}

export type FeedSnapshot = {
  schema_version: number
  run_id?: string
  run_status?: 'succeeded' | 'partial' | 'failed'
  scope?: 'user'
  snapshot_id?: string
  generated_at?: string
  updated_at?: string
  items: FeedItem[]
  today_items?: FeedItem[]
  featured_items?: FeedItem[]
  daily_push_items?: FeedItem[]
  item_count?: number
  ai_enabled?: boolean
  source_outcomes?: SourceOutcome[]
  issues?: RunIssue[]
}

export type FeedHistory = {
  schema_version: number
  scope: 'user'
  items: FeedItem[]
  featured_items: FeedItem[]
  item_count: number
  snapshots: unknown[]
}

export type SavedFeed = {
  schema_version: 1
  scope: 'user'
  items: FeedItem[]
  item_count: number
  limit: number
  offset: number
}

export type SourceHealthStatus = 'unknown' | 'healthy' | 'degraded' | 'failing'

export type SourceHealthItem = {
  subscription_id: string
  source_id: string
  source_display_name?: string
  source_type?: string
  status: SourceHealthStatus
  last_attempt_at?: string | null
  last_success_at?: string | null
  consecutive_failures: number
  last_fetched_count?: number
  last_issue?: RunIssue | null
  last_job_id?: string | null
}

export type SourceHealthResponse = {
  schema_version: number
  scope: 'user'
  summary: Record<SourceHealthStatus | 'total', number>
  items: SourceHealthItem[]
}

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'partial' | 'failed' | 'cancelled'

export type ResponseSchemaField = {
  path: string
  type: 'object' | 'array' | 'string' | 'integer' | 'number' | 'boolean' | 'null' | 'mixed' | string
}

export type ResponseSchemaSummary = {
  root_type: string
  fields: ResponseSchemaField[]
  truncated?: boolean
}

export type SourceResponseSchema = {
  source_id: string
  catalog_type?: string
  capture_status?: 'captured' | 'empty' | 'cached' | 'unavailable' | string
  upstream?: ResponseSchemaSummary | null
  normalized?: ResponseSchemaSummary | null
  job_truncated?: boolean
}

export type Job = {
  id: string
  user_id: string
  job_type: 'source_test' | 'source_fetch' | 'user_feed_refresh' | string
  source_id?: string | null
  subscription_id?: string | null
  status: JobStatus
  created_at?: string
  started_at?: string | null
  finished_at?: string | null
  error_code?: string | null
  error_message?: string | null
  retryable?: boolean
  result?: Record<string, unknown> | null
  result_json?: Record<string, unknown> | null
  deduplicated?: boolean
}

export type CatalogField = {
  name: string
  label: string
  input_type: string
  required: boolean
  default: unknown
  options?: Array<string | { value: string; label: string }>
  min?: number | null
  max?: number | null
  help?: string
}

export type SourceTypeDefinition = {
  type: string
  label?: string
  display_name?: string
  fields: CatalogField[]
}

export type CatalogSource = {
  id: string
  type: string
  display_name: string
  description?: string
  scope: 'public' | 'workspace' | 'private'
  owner_user_id?: string
  default_channel?: string | null
  default_topics?: string[]
  config?: Record<string, unknown>
  enabled: boolean
  subscribed?: boolean
  subscription_id?: string | null
  editable?: boolean
  secret_configured?: boolean
  secret_env?: string | null
  avatar_url?: string | null
}

export type SourceSchedule = {
  schema_version?: number
  enabled: boolean
  interval_minutes: number
  allowed_intervals?: number[]
  next_run_at?: string | null
  last_job?: Job | null
  active_job?: Job | null
  worker_status?: string
  last_skip_reason?: string | null
}

export type Subscription = {
  id: string
  user_id: string
  source_id: string
  source_display_name?: string
  source_type?: string
  enabled: boolean
  override_channel?: string | null
  override_topics?: string[]
  personal_tags?: string[]
  analysis_mode?: 'full' | 'personal_only'
  priority?: number
  schedule?: SourceSchedule
}

export type FeedSchedule = SourceSchedule & {
  last_enqueued_at?: string | null
  last_evaluated_at?: string | null
}

export type SecretRef = {
  id: string
  name: string
  kind: 'ai' | 'apify'
  provider: string
  env_name: string
  is_set: boolean
  used_by: Array<{ type: string; id: string; name: string }>
}

export type ConfigResponse = {
  path?: string
  config: Record<string, unknown>
  taxonomy?: TaxonomyOptions
  env_status?: Array<{ name?: string; configured?: boolean; label?: string }>
}

export type TaxonomyOptions = {
  channels: string[]
  topics: string[]
}
