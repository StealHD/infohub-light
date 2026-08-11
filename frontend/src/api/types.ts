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

export type NotificationChannel = 'email' | 'webhook' | 'telegram'

export type WebhookProvider =
  | 'generic_event'
  | 'generic_text'
  | 'feishu_lark_v2'
  | 'wecom'
  | 'dingtalk'
  | 'slack'
  | 'discord'

export type WebhookProviderOption = {
  provider: WebhookProvider
  label: string
  description: string
  url_hint: string
  signing: 'none' | 'optional'
  verification_mode: 'http_status' | 'provider_response'
}

export type NotificationChannelTestStatus = 'sent' | 'failed' | 'unknown' | null

export type NotificationChannelState = {
  enabled: boolean
  configured: boolean
  available: boolean
  generation: number
  enabled_at: string | null
  last_test_status: NotificationChannelTestStatus
  last_tested_at: string | null
  last_test_error_code: string | null
}

export type NotificationWebhookChannelState = NotificationChannelState & {
  provider: WebhookProvider
  provider_explicit: boolean
  signing_secret_configured: boolean
  verification_mode: 'http_status' | 'provider_response'
}

export type NotificationChannelStates = {
  email: NotificationChannelState
  webhook: NotificationWebhookChannelState
  telegram: NotificationChannelState
}

export type NotificationTargetScope = 'private' | 'shared'

export type NotificationTarget = {
  id: string
  name: string
  scope: NotificationTargetScope
  channel: NotificationChannel
  configured: boolean
  enabled: boolean
  available: boolean
  transport_ready: boolean
  config_generation: number
  activation_generation: number
  enabled_at: string | null
  last_test_status: NotificationChannelTestStatus
  last_tested_at: string | null
  last_test_error_code: string | null
  can_edit: boolean
  can_test: boolean
  can_enable: boolean
  usage: {
    user_binding_count: number
    alert_binding_count: number
    preferred_active_delivery_count: number
    alert_active_delivery_count: number
  }
  updated_at: string | null
  webhook_provider?: WebhookProvider
  webhook_signing_secret_configured?: boolean
  webhook_verification_mode?: 'http_status' | 'provider_response'
}

export type NotificationTargets = {
  schema_version: 1
  targets: NotificationTarget[]
  webhook_provider_options: WebhookProviderOption[]
}

export type NotificationService = NotificationTarget & {
  legacy_private: boolean
  can_validate: boolean
}

export type NotificationServiceEmailCredentialState = {
  configured: boolean
  ready: boolean
  generation: number
  provider: NotificationEmailProvider | null
  sender_name: string | null
  region: string | null
  sender_email_configured: boolean
  smtp_username_configured: boolean
  providers: NotificationEmailProviderOption[]
}

