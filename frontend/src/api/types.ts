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

export type NotificationChannel = 'email' | 'webhook'

export type UserNotificationSettings = {
  schema_version: number
  enabled: boolean
  channel: NotificationChannel
  email_configured: boolean
  email_transport_ready: boolean
  webhook_configured: boolean
  last_test_status: string | null
  last_tested_at: string | null
  last_test_error_code: string | null
  updated_at: string | null
}

export type UserNotificationSettingsPatch = {
  enabled?: boolean
  channel?: NotificationChannel
  email_address?: string | null
  webhook_url?: string | null
}

export type NotificationTestResult = {
  sent: boolean
  channel: NotificationChannel
}

export type NotificationEmailProvider = 'qq' | 'netease' | 'gmail' | 'resend' | 'amazon_ses'

export type NotificationEmailProviderOption = {
  provider: NotificationEmailProvider
  label: string
  credential_label: string
  sender_hint: string
  requires_region: boolean
  requires_smtp_username: boolean
  smtp_port: 465
  security: 'ssl'
}

export type NotificationEmailTransport = {
  schema_version: number
  configured: boolean
  provider: NotificationEmailProvider | null
  sender_email: string | null
  sender_name: string
  region: string | null
  smtp_username: string | null
  enabled: boolean
  credential_configured: boolean
  generation: number
  last_test_status: 'sent' | 'failed' | null
  last_test_generation: number | null
  last_tested_at: string | null
  last_test_error_code: string | null
  can_enable: boolean
  ready: boolean
  connection: {
    smtp_host: string
    smtp_port: 465
    security: 'ssl'
    smtp_username: string
  } | null
  providers: NotificationEmailProviderOption[]
  updated_at: string | null
}

export type NotificationEmailTransportPatch = {
  provider?: NotificationEmailProvider
  sender_email?: string
  sender_name?: string
  credential?: string | null
  enabled?: boolean
  region?: string | null
  smtp_username?: string | null
}

export type NotificationEmailTransportTestResult = {
  sent: boolean
  generation: number
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
  ingested_at?: string
  images?: string[]
  media_urls?: string[]
  image_url?: string
  timeline_bucket?: 'today' | 'feed' | 'history'
  storage_state?: 'online' | 'archived'
  body_available?: boolean
  user_state?: UserItemState
  presentation?: FeedPresentation
}

export type ContentFormat = 'article' | 'video' | 'image' | 'gallery' | 'audio' | 'social_post' | 'discussion' | 'release' | 'other'
export type ContentFormatOrigin = 'upstream' | 'deterministic' | 'ai' | 'fallback'

export type FeedPresentation = {
  version: 1 | 2
  source: { id: string; catalog_type: string; platform: string; name: string; avatar_url?: string }
  author: { name: string; kind: 'person' | 'account' | 'channel' | 'organization' | 'unknown' }
  timing: { published_at: string; fetched_at: string; effective_at?: string }
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
  window?: FeedWindow
}

export type FeedWindow = {
  timezone: 'Asia/Shanghai'
  feed_days: 7 | 14 | 30
  today_start: string
  feed_start: string
  now: string
}

export type FeedHistory = {
  schema_version: number
  scope: 'user'
  items: FeedItem[]
  featured_items: FeedItem[]
  item_count: number
  total_count: number
  limit: number
  offset: number
  has_more: boolean
  snapshots: unknown[]
  window?: FeedWindow
}

export type FeedHistoryParams = {
  q?: string
  sourceId?: string
  limit?: number
  offset?: number
}

export type FeedSearch = {
  schema_version: 1
  scope: 'user'
  items: FeedItem[]
  item_count: number
  total_count: number
  has_more: boolean
  next_cursor: string | null
  window: FeedWindow
}

export type FeedSearchParams = {
  q: string
  limit?: number
  cursor?: string
  submitted?: boolean
}

export type SavedFeed = {
  schema_version: 1
  scope: 'user'
  items: FeedItem[]
  item_count: number
  limit: number
  offset: number
}

export type IgnoredFeed = SavedFeed

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
  today_item_count?: number
  feed_item_count?: number
  current_item_count?: number
  history_item_count?: number
  last_issue?: RunIssue | null
  last_job_id?: string | null
}