export type NotificationServices = {
  schema_version: 1
  services: NotificationService[]
  channel_credentials: {
    email: NotificationServiceEmailCredentialState
    telegram: {
      configured: boolean
      ready: boolean
      generation: number
    }
    webhook: {
      configured: true
      ready: true
      generation: 0
    }
  }
  webhook_provider_options: WebhookProviderOption[]
  can_manage: boolean
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

export type NotificationTargetCreate = {
  name: string
  scope: NotificationTargetScope
  channel: NotificationChannel
  email_address?: string
  webhook_url?: string
  webhook_provider?: WebhookProvider
  webhook_signing_secret?: string
  telegram_chat_id?: string
}

export type NotificationTargetPatch = {
  name?: string
  enabled?: boolean
  email_address?: string
  webhook_url?: string
  webhook_provider?: WebhookProvider
  webhook_signing_secret?: string | null
  telegram_chat_id?: string
}

export type NotificationServiceEmailTransportPatch = {
  provider?: NotificationEmailProvider
  sender_email?: string
  sender_name?: string
  credential?: string
  region?: string | null
  smtp_username?: string | null
}

export type NotificationServiceCreate = Omit<NotificationTargetCreate, 'scope'> & {
  scope?: 'shared'
  telegram_bot_token?: string
  email_transport?: NotificationServiceEmailTransportPatch
}

export type NotificationServicePatch = NotificationTargetPatch & {
  telegram_bot_token?: string
  email_transport?: NotificationServiceEmailTransportPatch
}

export type UserNotificationSettings = {
  schema_version: 4
  enabled: boolean
  target_ids: string[]
  selected_targets: NotificationTarget[]
  channels: NotificationChannel[]
  channel: NotificationChannel
  channel_states: NotificationChannelStates
  email_configured: boolean
  email_transport_ready: boolean
  webhook_configured: boolean
  webhook_provider: WebhookProvider
  webhook_provider_explicit: boolean
  webhook_signing_secret_configured: boolean
  webhook_verification_mode: 'http_status' | 'provider_response'
  webhook_provider_options: WebhookProviderOption[]
  telegram_configured: boolean
  telegram_transport_ready: boolean
  last_test_status: NotificationChannelTestStatus
  last_tested_at: string | null
  last_test_error_code: string | null
  updated_at: string | null
}

export type UserNotificationSettingsPatch = {
  enabled?: boolean
  target_ids?: string[]
  channels?: NotificationChannel[]
  channel?: NotificationChannel
  email_address?: string | null
  webhook_url?: string | null
  webhook_provider?: WebhookProvider
  webhook_signing_secret?: string | null
  telegram_chat_id?: string | null
}

export type NotificationTestResult = {
  sent: boolean
  enabled?: boolean
  channel: NotificationChannel
  target_id?: string
  provider?: WebhookProvider
  verification?: 'http_accepted' | 'provider_accepted'
}

export type AgentDelegationAccess = 'read' | 'subscriptions_write'

export type AgentDelegationDiagnosticsScope = 'self' | 'workspace'

export type AgentDelegationScope =
  | 'inteliscope:read'
  | 'inteliscope:subscriptions:write'
  | 'inteliscope:diagnostics:read'

export type AgentDelegation = {
  id: string
  name: string
  client_type: 'openclaw'
  access: AgentDelegationAccess
  diagnostics_scope: AgentDelegationDiagnosticsScope
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
    image_io_enabled?: boolean
    media_origins?: string[]
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

export type SourceSummary = {
  schema_version: 1
  overview: string
  highlights: string[]
  item_count: number
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

export type FeedEndMessageScene = 'empty' | 'first_end' | 'repeat_end'

export type FeedEndMessages = {
  schema_version: 1
  source: 'builtin' | 'ai'
  status: 'disabled' | 'pending' | 'refreshing' | 'ready' | 'degraded'
  generation: number
  generated_at: string | null
  last_attempt_at: string | null
  next_refresh_at: string | null
  retry_at: string | null
  last_error_code: string | null
  scenes: Record<FeedEndMessageScene, string[]>
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
  catalog_source_type?: string
  label?: string
  display_name?: string
  credential_mode?: 'none' | 'source_secret' | 'workspace_apify_pool'
  availability?: 'ready' | 'temporarily_unavailable'
  unavailable_reason?: 'platform_setup_pending' | 'workspace_credential_unavailable' | null
  fields: CatalogField[]
}

export type SourceTypesResponse = {
  schema_version: 1
  generation: number
  source_types: SourceTypeDefinition[]
}

export type ApifyActorSourceCapability = {
  profile_id: string
  platform: string
  target_type: string
  capability: string
  mode: 'primary' | 'fallback'
  generation: number
  storage_type: string
  fields: Array<{
    name: string
    input_type: string
    required: boolean
  }>
}

export type ApifyActorSupportProfile = {
  id: string
  route_key: string
  platform: 'x' | 'youtube' | 'instagram'
  target_type: 'profile' | 'channel'
  capability: 'items'
  mode: 'primary' | 'fallback'
  label: string
}

export type ApifyActorSourceCapabilitiesResponse = {
  schema_version: 1
  generation: number
  support_profiles: ApifyActorSupportProfile[]
  capabilities: ApifyActorSourceCapability[]
}

export type CatalogSource = {
  id: string
  type: string
  setup_type?: string
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
  base_url?: string
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

export type ApifyActorRouteSupportStatus =
  | 'supported'
  | 'degraded'
  | 'pending'
  | 'unsupported'
  | 'blocked'

export type ApifyActorRouteRuntimeStatus =
  | 'ready'
  | 'degraded'
  | 'blocked'
  | 'exhausted'
  | 'budget_blocked'

export type ApifyActorSlotName = 'primary' | 'backup_1' | 'backup_2'

export type ApifyActorRevisionLifecycle =
  | 'proposed'
  | 'static_valid'
  | 'probationary'
  | 'certified'
  | 'legacy_builtin'
  | 'quarantined'
  | 'superseded'
  | 'rejected'

export type ApifyActorCertificationProgress = {
  auto_promotes: boolean
  lifecycle: ApifyActorRevisionLifecycle
  success_identities: { current: number; required: number }
  reference_targets: { current: number; required: number }
  valid_samples: { current: number; successful: number; required: number }
  success_rate: { current: number; required: number }
  observation_started_at: string | null
  eligible_at: string | null
  remaining_seconds: number | null
  blockers: string[]
}

export type ApifyActorWorkflowKind =
  | 'setup_discovery_required'
  | 'setup_discovery_running'
  | 'setup_candidate_selection_required'
  | 'setup_canary_approval_required'
  | 'setup_canary_running'
  | 'setup_activation_approval_required'
  | 'backup_2_discovery_required'
  | 'backup_2_discovery_running'
  | 'backup_2_candidate_selection_required'
  | 'backup_2_canary_approval_required'
  | 'backup_2_canary_running'
  | 'backup_2_activation_approval_required'
  | 'legacy_discovery_required'
  | 'legacy_discovery_running'
  | 'legacy_candidate_selection_required'
  | 'legacy_canary_approval_required'
  | 'legacy_canary_running'
  | 'legacy_activation_approval_required'
  | 'probation_observing'
  | 'source_validation_required'
  | 'runtime_degraded_monitoring'
  | 'blocked_unknown_start'
  | 'budget_blocked'
  | 'complete'

export type ApifyActorWorkflowFailure = {
  phase: 'route_validation' | 'source_validation'
  code: string
  actual_cost_usd: number | null
  cost_final: boolean
}

export type ApifyActorWorkflowProgress = Record<string, unknown> & {
  last_failure?: ApifyActorWorkflowFailure
}

export type ApifyActorWorkflow = {
  kind: ApifyActorWorkflowKind | string
  goal: ApifyActorPoolGoal | null
  stage_id?: string | null
  run_id?: string | null
  plan_hash?: string | null
  progress: ApifyActorWorkflowProgress
  blockers: string[]
}

export type ApifyActorRevisionSummary = {
  revision_id: string
  actor_id: string
  actor_public_name?: string | null
  publisher: string
  build_id?: string | null
  build_number?: string | null
  manifest_hash?: string | null
  lifecycle: ApifyActorRevisionLifecycle
  certification_progress?: ApifyActorCertificationProgress | null
  listed_price_usd_per_1000?: number | null
  pricing?: {
    model: string | null
    billing_unit: 'free' | 'dataset_item' | 'event' | 'unknown'
    unit_price_min_usd: number | null
    unit_price_max_usd: number | null
    minimum_charge_usd: number | null
    minimum_run_cap_usd: number | null
  }
  last_charge_usd?: number | null
  avg_charge_24h_usd?: number | null
  last_canary_at?: string | null
  last_canary_status?: string | null
  can_canary?: boolean
  can_activate?: boolean
}

export type ApifyActorRouteActiveSlot = {
  slot: ApifyActorSlotName
  revision_id: string | null
  runnable: boolean
  validation_status?: string | null
  revision?: ApifyActorRevisionSummary | null
}

export type ApifyActorRouteSummary = {
  route_id: string
  route_key: string
  platform: string
  target_type: string
  capability: string
  mode: 'primary' | 'fallback'
  generation: number
  support_status: ApifyActorRouteSupportStatus
  runtime_status: ApifyActorRouteRuntimeStatus
  runnable_slots: number
  required_slots: 3
  min_runtime_healthy: 2
  publisher_count: number
  per_run_cap_usd: number
  discovery_run_id?: string | null
  blocked_reason?: string | null
  updated_at?: string | null
  workflow?: ApifyActorWorkflow
}

export type ApifyActorSourceValidationSlot = {
  slot: ApifyActorSlotName
  revision_id: string | null
  status: string
  last_canary_at?: string | null
  last_canary_status?: string | null
  can_canary?: boolean
}

export type ApifyActorSourceValidation = {
  source_id: string
  binding_status: string
  generation: number
  slots: ApifyActorSourceValidationSlot[]
  activation_confirmation?: string | null
  staged_validation?: {
    stage_id: string
    status: string
    required_count: number
    passed_count: number
    last_error_code?: string | null
  }
}

export type ApifyActorRevisionDiff = {
  slot: ApifyActorSlotName
  current_revision_id: string | null
  proposed_revision_id: string
  changes: string[]
}

export type ApifyActorRouteDetail = ApifyActorRouteSummary & {
  slots: ApifyActorRouteActiveSlot[]
  revisions: ApifyActorRevisionSummary[]
  source_validations?: ApifyActorSourceValidation[]
  source_validation_summary?: {
    ready: number
    pending: number
    failed: number
  }
  replacement_needed?: boolean
  revision_diffs?: ApifyActorRevisionDiff[]
  activation_recommendation?: {
    ready: boolean
    already_active: boolean
    confirmation: '确认启用 Actor 主备'
    problems: string[]
    certified_actor_count: number
    backup_2_actor_count: number
    runnable_actor_count: number
    publisher_count: number
    activation_mode: 'standard_2plus1' | 'expedited_2of3' | null
    slots: Array<{
      slot: ApifyActorSlotName
      revision_id: string | null
      revision: ApifyActorRevisionSummary | null
    }>
  }
  workflow?: ApifyActorWorkflow
}

export type ApifyActorRoutesResponse = {
  schema_version: 1
  generation: number
  support_profiles: ApifyActorSupportProfile[]
  routes: ApifyActorRouteSummary[]
}

export type ApifyActorDiscoveryCandidate = {
  revision: ApifyActorRevisionSummary
  rank?: number | null
  status: string
  validation_status?: string | null
  validation_outcome?: string | null
  validation_cost_usd?: number | null
  validation_cost_final?: boolean
  validation_duration_ms?: number | null
  actor_run_status?: string | null
  canary_in_flight?: boolean
  rejection_reasons?: string[]
  awaiting_approval?: boolean
}

export type ApifyActorDiscoveryRun = {
  schema_version: 5
  run_id: string
  route_id?: string | null
  generation: number
  stage: string
  status: string
  queries_completed?: number | null
  queries_limit?: number | null
  budget_cap_usd: number
  spent_usd?: number | null
  reserved_usd?: number | null
  unreconciled_cost_count?: number | null
  canary_attempts_used?: number | null
  canary_attempts_limit?: number | null
  canary_attempts_remaining?: number | null
  canary_timeout_seconds?: number | null
  candidate_count?: number | null
  candidate_shortfall?: number | null
  publisher_count?: number | null
  publisher_shortfall?: number | null
  error_code?: string | null
  failure_phase?: string | null
  measurement_mode?: boolean
  metrics?: ApifyActorDiscoveryMetrics
  rejections?: Array<{ reason: string; count: number }>
  candidates: ApifyActorDiscoveryCandidate[]
  canary_batch?: ApifyActorCanaryBatch | null
  updated_at?: string | null
}

export type ApifyActorCanaryPlanItem = {
  ordinal: number
  candidate_id?: string
  actor_public_name?: string
  revision_id: string
  actor_id: string
  publisher: string
  build_id: string
  build_number: string
  lifecycle: ApifyActorRevisionSummary['lifecycle']
  pricing?: ApifyActorRevisionSummary['pricing']
  authorized_cap_usd: number
  already_validated?: boolean
  validation_profile?: ApifyActorValidationProfile
}

export type ApifyActorValidationProfile = {
  timeout_seconds: number
  sample_items: 1 | 3 | 5
  max_charge_usd: number
  supports_sample_items: boolean
  options_hash: string
  profile_hash?: string
}

export type ApifyActorValidationProfileRequest = Pick<
  ApifyActorValidationProfile,
  'timeout_seconds' | 'sample_items' | 'max_charge_usd' | 'options_hash'
> & { candidate_id: string }

export type ApifyActorPoolGoal =
  | 'initial_pool'
  | 'complete_third'
  | 'upgrade_legacy'

export type ApifyActorPoolStage = {
  stage_id: string
  route_id: string
  discovery_run_id: string
  initial_batch_id: string
  goal: ApifyActorPoolGoal
  target_slot_count: 2 | 3
  selection_mode: 'server' | 'manual'
  base_generation: number
  base_pool_hash: string
  plan_hash: string
  max_total_charge_usd: number
  route_validation_cap_usd: number
  target_slots: Record<ApifyActorSlotName, string | null>
  target_pool_hash?: string | null
  status: string
  applied_route_generation?: number | null
  last_error_code?: string | null
  source_summary: {
    source_count: number
    required_count: number
    passed_count: number
    succeeded_sources: number
    failed_sources: number
    active_sources: number
  }
  cost_summary: {
    actual_cost_usd: number
    reserved_cost_usd: number
    validation_count: number
    cost_final: boolean
  }
  created_at: string
  updated_at: string
  applied_at?: string | null
}

export type ApifyActorCanaryPlan = {
  schema_version: 1 | 2 | 3
  goal?: ApifyActorPoolGoal
  selection_mode?: 'server' | 'manual'
  target_slot_count?: 2 | 3
  run_id: string
  route_id: string
  route_key: string
  platform: string
  target_type: string
  capability: string
  mode: 'primary' | 'fallback'
  generation: number
  status: 'ready' | 'activation_ready' | 'insufficient_candidates'
  ready: boolean
  activation_ready: boolean
  plan_hash: string
  max_candidates: number
  max_total_charge_usd: number
  per_candidate_cap_usd: number
  successful_actor_count: number
  successful_publisher_count: number
  attempts_used: number
  attempts_remaining: number
  budget_remaining_usd: number
  items: ApifyActorCanaryPlanItem[]
  base_pool_hash?: string
  required_success_count?: number
  route_validation_cap_usd?: number
  source_validation_cap_usd?: number
  source_count?: number
  source_validation_count?: number
}

export type ApifyActorCanaryBatchRequest = {
  expected_generation: number
  expected_plan_hash: string
  approval_id: string
  confirmation: '确认付费验证主备'
  goal?: ApifyActorPoolGoal
  max_candidates: number
  max_total_charge_usd: number
  candidate_ids?: string[]
  candidate_validation_profiles?: ApifyActorValidationProfileRequest[]
  target_slot_count?: 2 | 3
}

export type ApifyActorPoolCandidate = {
  candidate_id: string
  actor_public_name: string
  publisher: string
  pricing?: ApifyActorRevisionSummary['pricing']
  max_validation_charge_usd: number
  validation_options?: ApifyActorValidationProfile & {
    timeout_min_seconds: number
    timeout_max_seconds: number
    allowed_sample_items: Array<1 | 3 | 5>
    max_charge_limit_usd: number
  }
  last_failure?: {
    code: string
    duration_seconds: number | null
    dataset_row_count: number | null
    mapped_item_count: number | null
    actual_cost_usd: number | null
    cost_final: boolean
    timeout_seconds: number
    sample_items: 1 | 3 | 5
    max_charge_usd: number
    profile_hash: string
    completed_at: string | null
  } | null
  requires_profile_change?: boolean
  existing_actor_upgrade?: boolean
  selectable: boolean
  unavailable_reason?: string | null
}

export type ApifyActorPoolCandidates = {
  schema_version: 1
  route_id: string
  generation: number
  goal: ApifyActorPoolGoal
  run_id: string | null
  required_selection_count: 1 | 3
  candidates: ApifyActorPoolCandidate[]
  blockers: string[]
}

export type ApifyActorPoolCandidateRefresh = {
  schema_version: 1
  route_id: string
  run_id: string
  status: 'refreshing'
}

export type ApifyActorCanaryBatchItem = ApifyActorCanaryPlanItem & {
  status: string
  semantic_outcome?: string | null
  actual_cost_usd?: number | null
  cost_final: boolean
  preflight_checked_at?: string | null
  started_at?: string | null
  completed_at?: string | null
}

export type ApifyActorCanaryBatch = {
  schema_version: 1 | 2 | 3
  batch_id: string
  route_id: string
  discovery_run_id: string
  approved_generation: number
  plan_hash: string
  max_candidates: number
  max_total_charge_usd: number
  route_validation_cap_usd?: number
  per_candidate_cap_usd: number
  goal?: ApifyActorPoolGoal
  pool_stage_id?: string | null
  pool_stage?: ApifyActorPoolStage | null
  status: string
  planned_count: number
  success_count: number
  publisher_count: number
  actual_cost_usd?: number | null
  cost_final: boolean
  stop_reason?: string | null
  created_at: string
  started_at?: string | null
  completed_at?: string | null
  updated_at: string
  items: ApifyActorCanaryBatchItem[]
}

export type ApifyActorCanaryBatchResponse = {
  schema_version: 1 | 2
  batch: ApifyActorCanaryBatch
  job: { id: string; status: string }
}

export type ApifyActorDiscoveryMetrics = {
  request_max_output_tokens: number | null
  input_tokens: number | null
  completion_tokens: number | null
  reasoning_tokens: number | null
  content_tokens: number | null
  finish_reason: string | null
  latency_ms: number | null
  response_bytes: number | null
  json_status: string | null
  manifest_status: string | null
}

export type ApifyActorSupportCheckRequest = {
  platform: string
  target_type: string
  capability: string
  expected_generation: number
  force_discovery?: boolean
}

export type ApifyActorSupportCheckResponse = {
  schema_version: 1
  kind: 'route' | 'discovery'
  generation: number
  route_generation: number
  route_id?: string | null
  support_status: ApifyActorRouteSupportStatus
  discovery_run_id?: string | null
  job?: {
    id: string
    status: string
  } | null
}

export type ApifyActorActivePoolUpdate = {
  expected_generation: number
  rollback_revision_id?: string
  per_run_cap_usd?: number
  slots: Array<{
    slot: ApifyActorSlotName
    revision_id: string | null
  }>
}

export type ApifyActorRecommendedPoolActivation = {
  expected_generation: number
  confirmation: '确认启用 Actor 主备'
  stage_id?: string
  expected_plan_hash?: string
  apply_id?: string
}

export type ApifyActorPaidCanaryRequest = {
  expected_generation: number
  approval_id: string
  confirmation: '确认付费试跑'
  max_total_charge_usd: number
}

export type ApifyActorPaidCanaryResponse = {
  schema_version: 1
  validation: {
    validation_id: string
    route_id: string
    source_id?: string | null
    revision_id: string
    kind: 'route_reference' | 'source_canary'
    status: string
    semantic_outcome?: string | null
    cost_usd?: number | null
    created_at: string
    completed_at?: string | null
  }
  job: {
    id: string
    status: string
  }
}

export type ApifyActorSourceBindingActivationResponse = {
  schema_version: 1
  source_id: string
  route_id: string
  generation: number
  binding_status: string
}

export type ApifyActorSourceSupport = {
  schema_version: 1 | 2
  source_id: string
  route_id: string | null
  generation: number
  binding_status: string
  verified_revision_set_hash?: string | null
  budget_cap_usd: number
  spent_usd: number
  reserved_usd: number
  remaining_budget_usd: number
  slots: ApifyActorSourceValidationSlot[]
  next_action?: {
    kind: 'upgrade_pool_required' | 'validate_slot' | 'wait' | 'activate_source' | 'complete' | 'refresh'
    slot?: ApifyActorSlotName
    reason?: string
  }
  activation_confirmation?: string | null
}

export type ApifyActorSourceBindingActivation = {
  expected_generation: number
  confirmation: string
}

export type ApifyActorDiscoverySettings = {
  schema_version: 4
  generation: number
  enabled: boolean
  ai_config_id: string
  ai_options: Array<{
    id: string
    label: string
    provider: string
    model: string
    key_name: string | null
    preferred: boolean
    ready: boolean
    unavailable_reason: string | null
  }>
  max_queries_per_run: number
  max_candidates: number
  max_output_tokens: number
  recommended_max_output_tokens: number | null
  measurements: {
    youtube: ApifyActorDiscoveryMeasurement | null
    instagram: ApifyActorDiscoveryMeasurement | null
  }
  updated_at?: string | null
}

export type ApifyActorDiscoveryMeasurement = {
  run_id: string
  route_id: string
  stage: string
  updated_at: string | null
  metrics: ApifyActorDiscoveryMetrics
}

export type ApifyActorDiscoverySettingsPatch = {
  expected_generation: number
  enabled?: boolean
  ai_config_id?: string
  max_queries_per_run?: number
  max_candidates?: number
  max_output_tokens?: number
}

export type ApifyActorDiscoveryMeasurementRequest = {
  expected_generation: number
  confirmation: '确认AI容量测试'
  max_output_tokens: 32768 | 65536
  route_keys: Array<'youtube/channel/items' | 'instagram/profile/items'>
}

export type ApifyActorDiscoveryMeasurementResponse = {
  schema_version: 1
  runs: Array<{ run_id: string; route_id: string; stage: string }>
  jobs: Array<{ id: string; status: string }>
}

export type ApifyActorAlertEvent =
  | 'actor_switched'
  | 'route_exhausted'
  | 'quota_low'
  | 'budget_blocked'
  | 'start_outcome_unknown'
  | 'recovered'

export type ApifyActorAlertSettings = {
  schema_version: 4
  enabled: boolean
  target_ids: string[]
  selected_targets: NotificationTarget[]
  channels: NotificationChannel[]
  channel: NotificationChannel
  channel_states: NotificationChannelStates
  events: ApifyActorAlertEvent[]
  email_configured: boolean
  email_transport_ready: boolean
  webhook_configured: boolean
  webhook_provider: WebhookProvider
  webhook_provider_explicit: boolean
  webhook_signing_secret_configured: boolean
  webhook_verification_mode: 'http_status' | 'provider_response'
  webhook_provider_options: WebhookProviderOption[]
  telegram_configured: boolean
  telegram_transport_ready: boolean
  last_test_status: NotificationChannelTestStatus
  last_tested_at: string | null
  last_test_error_code: string | null
  last_alert_status: string | null
  last_alerted_at: string | null
  last_alert_error_code: string | null
  updated_at: string | null
}

export type ApifyActorAlertSettingsPatch = {
  enabled?: boolean
  target_ids?: string[]
  channels?: NotificationChannel[]
  channel?: NotificationChannel
  events?: ApifyActorAlertEvent[]
  email_address?: string | null
  webhook_url?: string | null
  webhook_provider?: WebhookProvider
  webhook_signing_secret?: string | null
  telegram_chat_id?: string | null
}

export type ApifyActorAlertDeliveryStatus =
  | 'pending'
  | 'sending'
  | 'sent'
  | 'failed'
  | 'unknown'
  | 'partial'
  | 'skipped'
  | null

export type ApifyActorAlertDelivery = {
  event_type: ApifyActorAlertEvent | ''
  channel: NotificationChannel
  target_id: string | null
  target_name: string | null
  status: ApifyActorAlertDeliveryStatus
  error_code: string | null
  created_at: string
  started_at: string | null
  sent_at: string | null
  updated_at: string
}

export type ApifyActorAlertIncident = {
  schema_version: 3
  id: string
  route: 'x/profile'
  event_type: ApifyActorAlertEvent
  severity: 'info' | 'warning' | 'critical'
  status: 'open' | 'resolved'
  actor_name: string | null
  active_actor_name: string | null
  reason_code: string | null
  opened_at: string
  last_seen_at: string
  resolved_at: string | null
  deliveries: ApifyActorAlertDelivery[]
  delivery_status: ApifyActorAlertDeliveryStatus
  delivery_error_code: string | null
}

export type ApifyActorAlertIncidents = {
  schema_version: 3
  incidents: ApifyActorAlertIncident[]
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