export type SourceHealthResponse = {
  schema_version: number
  scope: 'user'
  summary: Record<SourceHealthStatus | 'total', number>
  items: SourceHealthItem[]
  window?: FeedWindow
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
  credential_mode?: 'source_secret' | 'workspace_apify_pool'
  fields: CatalogField[]
}

export type CatalogSource = {
  id: string
  type: string
  display_name: string
  description?: string
  scope: 'public' | 'workspace' | 'private'
  owner_user_id?: string | null
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
  notify_on_new_items?: boolean
  notification_enabled_at?: string | null
  schedule?: SourceSchedule
  reused_item_count?: number
}

export type SubscriptionDisableDisposition = 'keep' | 'save' | 'dismiss'

export type SubscriptionPatch = Partial<Pick<Subscription,
  'enabled' | 'override_channel' | 'override_topics' | 'personal_tags' | 'analysis_mode' | 'priority' | 'notify_on_new_items'
>> & {
  on_disable?: SubscriptionDisableDisposition
}

export type SourceUsage = {
  source_id: string
  subscriber_count: number
  enabled_subscriber_count: number
}

export type SourceShareResult = {
  source: CatalogSource
  management_transferred: true
  notice: string
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

export type SecretQuota = {
  secret_id: string
  provider: 'apify'
  currency: 'USD'
  cycle_start_at: string
  cycle_end_at: string
  checked_at: string
  monthly_included_credits_usd: number
  monthly_usage_usd: number
  remaining_included_credits_usd: number
  max_monthly_usage_usd: number
  remaining_hard_limit_usd: number
}

export type ApifyKeyPoolMemberStatus =
  | 'active'
  | 'standby'
  | 'draining'
  | 'depleted'
  | 'invalid'

export type ApifyKeyPoolMember = {
  secret_id: string
  position: number
  status: ApifyKeyPoolMemberStatus
  blocked_until: string | null
  cycle_end_at: string | null
  last_checked_at: string | null
  last_error_code: string | null
  active_run_count: number
}

export type ApifyKeyPool = {
  schema_version: 1
  enabled: boolean
  generation: number
  status: 'empty' | 'ready' | 'draining' | 'blocked' | 'exhausted'
  active_secret_id: string | null
  draining_secret_id: string | null
  blocked_reason: string | null
  retry_at: string | null
  members: ApifyKeyPoolMember[]
}

export type ConfigResponse = {
  path?: string
  config: Record<string, unknown>
  taxonomy?: TaxonomyOptions
  env_status?: Array<{ name?: string; set?: boolean; used_by?: string[]; configured?: boolean; label?: string }>
}

export type StorageSummary = {
  schema_version: 1
  policy: {
    feed_snapshot_days: number
    feed_snapshot_per_user: number
    source_snapshot_days: number
    completed_job_days: number
    analysis_cache_days: number
    usage_event_days: number
    archive_after_days: number
    automatic_permanent_delete: false
  }
  bytes: {
    database: number
    media: number
    archives: number
  }
  counts: {
    content_total: number
    content_online: number
    content_archived: number
    feed_snapshots: number
    source_snapshots: number
    media_assets: number
    archive_batches: number
  }
  readiness: {
    feed_storage_v3: boolean
    content_timeline_v11: boolean
    ready: boolean
  }
  last_cleanup_at: string | null
}

export type StorageOperation = 'cleanup' | 'archive' | 'restore' | 'delete_archive'

export type StoragePlan = {
  id: string
  actor_user_id: string
  operation: StorageOperation
  status: 'previewed' | 'applied' | 'expired' | 'failed'
  payload: {
    request: Record<string, unknown>
    parameters: Record<string, unknown>
    preview: Record<string, unknown>
  }
  result: Record<string, unknown>
  fingerprint: string
  expires_at: string
  created_at: string
  applied_at: string | null
  updated_at: string
}

export type StorageArchive = {
  id: string
  status: 'committed' | 'restored' | 'failed' | 'deleted'
  cutoff_at: string
  checksum: string
  item_count: number
  media_count: number
  byte_size: number
  created_at: string
  committed_at: string
  restored_at: string | null
  updated_at: string
}

export type StorageArchives = {
  schema_version: 1
  archives: StorageArchive[]
}

export type TaxonomyOptions = {
  channels: string[]
  topics: string[]
}
