const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'src', 'ui', 'static', 'subscriptions.js'),
  'utf8'
);
const authSource = fs.readFileSync(
  path.join(__dirname, '..', 'src', 'ui', 'static', 'auth.js'),
  'utf8'
);

function loadSubscriptions(fetchImpl) {
  const messageElement = { textContent: '', className: '' };
  const elements = {
    subscriptionMessage: messageElement,
    subscriptionSummary: { textContent: '' },
    subscriptionConsole: { innerHTML: '' },
    refreshMyFeedBtn: { disabled: false, title: '', textContent: '立即刷新' },
    refreshBtn: { disabled: false, title: '', textContent: '获取新内容' },
  };
  const context = {
    console,
    URL,
    HUB_CHANNEL_OPTIONS: ['AI'],
    TAG_LIBRARY_OPTIONS: ['AI Agent'],
    state: {
      auth: { user: { id: 'user-me', username: 'me', role: 'member' } },
      subscriptionConsole: null,
      subscriptionJobSubmission: false,
      subscriptionJobPoll: null,
      sourceHealth: null,
      sourceHealthLoaded: false,
      sourceHealthLoading: false,
      sourceHealthLoadToken: 0,
      sourceHealthLoadUserId: null,
      sourceHealthLoadPromise: null,
      sourceHealthSyncedJobIds: {},
      sourceHealthFilter: '',
      feedActivity: null,
      feedActivityLoaded: false,
      feedActivityLoading: false,
      feedActivityLoadToken: 0,
      feedActivityLoadUserId: null,
    },
    window: {
      clearTimeout() {},
      setTimeout() {
        throw new Error('terminal test unexpectedly scheduled another poll');
      },
    },
    document: {
      getElementById(id) {
        return elements[id] || null;
      },
    },
    fetch: fetchImpl,
    unwrapApiPayload(payload) {
      return payload.data;
    },
    apiErrorMessage(payload, fallback) {
      return (payload.error && payload.error.message) || fallback;
    },
    canUseConfig() {
      return true;
    },
    showLoginGate() {},
    escapeHtml(value) {
      return String(value == null ? '' : value).replace(/[&<>"']/g, (character) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
      })[character]);
    },
    formatDate(value) {
      return value ? `DATE(${value})` : '未知';
    },
    safeExternalUrl(value) {
      try {
        const parsed = new URL(String(value));
        return ['http:', 'https:'].includes(parsed.protocol) && !parsed.username && !parsed.password
          ? parsed.href
          : '';
      } catch (_error) {
        return '';
      }
    },
    setFeedActivity(job, options = {}) {
      if (job && job.job_type === 'user_feed_refresh') {
        context.state.feedActivity = { job, workerStatus: options.workerStatus || 'unknown' };
      }
    },
  };
  vm.createContext(context);
  vm.runInContext(source, context, { filename: 'subscriptions.js' });
  return { context, messageElement, elements };
}

function healthItem(overrides = {}) {
  return {
    subscription_id: 'subscription-health',
    source_id: 'source-health',
    source_display_name: 'Health Source',
    source_type: 'rss',
    status: 'healthy',
    last_attempt_at: '2026-07-11T02:00:00Z',
    last_success_at: '2026-07-11T02:00:00Z',
    last_failure_at: null,
    consecutive_failures: 0,
    last_fetched_count: 3,
    last_issue: null,
    last_job_id: 'job-health',
    ...overrides,
  };
}

function healthPayload(items = [], summary = null) {
  return {
    schema_version: 1,
    scope: 'user',
    summary: summary || {
      total: items.length,
      healthy: items.filter((item) => item.status === 'healthy').length,
      degraded: items.filter((item) => item.status === 'degraded').length,
      failing: items.filter((item) => item.status === 'failing').length,
      unknown: items.filter((item) => item.status === 'unknown').length,
    },
    items,
  };
}

test('owner console loads members from users response without archive quality request', async () => {
  const urls = [];
  const payloads = {
    '/api/dashboard/summary': { marker: 'summary' },
    '/api/catalog/sources': { sources: [{ id: 'source-one' }] },
    '/api/catalog/source-types': { source_types: [{ id: 'rss' }] },
    '/api/me/subscriptions': { subscriptions: [{ id: 'subscription-one' }] },
    '/api/jobs': { jobs: [] },
    '/api/feed/history': { snapshots: [{ id: 'snapshot-one' }] },
    '/api/me/feed-schedule': {
      schema_version: 1,
      enabled: true,
      interval_minutes: 360,
      allowed_intervals: [60, 180, 360, 720, 1440],
      active_job: null,
      last_job: null,
      worker_status: 'ready',
    },
    '/api/me/source-health': {
      schema_version: 1,
      scope: 'user',
      summary: { total: 5, healthy: 2, degraded: 1, failing: 1, unknown: 1 },
      items: [],
    },
    '/api/users': { users: [{ id: 'user-owner', username: 'owner' }] },
    '/api/admin/secrets': { secrets: [{ id: 'secret-apify', kind: 'apify', provider: 'apify', name: 'Apify Primary', env_name: 'APIFY_TOKEN', is_set: true }] },
  };
  const fetchImpl = async (url) => {
    const pathname = String(url).split('?')[0];
    urls.push(pathname);
    return {
      ok: true,
      status: 200,
      async json() {
        return { ok: true, data: payloads[pathname] || { sources: [{ id: 'quality-decoy' }] } };
      },
    };
  };
  const { context, elements } = loadSubscriptions(fetchImpl);
  context.state.auth.user.role = 'owner';
  context.resumeActiveFeedJobPoll = () => {};

  await context.loadSubscriptionConsole();

  assert.deepEqual(urls, [
    '/api/dashboard/summary',
    '/api/catalog/sources',
    '/api/catalog/source-types',
    '/api/me/subscriptions',
    '/api/jobs',
    '/api/feed/history',
    '/api/me/feed-schedule',
    '/api/me/source-health',
    '/api/users',
    '/api/admin/secrets',
  ]);
  assert.equal(context.state.feedSchedule.enabled, true);
  assert.equal(context.state.sourceHealth.summary.total, 5);
  assert.equal(context.state.subscriptionConsole.members.length, 1);
  assert.equal(context.state.subscriptionConsole.members[0].id, 'user-owner');
  assert.equal(context.state.secrets[0].id, 'secret-apify');
  assert.match(elements.subscriptionConsole.innerHTML, /来源健康/);
  assert.match(elements.subscriptionConsole.innerHTML, /总计[^<]*<\/span><strong>5<\/strong>/);
  assert.match(elements.subscriptionConsole.innerHTML, /正常[^<]*<\/span><strong>2<\/strong>/);
  assert.match(elements.subscriptionConsole.innerHTML, /需关注[^<]*<\/span><strong>1<\/strong>/);
  assert.match(elements.subscriptionConsole.innerHTML, /连续失败[^<]*<\/span><strong>1<\/strong>/);
  assert.match(elements.subscriptionConsole.innerHTML, /尚未抓取[^<]*<\/span><strong>1<\/strong>/);
  assert.equal(Object.hasOwn(context.state.subscriptionConsole.apiStatus, 'sourceQuality'), false);
});

test('member console survives a failed source-health read without shifting result indexes', async () => {
  const urls = [];
  const payloads = {
    '/api/dashboard/summary': { current_user: { id: 'user-me', username: 'me', role: 'member' } },
    '/api/catalog/sources': { sources: [] },
    '/api/catalog/source-types': { source_types: [{ type: 'rss', label: 'RSS' }] },
    '/api/me/subscriptions': { subscriptions: [{ id: 'subscription-member' }] },
    '/api/jobs': { jobs: [] },
    '/api/feed/history': { snapshots: [{ id: 'snapshot-member' }] },
    '/api/me/feed-schedule': {
      schema_version: 1,
      enabled: false,
      interval_minutes: 360,
      allowed_intervals: [60, 180, 360, 720, 1440],
      active_job: null,
      last_job: null,
      worker_status: 'ready',
    },
  };
  const { context, messageElement } = loadSubscriptions(async (url) => {
    const pathname = String(url).split('?')[0];
    urls.push(pathname);
    if (pathname === '/api/me/source-health') {
      return {
        ok: false,
        status: 503,
        async json() {
          return { ok: false, error: { code: 'health_unavailable', message: 'health unavailable' } };
        },
      };
    }
    return {
      ok: true,
      status: 200,
      async json() { return { ok: true, data: payloads[pathname] }; },
    };
  });
  context.resumeActiveFeedJobPoll = () => {};

  await context.loadSubscriptionConsole();

  assert.deepEqual(urls, [
    '/api/dashboard/summary',
    '/api/catalog/sources',
    '/api/catalog/source-types',
    '/api/me/subscriptions',
    '/api/jobs',
    '/api/feed/history',
    '/api/me/feed-schedule',
    '/api/me/source-health',
  ]);
  assert.equal(context.state.subscriptionConsoleLoaded, true);
  assert.equal(context.state.subscriptionConsole.subscriptions[0].id, 'subscription-member');
  assert.equal(context.state.subscriptionConsole.feedSchedule.interval_minutes, 360);
  assert.equal(context.state.subscriptionConsole.members.length, 0);
  assert.match(messageElement.textContent, /来源健康.*读取失败|来源健康.*health unavailable/);
});

test('health summary and personal cards render exact states, diagnostics, and subscribed-only retry controls', () => {
  const { context, elements } = loadSubscriptions(async () => { throw new Error('unexpected fetch'); });
  const subscriptions = [
    {
      id: 'subscription-healthy',
      source_id: 'source-healthy',
      source_display_name: 'Healthy Zero',
      source_type: 'rss',
      enabled: true,
      override_topics: [],
    },
    {
      id: 'subscription-degraded',
      source_id: 'source-degraded',
      source_display_name: 'Disabled but retained',
      source_type: 'reddit',
      enabled: false,
      override_topics: [],
    },
    {
      id: 'subscription-failing',
      source_id: 'source-failing',
      source_display_name: 'Failing Source',
      source_type: 'github_release',
      enabled: true,
      override_topics: [],
    },
    {
      id: 'subscription-unknown',
      source_id: 'source-unknown',
      source_display_name: 'Unknown Source',
      source_type: 'telegram',
      enabled: true,
      override_topics: [],
    },
  ];
  const items = [
    healthItem({
      subscription_id: 'subscription-healthy',
      source_id: 'source-healthy',
      source_display_name: 'Healthy Zero',
      status: 'healthy',
      last_fetched_count: 0,
    }),
    healthItem({
      subscription_id: 'subscription-degraded',
      source_id: 'source-degraded',
      source_display_name: 'Disabled but retained',
      status: 'degraded',
      last_success_at: '2026-07-10T01:00:00Z',
      last_failure_at: '2026-07-11T02:00:00Z',
      consecutive_failures: 1,
      last_fetched_count: 4,
      last_issue: {
        stage: 'fetch',
        code: 'HTTPError',
        message: 'upstream returned 503',
        retryable: true,
      },
    }),
    healthItem({
      subscription_id: 'subscription-failing',
      source_id: 'source-failing',
      source_display_name: 'Failing Source',
      status: 'failing',
      last_success_at: null,
      last_failure_at: '2026-07-11T02:00:00Z',
      consecutive_failures: 3,
      last_fetched_count: 0,
      last_issue: {
        stage: 'normalize',
        code: 'InvalidPayload',
        message: 'payload has no items',
        retryable: false,
      },
    }),
    healthItem({
      subscription_id: 'subscription-unknown',
      source_id: 'source-unknown',
      source_display_name: 'Unknown Source',
      status: 'unknown',
      last_attempt_at: null,
      last_success_at: null,
      last_failure_at: null,
      last_fetched_count: 0,
      last_job_id: null,
    }),
  ];
  const sourceHealth = healthPayload(items, {
    total: 4,
    healthy: 1,
    degraded: 1,
    failing: 1,
    unknown: 1,
  });

  context.renderSubscriptionConsole({
    summary: {},
    sources: [
      { id: 'source-healthy', type: 'rss', scope: 'public', display_name: 'Healthy Zero' },
      { id: 'source-market', type: 'rss', scope: 'public', display_name: 'Marketplace Only' },
    ],
    sourceTypes: [],
    subscriptions,
    jobs: [],
    feedSchedule: {},
    members: [],
    apiStatus: {},
    sourceHealth,
  });

  const html = elements.subscriptionConsole.innerHTML;
  assert.match(html, /来源健康/);
  assert.match(html, /总计[^<]*<\/span><strong>4<\/strong>/);
  assert.match(html, /正常[^<]*<\/span><strong>1<\/strong>/);
  assert.match(html, /需关注[^<]*<\/span><strong>1<\/strong>/);
  assert.match(html, /连续失败[^<]*<\/span><strong>1<\/strong>/);
  assert.match(html, /尚未抓取[^<]*<\/span><strong>1<\/strong>/);
  assert.match(html, /Healthy Zero[\s\S]*?正常/);
  assert.match(html, /Healthy Zero[\s\S]*?上次尝试[^]*?DATE\(2026-07-11T02:00:00Z\)/);
  assert.match(html, /Healthy Zero[\s\S]*?抓取条数[^]*?>0 条</);
  assert.match(html, /Disabled but retained[\s\S]*?停用[\s\S]*?需关注/);
  assert.match(html, /HTTPError/);
  assert.match(html, /upstream returned 503/);
  assert.match(html, /可重试/);
  assert.match(html, /InvalidPayload/);
  assert.match(html, /payload has no items/);
  assert.match(html, /不可重试/);
  assert.match(html, /尚未抓取/);
  assert.match(html, /data-source-fetch="source-healthy"[^>]*data-subscription-id="subscription-healthy"[^>]*>重新抓取<\/button>/);

  const marketplaceNameIndex = html.indexOf('<h4>Marketplace Only</h4>');
  assert.ok(marketplaceNameIndex >= 0);
  const marketplaceStart = html.lastIndexOf('<article', marketplaceNameIndex);
  const marketplaceEnd = html.indexOf('</article>', marketplaceNameIndex);
  const marketplaceCard = html.slice(marketplaceStart, marketplaceEnd + '</article>'.length);
  assert.match(marketplaceCard, />抓取<\/button>/);
  assert.doesNotMatch(marketplaceCard, /重新抓取|正常|需关注|连续失败|尚未抓取|上次成功|抓取条数|HTTPError/);
});

test('viewer sees health diagnostics but refetch stays disabled and programmatic queue is guarded', async () => {
  let fetchCalls = 0;
  const { context } = loadSubscriptions(async () => {
    fetchCalls += 1;
    throw new Error('viewer must not submit');
  });
  context.state.auth.user.role = 'viewer';
  const html = context.renderSubscriptionCard({
    id: 'subscription-viewer',
    source_id: 'source-viewer',
    source_display_name: 'Viewer Source',
    source_type: 'rss',
    enabled: true,
    override_topics: [],
  }, healthItem({
    subscription_id: 'subscription-viewer',
    source_id: 'source-viewer',
    status: 'degraded',
    last_issue: { stage: 'fetch', code: 'TimeoutError', message: 'timed out', retryable: true },
  }));

  assert.match(html, /需关注/);
  assert.match(html, /TimeoutError/);
  assert.match(html, /data-source-fetch="source-viewer"[^>]*disabled[^>]*>重新抓取<\/button>/);
  await context.queueSourceJob('source-viewer', 'source_fetch', 'subscription-viewer');
  assert.equal(fetchCalls, 0);
});

test('source display name and issue code/message are HTML escaped and the message is shortened', () => {
  const { context } = loadSubscriptions(async () => { throw new Error('unexpected fetch'); });
  const longMessage = '<script>alert("health")</script> ' + 'x'.repeat(240);
  const html = context.renderSubscriptionCard({
    id: 'subscription-escape',
    source_id: 'source-escape',
    source_display_name: '<img src=x onerror=alert(1)>',
    source_type: 'rss',
    enabled: true,
    override_topics: [],
  }, healthItem({
    subscription_id: 'subscription-escape',
    source_id: 'source-escape',
    status: 'failing',
    last_issue: {
      stage: 'fetch',
      code: '<Timeout&Error>',
      message: longMessage,
      retryable: true,
    },
  }));

  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.match(html, /&lt;Timeout&amp;Error&gt;/);
  assert.match(html, /&lt;script&gt;alert\(&quot;health&quot;\)&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<img src=x|<script>/);
  assert.doesNotMatch(html, new RegExp('x'.repeat(180)));
  assert.match(html, /\.\.\./);
});

test('canonical source type fields render all eight editors with immutable types and advanced JSON fallback', () => {
  const { context } = loadSubscriptions(async () => { throw new Error('unexpected fetch'); });
  const types = [
    ['rss', { name: 'url', label: 'RSS URL', input_type: 'url', required: true, default: '', help: 'Feed address' }],
    ['github_release', { name: 'owner', label: 'Owner', input_type: 'text', required: true, default: '' }],
    ['github_user', { name: 'username', label: 'Username', input_type: 'text', required: true, default: '' }],
    ['reddit_subreddit', { name: 'subreddit', label: 'Subreddit', input_type: 'text', required: true, default: '' }],
    ['reddit_user', { name: 'username', label: 'Username', input_type: 'text', required: true, default: '' }],
    ['telegram_channel', { name: 'channel', label: 'Channel', input_type: 'text', required: true, default: '' }],
    ['apify_social', { name: 'platform', label: 'Platform', input_type: 'select', required: true, default: 'x', options: ['x', 'instagram'] }],
    ['hackernews', { name: 'fetch_top_stories', label: 'Top stories', input_type: 'number', required: false, default: 30, min: 1, max: 100 }],
  ].map(([type, field]) => ({ type, label: type, fields: [field], template: {} }));

  for (const definition of types) {
    const field = definition.fields[0];
    const html = context.renderSourceEditor({
      id: `source-${definition.type}`,
      type: definition.type,
      scope: 'private',
      owner_user_id: 'user-me',
      display_name: definition.type,
      config: { [field.name]: field.default },
      default_topics: [],
      enabled: true,
    }, types, null);
    assert.match(html, new RegExp(`name="source_type" value="${definition.type}"[^>]*(?:disabled|readonly)`));
    assert.match(html, new RegExp(`name="config\\.${field.name}"`));
    assert.match(html, /<details[^>]*class="source-editor-advanced"/);
    assert.match(html, /<summary>高级 JSON<\/summary>/);
  }
  const rssHtml = context.renderSourceEditor({
    id: 'source-rss', type: 'rss', scope: 'private', owner_user_id: 'user-me',
    display_name: 'RSS', config: { url: 'https://example.com/feed.xml' }, default_topics: [], enabled: true,
  }, types, null);
  assert.match(rssHtml, /Feed address/);
  assert.match(rssHtml, /name="config\.url"[^>]*required/);
  const apifyHtml = context.renderSourceEditor({
    id: 'source-apify', type: 'apify_social', scope: 'private', owner_user_id: 'user-me',
    display_name: 'Apify', config: { platform: 'instagram' }, default_topics: [], enabled: true,
  }, types, null);
  assert.match(apifyHtml, /<option value="instagram" selected>/);
  const createHtml = context.renderAdvancedSourceForm(types);
  assert.match(createHtml, /data-advanced-source-fields="rss"/);
  assert.match(createHtml, /name="config\.url"/);
  assert.match(createHtml, /<details[^>]*class="source-editor-advanced(?: wide)?"/);
  assert.match(createHtml, /<summary>高级 JSON<\/summary>/);

  assert.equal(context.sourceCanEdit({ scope: 'private', owner_user_id: 'user-me' }), true);
  assert.equal(context.sourceCanEdit({ scope: 'public', owner_user_id: 'user-other' }), false);
  context.state.auth.user.role = 'admin';
  assert.equal(context.sourceCanEdit({ scope: 'public', owner_user_id: 'user-other' }), true);
  assert.equal(context.sourceCanEdit({ scope: 'private', owner_user_id: 'user-other' }), false);
  context.state.auth.user.role = 'viewer';
  assert.equal(context.sourceCanEdit({ scope: 'public', owner_user_id: 'user-me' }), false);
  assert.equal(context.renderSubscriptionEditor({ id: 'subscription-viewer', source_id: 'source-viewer' }), '');
});

test('source editor payload clears optional fields and save test refetch actions preserve request order', async () => {
  const requests = [];
  const queued = [];
  const { context } = loadSubscriptions(async () => { throw new Error('unexpected raw fetch'); });
  context.fetchSubscriptionApi = async (url, options) => {
    requests.push({ url, options, body: options && options.body ? JSON.parse(options.body) : null });
    return { id: 'source-edit', type: 'rss' };
  };
  context.queueSourceJob = async (sourceId, kind, subscriptionId) => {
    queued.push({ sourceId, kind, subscriptionId });
  };
  context.loadSubscriptionConsole = async () => {};
  const definition = {
    type: 'rss',
    fields: [
      { name: 'url', label: 'URL', input_type: 'url', required: true, default: '' },
      { name: 'optional', label: 'Optional', input_type: 'text', required: false, default: null },
      { name: 'tags', label: 'Tags', input_type: 'list', required: false, default: [] },
    ],
  };
  const elements = {
    display_name: { value: 'Edited RSS' },
    description: { value: '' },
    default_channel: { value: '' },
    default_topics: { value: '' },
    secret_env: { value: '' },
    enabled: { checked: true },
    config_json: { value: '{"legacy":"kept"}' },
    'config.url': { value: 'https://example.com/edited.xml' },
    'config.optional': { value: '' },
    'config.tags': { value: '' },
  };
  const form = {
    elements,
    getAttribute(name) {
      return { 'data-source-editor': 'source-edit', 'data-source-type': 'rss', 'data-subscription-id': 'subscription-edit' }[name] || '';
    },
  };

  const payload = context.sourceEditorPayload(form, definition);
  assert.deepEqual(JSON.parse(JSON.stringify(payload)), {
    display_name: 'Edited RSS',
    description: null,
    default_channel: null,
    default_topics: [],
    config: {
      legacy: 'kept',
      url: 'https://example.com/edited.xml',
      optional: null,
      tags: [],
    },
    secret_env: null,
    enabled: true,
  });

  await context.saveSourceEditor(form, 'save', definition);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/api/catalog/sources/source-edit');
  assert.equal(requests[0].options.method, 'PATCH');
  assert.equal(queued.length, 0);

  await context.saveSourceEditor(form, 'test', definition);
  await context.saveSourceEditor(form, 'refetch', definition);
  assert.deepEqual(queued, [
    { sourceId: 'source-edit', kind: 'source_test', subscriptionId: 'subscription-edit' },
    { sourceId: 'source-edit', kind: 'source_fetch', subscriptionId: 'subscription-edit' },
  ]);
  assert.equal(requests.length, 3);
});

test('source editor stops after a delayed owner response crosses into another user', async () => {
  let resolvePatch;
  const pendingPatch = new Promise((resolve) => { resolvePatch = resolve; });
  const queued = [];
  let consoleLoads = 0;
  const { context, messageElement } = loadSubscriptions(async () => {
    throw new Error('unexpected raw fetch');
  });
  context.fetchSubscriptionApi = async () => pendingPatch;
  context.queueSourceJob = async (...args) => { queued.push(args); };
  context.loadSubscriptionConsole = async () => { consoleLoads += 1; };
  const form = {
    elements: {
      display_name: { value: 'A source' },
      description: { value: '' },
      default_channel: { value: '' },
      default_topics: { value: '' },
      secret_env: { value: '' },
      enabled: { checked: true },
      config_json: { value: '{}' },
      'config.url': { value: 'https://a.example/feed.xml' },
    },
    getAttribute(name) {
      return {
        'data-source-editor': 'source-a',
        'data-source-type': 'rss',
        'data-subscription-id': 'subscription-a',
      }[name] || '';
    },
  };
  const definition = {
    type: 'rss',
    fields: [{ name: 'url', label: 'URL', input_type: 'url', required: true, default: '' }],
  };

  const saving = context.saveSourceEditor(form, 'test', definition);
  await new Promise((resolve) => setImmediate(resolve));
  context.state.auth.user = { id: 'user-b', role: 'member' };
  context.state.subscriptionConsoleLoaded = true;
  messageElement.textContent = 'B message';
  resolvePatch({ id: 'source-a' });
  const result = await saving;

  assert.equal(result, false);
  assert.deepEqual(queued, []);
  assert.equal(consoleLoads, 0);
  assert.equal(context.state.subscriptionConsoleLoaded, true);
  assert.equal(messageElement.textContent, 'B message');
});

test('subscription editor sends explicit clears and save alone never queues a job', async () => {
  const requests = [];
  const queued = [];
  const { context } = loadSubscriptions(async () => { throw new Error('unexpected raw fetch'); });
  context.fetchSubscriptionApi = async (url, options) => {
    requests.push({ url, options, body: JSON.parse(options.body) });
    return { id: 'subscription-edit' };
  };
  context.queueSourceJob = async (sourceId, kind, subscriptionId) => queued.push({ sourceId, kind, subscriptionId });
  context.loadSubscriptionConsole = async () => {};
  const form = {
    elements: {
      override_channel: { value: '' },
      override_topics: { value: '' },
      personal_tags: { value: '' },
      analysis_mode: { value: 'personal_only' },
      priority: { value: '100' },
      enabled: { checked: false },
    },
    getAttribute(name) {
      return { 'data-subscription-editor': 'subscription-edit', 'data-source-id': 'source-edit' }[name] || '';
    },
  };

  assert.deepEqual(JSON.parse(JSON.stringify(context.subscriptionEditorPayload(form))), {
    override_channel: null,
    override_topics: [],
    personal_tags: [],
    analysis_mode: 'personal_only',
    priority: 100,
    enabled: false,
  });
  await context.saveSubscriptionEditor(form, 'save');
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/api/me/subscriptions/subscription-edit');
  assert.equal(queued.length, 0);
  await context.saveSubscriptionEditor(form, 'test');
  await context.saveSubscriptionEditor(form, 'refetch');
  assert.deepEqual(queued, [
    { sourceId: 'source-edit', kind: 'source_test', subscriptionId: 'subscription-edit' },
    { sourceId: 'source-edit', kind: 'source_fetch', subscriptionId: 'subscription-edit' },
  ]);
});

test('subscription editor renders and saves a per-source automatic fetch schedule', async () => {
  const requests = [];
  const { context } = loadSubscriptions(async () => { throw new Error('unexpected raw fetch'); });
  const html = context.renderSubscriptionEditor({
    id: 'subscription-x',
    source_id: 'source-x',
    enabled: true,
    override_topics: [],
    personal_tags: [],
    analysis_mode: 'full',
    priority: 50,
    schedule: {
      enabled: true,
      interval_minutes: 30,
      allowed_intervals: [30, 60, 180, 360, 720, 1440],
    },
  });
  assert.match(html, /name="source_schedule_enabled"[^>]*checked/);
  assert.match(html, /name="source_schedule_interval_minutes"/);
  assert.match(html, /<option value="30" selected>30 分钟<\/option>/);

  context.fetchSubscriptionApi = async (url, options) => {
    requests.push({ url, body: JSON.parse(options.body) });
    return {};
  };
  context.loadSubscriptionConsole = async () => {};
  const form = {
    elements: {
      override_channel: { value: '' },
      override_topics: { value: '' },
      personal_tags: { value: '' },
      analysis_mode: { value: 'full' },
      priority: { value: '50' },
      enabled: { checked: true },
      source_schedule_enabled: { checked: true },
      source_schedule_interval_minutes: { value: '30' },
    },
    getAttribute(name) {
      return {
        'data-subscription-editor': 'subscription-x',
        'data-source-id': 'source-x',
      }[name] || '';
    },
  };

  await context.saveSubscriptionEditor(form, 'save');

  assert.deepEqual(requests, [
    {
      url: '/api/me/subscriptions/subscription-x',
      body: {
        override_channel: null,
        override_topics: [],
        personal_tags: [],
        analysis_mode: 'full',
        priority: 50,
        enabled: true,
      },
    },
    {
      url: '/api/me/subscriptions/subscription-x/schedule',
      body: { enabled: true, interval_minutes: 30 },
    },
  ]);
});

test('subscription editor stops after a delayed patch response crosses into another user', async () => {
  let resolvePatch;
  const pendingPatch = new Promise((resolve) => { resolvePatch = resolve; });
  const queued = [];
  let consoleLoads = 0;
  const { context, messageElement } = loadSubscriptions(async () => {
    throw new Error('unexpected raw fetch');
  });
  context.fetchSubscriptionApi = async () => pendingPatch;
  context.queueSourceJob = async (...args) => { queued.push(args); };
  context.loadSubscriptionConsole = async () => { consoleLoads += 1; };
  const form = {
    elements: {
      override_channel: { value: '' },
      override_topics: { value: '' },
      personal_tags: { value: '' },
      analysis_mode: { value: 'full' },
      priority: { value: '5' },
      enabled: { checked: true },
    },
    getAttribute(name) {
      return {
        'data-subscription-editor': 'subscription-a',
        'data-source-id': 'source-a',
      }[name] || '';
    },
  };

  const saving = context.saveSubscriptionEditor(form, 'refetch');
  await new Promise((resolve) => setImmediate(resolve));
  context.state.auth.user = { id: 'user-b', role: 'member' };
  context.state.subscriptionConsoleLoaded = true;
  messageElement.textContent = 'B message';
  resolvePatch({ id: 'subscription-a' });
  const result = await saving;

  assert.equal(result, false);
  assert.deepEqual(queued, []);
  assert.equal(consoleLoads, 0);
  assert.equal(context.state.subscriptionConsoleLoaded, true);
  assert.equal(messageElement.textContent, 'B message');
});

test('source job submission cannot poll or release another user controls after a delayed response', async () => {
  let resolvePost;
  const pendingPost = new Promise((resolve) => { resolvePost = resolve; });
  const polls = [];
  let previewLoads = 0;
  const { context, messageElement } = loadSubscriptions(async () => {
    throw new Error('unexpected raw fetch');
  });
  context.fetchSubscriptionApi = async () => pendingPost;
  context.pollJobUntilTerminal = (...args) => { polls.push(args); };
  context.loadJobsPreview = async () => { previewLoads += 1; };

  const submitting = context.queueSourceJob('source-a', 'source_test', 'subscription-a');
  await new Promise((resolve) => setImmediate(resolve));
  context.state.auth.user = { id: 'user-b', role: 'member' };
  const userBSubmission = { jobType: 'user_feed_refresh', owner: 'user-b' };
  context.state.subscriptionJobSubmission = userBSubmission;
  messageElement.textContent = 'B message';
  resolvePost({
    id: 'job-a',
    user_id: 'user-a',
    job_type: 'source_test',
    status: 'queued',
  });
  await submitting;

  assert.deepEqual(polls, []);
  assert.equal(previewLoads, 0);
  assert.strictEqual(context.state.subscriptionJobSubmission, userBSubmission);
  assert.equal(messageElement.textContent, 'B message');
});

test('successful source test rows show escaped sample details and only safe external links', () => {
  const { context } = loadSubscriptions(async () => { throw new Error('unexpected fetch'); });
  const safeHtml = context.renderJobs([{
    id: 'job-test-safe',
    job_type: 'source_test',
    status: 'succeeded',
    attempts: 1,
    max_attempts: 3,
    result_json: {
      count: 2,
      sample_title: '<Sample title>',
      sample_url: 'https://example.com/sample?id=1',
      message: 'RSS <ready>',
    },
  }]);
  assert.match(safeHtml, /预览 2 条/);
  assert.match(safeHtml, /&lt;Sample title&gt;/);
  assert.match(safeHtml, /href="https:\/\/example\.com\/sample\?id=1"[^>]*target="_blank"[^>]*rel="noopener noreferrer"/);
  assert.match(safeHtml, /RSS &lt;ready&gt;/);

  const unsafeHtml = context.renderJobs([{
    id: 'job-test-unsafe',
    job_type: 'source_test',
    status: 'succeeded',
    result_json: { count: 1, sample_title: 'Unsafe', sample_url: 'javascript:alert(1)', message: 'done' },
  }]);
  assert.doesNotMatch(unsafeHtml, /javascript:|href=/);
});

test('health metrics filter cards and attention cards expose edit test refetch and recent job actions', () => {
  const { context, elements } = loadSubscriptions(async () => { throw new Error('unexpected fetch'); });
  const subscriptions = [
    { id: 'sub-h', source_id: 'src-h', source_display_name: 'Healthy', source_type: 'rss', enabled: true, override_topics: [] },
    { id: 'sub-d', source_id: 'src-d', source_display_name: 'Degraded', source_type: 'rss', enabled: true, override_topics: [] },
    { id: 'sub-f', source_id: 'src-f', source_display_name: 'Failing', source_type: 'rss', enabled: true, override_topics: [] },
    { id: 'sub-u', source_id: 'src-u', source_display_name: 'Unknown', source_type: 'rss', enabled: true, override_topics: [] },
  ];
  const sourceHealth = healthPayload([
    healthItem({ subscription_id: 'sub-h', source_id: 'src-h', status: 'healthy', last_job_id: 'job-h' }),
    healthItem({ subscription_id: 'sub-d', source_id: 'src-d', status: 'degraded', last_job_id: 'job-d' }),
    healthItem({ subscription_id: 'sub-f', source_id: 'src-f', status: 'failing', last_job_id: 'job-f' }),
    healthItem({ subscription_id: 'sub-u', source_id: 'src-u', status: 'unknown', last_job_id: null }),
  ]);
  const summaryHtml = context.renderSourceHealthSummary(sourceHealth);
  for (const filter of ['', 'healthy', 'degraded', 'failing', 'unknown']) {
    assert.match(summaryHtml, new RegExp(`data-source-health-filter="${filter}"`));
  }

  context.state.sourceHealthFilter = 'attention';
  context.renderSubscriptionConsole({
    summary: {}, sources: [], sourceTypes: [], subscriptions, jobs: [], feedSchedule: {}, members: [], apiStatus: {}, sourceHealth,
  });
  const html = elements.subscriptionConsole.innerHTML;
  assert.doesNotMatch(html, /<h4>Healthy<\/h4>|<h4>Unknown<\/h4>/);
  assert.match(html, /<h4>Degraded<\/h4>/);
  assert.match(html, /<h4>Failing<\/h4>/);
  assert.match(html, /data-subscription-editor="sub-f"/);
  assert.match(html, /data-source-test="src-f"/);
  assert.match(html, /data-source-fetch="src-f"/);
  assert.match(html, /data-health-job="job-f"/);
});

test('recent health job lookup treats server job ids as data instead of selector syntax', async () => {
  const { context, messageElement } = loadSubscriptions(async () => {
    throw new Error('existing job must not fetch');
  });
  const jobId = 'job\"] body [data-secret="leak';
  let unsafeSelector = '';
  let scrolled = false;
  const row = {
    getAttribute(name) {
      return name === 'data-job-id' ? jobId : null;
    },
    scrollIntoView() {
      scrolled = true;
    },
  };
  context.state.subscriptionConsole = {
    jobs: [{ id: jobId, job_type: 'source_fetch', status: 'failed' }],
  };
  context.renderSubscriptionConsole = () => {};
  context.document.querySelector = (selector) => {
    unsafeSelector = selector;
    return null;
  };
  context.document.querySelectorAll = () => [row];
  context.window.setTimeout = (callback) => callback();

  await context.showHealthJob(jobId);

  assert.equal(unsafeSelector, '');
  assert.equal(scrolled, true);
  assert.match(messageElement.textContent, /已定位最近任务/);
});

test('cached recent health job outside the first eight is promoted before rendering', async () => {
  const { context } = loadSubscriptions(async () => {
    throw new Error('cached job must not fetch');
  });
  const jobs = Array.from({ length: 10 }, (_, index) => ({
    id: `job-${index}`,
    job_type: 'source_fetch',
    status: index === 9 ? 'failed' : 'succeeded',
  }));
  context.state.subscriptionConsole = { jobs };
  let renderedHtml = '';
  context.renderSubscriptionConsole = (data) => {
    renderedHtml = context.renderJobs(data.jobs);
  };
  context.window.setTimeout = () => {};

  await context.showHealthJob('job-9');

  assert.equal(context.state.subscriptionConsole.jobs[0].id, 'job-9');
  assert.match(renderedHtml, /data-job-id="job-9"/);
});

test('delayed recent health job response cannot replace another user console', async () => {
  let resolveJob;
  const pendingJob = new Promise((resolve) => { resolveJob = resolve; });
  const { context, messageElement } = loadSubscriptions(async () => {
    throw new Error('unexpected raw fetch');
  });
  context.fetchSubscriptionApi = async () => pendingJob;
  context.state.subscriptionConsole = { jobs: [], marker: 'user-a' };
  const rendered = [];
  context.renderSubscriptionConsole = (data) => { rendered.push(data.marker); };
  context.window.setTimeout = () => {};

  const locating = context.showHealthJob('job-a');
  await new Promise((resolve) => setImmediate(resolve));
  context.state.auth.user = { id: 'user-b', role: 'member' };
  const userBConsole = { jobs: [{ id: 'job-b' }], marker: 'user-b' };
  context.state.subscriptionConsole = userBConsole;
  messageElement.textContent = 'B message';
  resolveJob({ id: 'job-a', user_id: 'user-a', job_type: 'source_fetch', status: 'failed' });
  await locating;

  assert.strictEqual(context.state.subscriptionConsole, userBConsole);
  assert.deepEqual(rendered, []);
  assert.equal(messageElement.textContent, 'B message');
});

test('activity restore selects only the current user latest refresh and ignores an old-user response', async () => {
  let resolveOld;
  const oldResponse = new Promise((resolve) => { resolveOld = resolve; });
  let call = 0;
  const { context } = loadSubscriptions(async (url) => {
    assert.match(String(url), /^\/api\/jobs\?limit=20/);
    call += 1;
    if (call === 1) return oldResponse;
    return {
      ok: true,
      status: 200,
      async json() {
        return { ok: true, data: { jobs: [
          { id: 'job-other-newer', user_id: 'user-other', job_type: 'user_feed_refresh', status: 'succeeded', created_at: '2026-07-12T12:00:00Z' },
          { id: 'job-current', user_id: 'user-new', job_type: 'user_feed_refresh', status: 'running', created_at: '2026-07-12T11:00:00Z' },
        ] } };
      },
    };
  });
  context.state.auth.user = { id: 'user-old', role: 'admin' };
  const oldLoad = context.loadFeedActivity({ render: false });
  await new Promise((resolve) => setImmediate(resolve));
  context.state.auth.user = { id: 'user-new', role: 'admin' };
  const newLoad = context.loadFeedActivity({ render: false });
  await newLoad;
  resolveOld({
    ok: true,
    status: 200,
    async json() {
      return { ok: true, data: { jobs: [
        { id: 'job-old', user_id: 'user-old', job_type: 'user_feed_refresh', status: 'failed', created_at: '2026-07-12T13:00:00Z' },
      ] } };
    },
  });
  await oldLoad;

  assert.equal(context.state.feedActivity.job.id, 'job-current');
  assert.equal(context.state.feedActivityLoadUserId, 'user-new');
});

test('activity restore keeps the current user schedule job when more than twenty workspace jobs belong to others', async () => {
  const otherJobs = Array.from({ length: 25 }, (_, index) => ({
    id: `job-other-${index}`,
    user_id: `user-other-${index}`,
    job_type: 'user_feed_refresh',
    status: 'succeeded',
    updated_at: `2026-07-12T12:${String(index).padStart(2, '0')}:00Z`,
  }));
  const { context } = loadSubscriptions(async (url) => {
    assert.match(String(url), /^\/api\/jobs\?limit=20/);
    return {
      ok: true,
      status: 200,
      async json() { return { ok: true, data: { jobs: otherJobs } }; },
    };
  });
  context.state.feedSchedule = {
    worker_status: 'ready',
    active_job: {
      id: 'job-current-schedule',
      user_id: 'user-me',
      job_type: 'user_feed_refresh',
      status: 'running',
      updated_at: '2026-07-12T11:00:00Z',
    },
    last_job: {
      id: 'job-current-last',
      user_id: 'user-me',
      job_type: 'user_feed_refresh',
      status: 'succeeded',
      updated_at: '2026-07-12T10:00:00Z',
    },
  };
  context.state.data = {
    snapshot_id: 'snapshot-current',
    generated_at: '2026-07-12T09:00:00Z',
    item_count: 4,
  };

  await context.loadFeedActivity({ render: false });

  assert.equal(context.state.feedActivity.job.id, 'job-current-schedule');
  assert.equal(context.state.feedActivity.job.status, 'running');
});

test('manual feed refresh posts once, reports deduplication, and disables both entry points', async () => {
  let resolvePost;
  const requests = [];
  const postResponse = new Promise((resolve) => {
    resolvePost = resolve;
  });
  const fetchImpl = async (url, options = {}) => {
    requests.push({ url: String(url), options });
    if (options.method === 'POST') return postResponse;
    throw new Error(`unexpected request: ${url}`);
  };
  const { context, messageElement, elements } = loadSubscriptions(fetchImpl);
  context.loadJobsPreview = async () => {};
  let polledJob = null;
  context.pollJobUntilTerminal = (jobId, jobType) => {
    polledJob = { jobId, jobType };
    context.setSubscriptionJobPoll(jobId, jobType, Date.now());
    return new Promise(() => {});
  };

  const refreshPromise = context.refreshMyFeed();

  assert.equal(elements.refreshBtn.disabled, true);
  assert.equal(elements.refreshMyFeedBtn.disabled, true);
  resolvePost({
    ok: true,
    status: 200,
    async json() {
      return {
        ok: true,
        data: {
          id: 'job-existing',
          job_type: 'user_feed_refresh',
          status: 'running',
          deduplicated: true,
        },
      };
    },
  });
  await refreshPromise;

  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/api/jobs/user-feed-refresh');
  assert.equal(requests[0].options.method, 'POST');
  assert.deepEqual(JSON.parse(requests[0].options.body), {
    payload: { reason: 'manual_subscription_console' },
  });
  assert.deepEqual(polledJob, {
    jobId: 'job-existing',
    jobType: 'user_feed_refresh',
  });
  assert.match(messageElement.textContent, /已有|存在/);
  assert.equal(elements.refreshBtn.disabled, true);
  assert.equal(elements.refreshMyFeedBtn.disabled, true);
});

test('delayed feed refresh response cannot replace another user activity or controls', async () => {
  let resolvePost;
  const pendingPost = new Promise((resolve) => { resolvePost = resolve; });
  const polls = [];
  let previewLoads = 0;
  const { context, messageElement } = loadSubscriptions(async () => {
    throw new Error('unexpected raw fetch');
  });
  context.fetchSubscriptionApi = async () => pendingPost;
  context.pollJobUntilTerminal = (...args) => { polls.push(args); };
  context.loadJobsPreview = async () => { previewLoads += 1; };

  const refreshing = context.refreshMyFeed();
  await new Promise((resolve) => setImmediate(resolve));
  context.state.auth.user = { id: 'user-b', role: 'member' };
  const userBSubmission = { jobType: 'source_fetch', owner: 'user-b' };
  const userBActivity = {
    job: { id: 'job-b', user_id: 'user-b', job_type: 'user_feed_refresh', status: 'running' },
    workerStatus: 'ready',
  };
  context.state.subscriptionJobSubmission = userBSubmission;
  context.state.feedActivity = userBActivity;
  messageElement.textContent = 'B message';
  resolvePost({
    id: 'job-a',
    user_id: 'user-a',
    job_type: 'user_feed_refresh',
    status: 'queued',
  });
  await refreshing;

  assert.strictEqual(context.state.feedActivity, userBActivity);
  assert.deepEqual(polls, []);
  assert.equal(previewLoads, 0);
  assert.strictEqual(context.state.subscriptionJobSubmission, userBSubmission);
  assert.equal(messageElement.textContent, 'B message');
});

test('delayed retry response cannot enqueue polling or replace another user state', async () => {
  let resolveRetry;
  const pendingRetry = new Promise((resolve) => { resolveRetry = resolve; });
  const polls = [];
  let previewLoads = 0;
  const { context, messageElement } = loadSubscriptions(async () => {
    throw new Error('unexpected raw fetch');
  });
  context.state.subscriptionConsole = {
    jobs: [{
      id: 'job-a-failed',
      user_id: 'user-me',
      job_type: 'user_feed_refresh',
      status: 'failed',
    }],
  };
  context.fetchSubscriptionApi = async () => pendingRetry;
  context.pollJobUntilTerminal = (...args) => { polls.push(args); };
  context.loadJobsPreview = async () => { previewLoads += 1; };

  const retrying = context.retryJob('job-a-failed');
  await new Promise((resolve) => setImmediate(resolve));
  context.state.auth.user = { id: 'user-b', role: 'member' };
  const userBSubmission = { jobType: 'source_test', owner: 'user-b' };
  const userBActivity = {
    job: { id: 'job-b', user_id: 'user-b', job_type: 'user_feed_refresh', status: 'running' },
    workerStatus: 'ready',
  };
  const userBConsole = { jobs: [{ id: 'job-b' }] };
  context.state.subscriptionJobSubmission = userBSubmission;
  context.state.feedActivity = userBActivity;
  context.state.subscriptionConsole = userBConsole;
  messageElement.textContent = 'B message';
  resolveRetry({
    id: 'job-a-retry',
    user_id: 'user-me',
    job_type: 'user_feed_refresh',
    status: 'queued',
  });
  await retrying;

  assert.strictEqual(context.state.feedActivity, userBActivity);
  assert.strictEqual(context.state.subscriptionConsole, userBConsole);
  assert.deepEqual(polls, []);
  assert.equal(previewLoads, 0);
  assert.strictEqual(context.state.subscriptionJobSubmission, userBSubmission);
  assert.equal(messageElement.textContent, 'B message');
});

test('auth action invalidation advances the generation and releases only old controls', () => {
  const { context } = loadSubscriptions(async () => { throw new Error('unexpected fetch'); });
  assert.equal(typeof context.invalidateSubscriptionActions, 'function');
  let timerCleared = false;
  context.window.clearTimeout = () => { timerCleared = true; };
  context.state.subscriptionActionGeneration = 7;
  context.state.subscriptionJobSubmission = { jobType: 'source_test' };
  context.state.subscriptionJobPoll = { timer: 99 };
  const previousPollGeneration = context.state.subscriptionJobPollGeneration || 0;

  context.invalidateSubscriptionActions();

  assert.equal(context.state.subscriptionActionGeneration, 8);
  assert.equal(context.state.subscriptionJobSubmission, false);
  assert.equal(context.state.subscriptionJobPoll, null);
  assert.equal(context.state.subscriptionJobPollGeneration, previousPollGeneration + 1);
  assert.equal(timerCleared, true);
});

test('viewer refresh handler never submits even if invoked programmatically', async () => {
  let fetchCalls = 0;
  const { context, elements } = loadSubscriptions(async () => {
    fetchCalls += 1;
    throw new Error('viewer must not fetch');
  });
  context.state.auth.user.role = 'viewer';

  await context.refreshMyFeed();
  context.updateFeedRefreshButtons();

  assert.equal(fetchCalls, 0);
  assert.equal(elements.refreshBtn.disabled, true);
  assert.equal(elements.refreshMyFeedBtn.disabled, true);
});

test('reload resumes the newest active supported job and disables job buttons immediately', () => {
  const neverResolves = () => new Promise(() => {});
  const { context } = loadSubscriptions(neverResolves);
  const jobs = [
    {
      id: 'job-feed-old',
      job_type: 'user_feed_refresh',
      status: 'running',
      user_id: 'user-me',
      created_at: '2026-07-10T08:00:00+00:00',
    },
    {
      id: 'job-source-new',
      job_type: 'source_fetch',
      status: 'queued',
      user_id: 'user-me',
      source_id: 'source-new',
      subscription_id: 'subscription-new',
      created_at: '2026-07-10T10:00:00+00:00',
    },
    {
      id: 'job-test-middle',
      job_type: 'source_test',
      status: 'queued',
      user_id: 'user-me',
      created_at: '2026-07-10T09:00:00+00:00',
    },
  ];

  context.resumeActiveFeedJobPoll(jobs);

  assert.equal(context.state.subscriptionJobPoll.jobId, 'job-source-new');
  assert.equal(context.state.subscriptionJobPoll.sourceId, 'source-new');
  assert.equal(context.state.subscriptionJobPoll.subscriptionId, 'subscription-new');
  assert.match(
    context.jobWriteDisabledAttr('source_fetch', 'source-new', 'subscription-new'),
    /disabled/
  );
  assert.doesNotMatch(
    context.jobWriteDisabledAttr('source_fetch', 'source-other', null),
    /disabled/
  );
  assert.doesNotMatch(
    context.jobWriteDisabledAttr('source_test', 'source-new', 'subscription-new'),
    /disabled/
  );
  assert.equal(context.subscriptionJobPending('user_feed_refresh'), false);
});

test('admin reload ignores newer active jobs owned by another user', () => {
  const neverResolves = () => new Promise(() => {});
  const { context } = loadSubscriptions(neverResolves);
  context.state.auth.user.role = 'owner';

  context.resumeActiveFeedJobPoll([
    {
      id: 'job-missing-owner',
      job_type: 'source_fetch',
      status: 'running',
      source_id: 'source-unknown',
      created_at: '2026-07-10T12:00:00+00:00',
    },
    {
      id: 'job-other-user',
      job_type: 'user_feed_refresh',
      status: 'running',
      user_id: 'user-other',
      created_at: '2026-07-10T11:00:00+00:00',
    },
    {
      id: 'job-current-user',
      job_type: 'source_test',
      status: 'queued',
      user_id: 'user-me',
      source_id: 'source-mine',
      created_at: '2026-07-10T10:00:00+00:00',
    },
  ]);

  assert.equal(context.state.subscriptionJobPoll.jobId, 'job-current-user');
});

test('all current-user active source jobs keep their exact controls disabled', () => {
  const neverResolves = () => new Promise(() => {});
  const { context } = loadSubscriptions(neverResolves);
  context.state.auth.user.role = 'owner';
  const jobs = [
      {
        id: 'job-polled-newest',
        job_type: 'source_fetch',
        status: 'running',
        user_id: 'user-me',
        source_id: 'source-newest',
        subscription_id: 'subscription-newest',
        created_at: '2026-07-10T11:00:00+00:00',
      },
      {
        id: 'job-not-polled',
        job_type: 'source_test',
        status: 'queued',
        user_id: 'user-me',
        source_id: 'source-older',
        subscription_id: 'subscription-older',
        created_at: '2026-07-10T10:00:00+00:00',
      },
      {
        id: 'job-other-user',
        job_type: 'source_test',
        status: 'running',
        user_id: 'user-other',
        source_id: 'source-other',
        subscription_id: 'subscription-other',
        created_at: '2026-07-10T12:00:00+00:00',
      },
    ];

  context.resumeActiveFeedJobPoll(jobs);
  context.state.subscriptionConsole = { jobs };

  assert.equal(context.state.subscriptionJobPoll.jobId, 'job-polled-newest');
  assert.match(
    context.jobWriteDisabledAttr('source_test', 'source-older', 'subscription-older'),
    /disabled/
  );
  assert.doesNotMatch(
    context.jobWriteDisabledAttr('source_test', 'source-older', 'subscription-different'),
    /disabled/
  );
  assert.doesNotMatch(
    context.jobWriteDisabledAttr('source_test', 'source-other', 'subscription-other'),
    /disabled/
  );
});

test('partial terminal jobs show result issues and still reload their snapshot', async () => {
  const partialJob = {
    id: 'job-partial',
    job_type: 'user_feed_refresh',
    status: 'partial',
    result_json: {
      snapshot_id: 'snapshot-partial',
      issues: [
        { code: 'TimeoutError', message: 'one source timed out' },
      ],
    },
  };
  const fetchImpl = async () => ({
    ok: true,
    status: 200,
    async json() {
      return { ok: true, data: partialJob };
    },
  });
  const { context, messageElement } = loadSubscriptions(fetchImpl);
  let loadDataCalls = 0;
  context.loadJobsPreview = async () => {};
  context.loadData = async () => {
    loadDataCalls += 1;
    return true;
  };

  const returned = await context.pollJobUntilTerminal(
    partialJob.id,
    partialJob.job_type,
    Date.now()
  );

  assert.equal(returned.status, 'partial');
  assert.equal(loadDataCalls, 1);
  assert.equal(context.state.subscriptionJobPoll, null);
  assert.match(messageElement.textContent, /TimeoutError: one source timed out/);
});

test('source-fetch and full-refresh terminals refresh health once while source-test does not', async () => {
  async function runTerminal(jobType) {
    const job = {
      id: `job-${jobType}`,
      job_type: jobType,
      status: 'failed',
      user_id: 'user-me',
      source_id: 'source-health',
      subscription_id: 'subscription-health',
      result_json: {},
      error_code: 'TerminalFailure',
      error_message: 'finished for test',
    };
    let healthRequests = 0;
    const { context } = loadSubscriptions(async (url) => {
      const pathname = String(url).split('?')[0];
      if (pathname === `/api/jobs/${job.id}`) {
        return {
          ok: true,
          status: 200,
          async json() { return { ok: true, data: job }; },
        };
      }
      if (pathname === '/api/me/source-health') {
        healthRequests += 1;
        return {
          ok: true,
          status: 200,
          async json() { return { ok: true, data: healthPayload([healthItem()]) }; },
        };
      }
      throw new Error(`unexpected request: ${url}`);
    });
    context.state.subscriptionConsole = { jobs: [job] };
    context.loadJobsPreview = async () => {};
    context.loadFeedSchedule = async () => ({});
    let renders = 0;
    context.renderSubscriptionConsole = () => { renders += 1; };

    await context.pollJobUntilTerminal(
      job.id,
      job.job_type,
      Date.now(),
      job.source_id,
      job.subscription_id
    );
    return { healthRequests, renders };
  }

  const sourceFetch = await runTerminal('source_fetch');
  const fullRefresh = await runTerminal('user_feed_refresh');
  const sourceTest = await runTerminal('source_test');

  assert.equal(sourceFetch.healthRequests, 1);
  assert.ok(sourceFetch.renders >= 1);
  assert.equal(fullRefresh.healthRequests, 1);
  assert.ok(fullRefresh.renders >= 1);
  assert.equal(sourceTest.healthRequests, 0);
});

test('one in-flight health read is shared and an old-user response cannot overwrite current health', async () => {
  let resolveOldHealth;
  let healthRequests = 0;
  const pendingOldHealth = new Promise((resolve) => { resolveOldHealth = resolve; });
  const { context } = loadSubscriptions(async (url) => {
    assert.match(String(url), /^\/api\/me\/source-health\?/);
    healthRequests += 1;
    return pendingOldHealth;
  });
  assert.equal(typeof context.loadSourceHealth, 'function');
  const oldRequest = context.loadSourceHealth({ render: false });
  const duplicateRequest = context.loadSourceHealth({ render: false });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(healthRequests, 1);

  const currentHealth = healthPayload([
    healthItem({
      subscription_id: 'subscription-new-user',
      source_id: 'source-new-user',
      source_display_name: 'New User Source',
    }),
  ]);
  context.state.auth.user = { id: 'user-new', username: 'new', role: 'member' };
  context.state.sourceHealth = currentHealth;
  context.state.sourceHealthLoadUserId = 'user-new';
  resolveOldHealth({
    ok: true,
    status: 200,
    async json() { return { ok: true, data: healthPayload([healthItem()]) }; },
  });
  const [oldResult, duplicateResult] = await Promise.all([oldRequest, duplicateRequest]);

  assert.equal(oldResult, null);
  assert.equal(duplicateResult, null);
  assert.strictEqual(context.state.sourceHealth, currentHealth);
  assert.equal(context.state.sourceHealth.items[0].subscription_id, 'subscription-new-user');
});

test('terminal health sync starts a trailing read instead of accepting a pre-terminal in-flight result', async () => {
  let resolvePreTerminal;
  let healthRequests = 0;
  const preTerminalResponse = new Promise((resolve) => { resolvePreTerminal = resolve; });
  const terminalHealth = healthPayload([
    healthItem({ last_job_id: 'job-terminal-health', last_fetched_count: 9 }),
  ]);
  const { context } = loadSubscriptions(async (url) => {
    assert.match(String(url), /^\/api\/me\/source-health\?/);
    healthRequests += 1;
    if (healthRequests === 1) return preTerminalResponse;
    return {
      ok: true,
      status: 200,
      async json() { return { ok: true, data: terminalHealth }; },
    };
  });

  const preTerminalLoad = context.loadSourceHealth({ render: false });
  await new Promise((resolve) => setImmediate(resolve));
  const syncPromise = context.refreshSourceHealthForTerminalJob({
    id: 'job-terminal-health',
    job_type: 'source_fetch',
    status: 'succeeded',
  });
  await new Promise((resolve) => setImmediate(resolve));
  const requestsAfterTerminal = healthRequests;
  if (requestsAfterTerminal === 1) {
    resolvePreTerminal({
      ok: true,
      status: 200,
      async json() {
        return {
          ok: true,
          data: healthPayload([healthItem({ last_job_id: 'job-before-terminal' })]),
        };
      },
    });
  }
  const synced = await syncPromise;

  assert.equal(synced, true);
  assert.equal(requestsAfterTerminal, 2);
  assert.equal(context.state.sourceHealth.items[0].last_job_id, 'job-terminal-health');
  assert.equal(context.sourceHealthTerminalJobSynced('job-terminal-health'), true);

  if (requestsAfterTerminal > 1) {
    resolvePreTerminal({
      ok: true,
      status: 200,
      async json() {
        return {
          ok: true,
          data: healthPayload([healthItem({ last_job_id: 'job-before-terminal' })]),
        };
      },
    });
  }
  assert.equal(await preTerminalLoad, requestsAfterTerminal > 1 ? null : context.state.sourceHealth);
  assert.equal(context.state.sourceHealth.items[0].last_job_id, 'job-terminal-health');
});

test('an invalidated old-user console load cannot block or overwrite a new-user console load', async () => {
  const oldResolvers = [];
  let requestBatch = 'old';
  function responseData(pathname, userId) {
    const suffix = userId === 'user-old' ? 'old' : 'new';
    return {
      '/api/dashboard/summary': { current_user: { id: userId, username: suffix, role: 'member' } },
      '/api/catalog/sources': { sources: [{ id: `source-${suffix}` }] },
      '/api/catalog/source-types': { source_types: [] },
      '/api/me/subscriptions': { subscriptions: [{ id: `subscription-${suffix}`, source_id: `source-${suffix}` }] },
      '/api/jobs': { jobs: [] },
      '/api/feed/history': { snapshots: [] },
      '/api/me/feed-schedule': { enabled: false, interval_minutes: 360, active_job: null, last_job: null },
      '/api/me/source-health': healthPayload([
        healthItem({
          subscription_id: `subscription-${suffix}`,
          source_id: `source-${suffix}`,
          source_display_name: `${suffix} source`,
        }),
      ]),
    }[pathname];
  }
  const { context } = loadSubscriptions((url) => {
    const pathname = String(url).split('?')[0];
    const userId = requestBatch === 'old' ? 'user-old' : 'user-new';
    const response = {
      ok: true,
      status: 200,
      async json() { return { ok: true, data: responseData(pathname, userId) }; },
    };
    if (requestBatch === 'new') return Promise.resolve(response);
    return new Promise((resolve) => oldResolvers.push(() => resolve(response)));
  });
  context.state.auth.user = { id: 'user-old', username: 'old', role: 'member' };
  context.resumeActiveFeedJobPoll = () => {};

  const oldLoad = context.loadSubscriptionConsole();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(context.state.subscriptionConsoleLoading, true);

  context.state.auth.user = { id: 'user-new', username: 'new', role: 'member' };
  assert.equal(typeof context.invalidateSubscriptionConsoleLoads, 'function');
  context.invalidateSubscriptionConsoleLoads(true);
  context.invalidateSourceHealthLoads(true);
  requestBatch = 'new';
  await context.loadSubscriptionConsole();
  assert.equal(context.state.subscriptionConsole.subscriptions[0].id, 'subscription-new');

  oldResolvers.forEach((resolve) => resolve());
  await oldLoad;

  assert.equal(context.state.subscriptionConsole.subscriptions[0].id, 'subscription-new');
  assert.equal(context.state.sourceHealth.items[0].subscription_id, 'subscription-new');
  assert.equal(context.state.subscriptionConsoleLoading, false);
});

test('an old-user jobs preview cannot populate or rerender the new-user console', async () => {
  let resolveOldJobs;
  const pendingOldJobs = new Promise((resolve) => { resolveOldJobs = resolve; });
  const { context } = loadSubscriptions(async (url) => {
    assert.match(String(url), /^\/api\/jobs\?/);
    return pendingOldJobs;
  });
  context.state.subscriptionConsole = { jobs: [{ id: 'job-new-user' }] };
  let renderedJobs = null;
  context.renderSubscriptionConsole = (data) => { renderedJobs = data.jobs; };

  const oldPreview = context.loadJobsPreview();
  await new Promise((resolve) => setImmediate(resolve));
  context.state.auth.user = { id: 'user-new', username: 'new', role: 'member' };
  context.invalidateSubscriptionConsoleLoads(true);
  context.state.subscriptionConsole = { jobs: [{ id: 'job-new-user' }] };
  resolveOldJobs({
    ok: true,
    status: 200,
    async json() { return { ok: true, data: { jobs: [{ id: 'alice-private-job' }] } }; },
  });
  await oldPreview;

  assert.deepEqual(context.state.subscriptionConsole.jobs, [{ id: 'job-new-user' }]);
  assert.equal(renderedJobs, null);
});

test('login logout and unauthorized auth transitions invalidate cached user-scoped work', () => {
  const loginBody = authSource.match(/async function handleAuthLoginSubmit[\s\S]*?async function handleAuthLogout/);
  const logoutBody = authSource.match(/async function handleAuthLogout[\s\S]*?async function handleConfigUnauthorized/);
  const unauthorizedBody = authSource.match(/async function handleConfigUnauthorized[\s\S]*$/);

  assert.ok(loginBody);
  assert.ok(logoutBody);
  assert.ok(unauthorizedBody);
  assert.match(loginBody[0], /invalidateSourceHealthLoads\(true\)/);
  assert.match(loginBody[0], /invalidateSubscriptionConsoleLoads\(true\)/);
  assert.match(loginBody[0], /invalidateSubscriptionActions\(\)/);
  assert.match(logoutBody[0], /invalidateSourceHealthLoads\(true\)/);
  assert.match(logoutBody[0], /invalidateSubscriptionConsoleLoads\(true\)/);
  assert.match(logoutBody[0], /invalidateSubscriptionActions\(\)/);
  assert.match(unauthorizedBody[0], /invalidateSourceHealthLoads\(true\)/);
  assert.match(unauthorizedBody[0], /invalidateSubscriptionConsoleLoads\(true\)/);
  assert.match(unauthorizedBody[0], /invalidateSubscriptionActions\(\)/);
});

test('schedule card is read-only for viewers and shows partial and stale worker details', () => {
  const { context } = loadSubscriptions(async () => { throw new Error('unexpected fetch'); });
  context.state.auth.user.role = 'viewer';
  const html = context.renderFeedScheduleCard({
    enabled: true,
    interval_minutes: 180,
    allowed_intervals: [60, 180, 360, 720, 1440],
    last_enqueued_at: '2026-07-11T10:00:00Z',
    next_run_at: '2026-07-11T13:00:00Z',
    last_skip_reason: 'active_source_fetch',
    worker_status: 'stale',
    active_job: { id: 'job-active', status: 'running' },
    last_job: {
      id: 'job-partial',
      status: 'partial',
      result_json: {
        item_count: 7,
        issues: [
          { code: 'TimeoutError', message: 'source A timed out' },
          { code: 'HTTPError', message: 'source B returned 503' },
        ],
      },
    },
  });

  assert.match(html, /自动更新信息流/);
  assert.match(html, /1 小时/);
  assert.match(html, /24 小时/);
  assert.match(html, /partial/);
  assert.match(html, /7 条/);
  assert.match(html, /2 个失败来源|2 个问题/);
  assert.match(html, /TimeoutError/);
  assert.match(html, /Worker stale/);
  assert.match(html, /job-active/);
  assert.match(html, /来源抓取任务正在运行/);
  assert.match(html, /DATE\(2026-07-11T10:00:00Z\)/);
  assert.match(html, /DATE\(2026-07-11T13:00:00Z\)/);
  assert.match(html, /name="enabled"[^>]*disabled/);
  assert.match(html, /name="interval_minutes"[^>]*disabled/);
  assert.match(html, /type="submit"[^>]*disabled/);
});

test('saving schedule patches enabled and interval then reloads the console', async () => {
  const requests = [];
  const fetchImpl = async (url, options) => {
    requests.push({ url: String(url), options });
    return {
      ok: true,
      status: 200,
      async json() {
        return {
          ok: true,
          data: {
            schema_version: 1,
            enabled: true,
            interval_minutes: 180,
            allowed_intervals: [60, 180, 360, 720, 1440],
          },
        };
      },
    };
  };
  const { context } = loadSubscriptions(fetchImpl);
  let reloads = 0;
  context.loadSubscriptionConsole = async () => { reloads += 1; };
  const form = {
    elements: {
      enabled: { checked: true },
      interval_minutes: { value: '180' },
    },
  };
  const event = {
    preventDefault() {},
    target: { closest: () => form },
  };

  await context.saveFeedSchedule(event);

  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/api/me/feed-schedule');
  assert.equal(requests[0].options.method, 'PATCH');
  assert.deepEqual(JSON.parse(requests[0].options.body), {
    enabled: true,
    interval_minutes: 180,
  });
  assert.equal(reloads, 1);
});

test('schedule load restores its active feed job through the shared poller', async () => {
  const schedule = {
    schema_version: 1,
    enabled: true,
    interval_minutes: 360,
    allowed_intervals: [60, 180, 360, 720, 1440],
    active_job: {
      id: 'job-scheduled-active',
      job_type: 'user_feed_refresh',
      status: 'queued',
      user_id: 'user-me',
      created_at: '2026-07-11T10:00:00Z',
    },
    worker_status: 'ready',
  };
  const fetchImpl = async (url) => {
    if (String(url).startsWith('/api/me/feed-schedule')) {
      return {
        ok: true,
        status: 200,
        async json() { return { ok: true, data: schedule }; },
      };
    }
    return new Promise(() => {});
  };
  const { context, elements } = loadSubscriptions(fetchImpl);

  await context.loadFeedSchedule();

  assert.strictEqual(context.state.feedSchedule, schedule);
  assert.equal(context.state.subscriptionJobPoll.jobId, 'job-scheduled-active');
  assert.equal(elements.refreshBtn.disabled, true);
  assert.equal(elements.refreshMyFeedBtn.disabled, true);
});

test('terminal polls resume every remaining active job and eventually load the feed snapshot', async () => {
  const initialJobs = [
    {
      id: 'job-source-test-new',
      job_type: 'source_test',
      status: 'running',
      user_id: 'user-me',
      created_at: '2026-07-11T12:00:00Z',
    },
    {
      id: 'job-source-fetch-middle',
      job_type: 'source_fetch',
      status: 'queued',
      user_id: 'user-me',
      created_at: '2026-07-11T11:00:00Z',
    },
    {
      id: 'job-feed-old',
      job_type: 'user_feed_refresh',
      status: 'queued',
      user_id: 'user-me',
      created_at: '2026-07-11T10:00:00Z',
    },
  ];
  const terminals = {
    'job-source-test-new': {
      ...initialJobs[0],
      status: 'succeeded',
      result_json: {},
    },
    'job-source-fetch-middle': {
      ...initialJobs[1],
      status: 'succeeded',
      result_json: {},
    },
    'job-feed-old': {
      ...initialJobs[2],
      status: 'succeeded',
      result_json: { snapshot_id: 'snapshot-feed-final', item_count: 4 },
    },
  };
  const remainingJobs = [
    [initialJobs[1], initialJobs[2]],
    [initialJobs[2]],
    [],
  ];
  let jobsRefreshes = 0;
  let scheduleRefreshes = 0;
  const polledJobIds = [];
  const fetchImpl = async (url) => {
    const pathname = String(url).split('?')[0];
    if (pathname.startsWith('/api/jobs/job-')) {
      const jobId = pathname.slice('/api/jobs/'.length);
      polledJobIds.push(jobId);
      return {
        ok: true,
        status: 200,
        async json() { return { ok: true, data: terminals[jobId] }; },
      };
    }
    if (pathname === '/api/jobs') {
      const jobs = remainingJobs[Math.min(jobsRefreshes, remainingJobs.length - 1)];
      jobsRefreshes += 1;
      return {
        ok: true,
        status: 200,
        async json() { return { ok: true, data: { jobs } }; },
      };
    }
    if (pathname === '/api/me/feed-schedule') {
      // Simulate a briefly stale schedule response that still reports the
      // just-finished feed refresh as active on the final reconciliation.
      const activeJob = initialJobs[2];
      scheduleRefreshes += 1;
      return {
        ok: true,
        status: 200,
        async json() {
          return {
            ok: true,
            data: {
              schema_version: 1,
              enabled: true,
              interval_minutes: 360,
              allowed_intervals: [60, 180, 360, 720, 1440],
              active_job: activeJob,
              worker_status: 'ready',
            },
          };
        },
      };
    }
    throw new Error(`unexpected request: ${url}`);
  };
  const { context, elements } = loadSubscriptions(fetchImpl);
  context.state.subscriptionConsole = { jobs: initialJobs };
  context.state.feedSchedule = {
    active_job: initialJobs[2],
    worker_status: 'ready',
  };
  context.renderSubscriptionConsole = () => context.updateFeedRefreshButtons();
  let loadDataCalls = 0;
  context.loadData = async () => { loadDataCalls += 1; return true; };

  context.resumeActiveFeedJobPoll(initialJobs);
  await new Promise((resolve) => setTimeout(resolve, 30));

  assert.deepEqual(polledJobIds, [
    'job-source-test-new',
    'job-source-fetch-middle',
    'job-feed-old',
  ]);
  assert.equal(jobsRefreshes, 3);
  assert.ok(scheduleRefreshes >= 3);
  assert.equal(loadDataCalls, 1);
  assert.equal(context.state.subscriptionJobPoll, null);
  assert.equal(context.state.feedSchedule.active_job, null);
  assert.equal(elements.refreshBtn.disabled, false);
  assert.equal(elements.refreshMyFeedBtn.disabled, false);
});

test('schedule watcher discovers a newly queued automatic refresh after the page stays open', async () => {
  const timers = [];
  let fetchCalls = 0;
  const activeJob = {
    id: 'job-scheduled-later',
    job_type: 'user_feed_refresh',
    status: 'queued',
    user_id: 'user-me',
    created_at: '2026-07-11T13:00:00Z',
  };
  let healthRequests = 0;
  const { context } = loadSubscriptions(async (url) => {
    const pathname = String(url).split('?')[0];
    if (pathname === '/api/me/source-health') {
      healthRequests += 1;
      return {
        ok: true,
        status: 200,
        async json() { return { ok: true, data: healthPayload([healthItem()]) }; },
      };
    }
    assert.equal(pathname, '/api/me/feed-schedule');
    fetchCalls += 1;
    return {
      ok: true,
      status: 200,
      async json() {
        return {
          ok: true,
          data: {
            schema_version: 1,
            enabled: true,
            interval_minutes: 360,
            active_job: activeJob,
            last_job: null,
            worker_status: 'ready',
          },
        };
      },
    };
  });
  context.state.feedSchedule = {
    enabled: true,
    interval_minutes: 360,
    active_job: null,
    last_job: null,
    worker_status: 'ready',
  };
  context.window.setTimeout = (callback, delay) => {
    timers.push({ callback, delay });
    return timers.length;
  };
  context.window.clearTimeout = () => {};
  let resumedJobs = [];
  context.resumeActiveFeedJobPoll = (jobs) => { resumedJobs = jobs; };

  context.startFeedScheduleWatcher();
  assert.equal(timers.length, 1);
  assert.equal(timers[0].delay, 30000);
  const firstTick = timers.shift();
  await firstTick.callback();

  assert.equal(fetchCalls, 1);
  assert.equal(resumedJobs.length, 1);
  assert.equal(resumedJobs[0].id, 'job-scheduled-later');
  assert.equal(timers.length, 1);
  context.stopFeedScheduleWatcher();
});

test('watcher does not premark a queued baseline last job and refreshes it after terminal', async () => {
  const queuedJob = {
    id: 'job-baseline-queued',
    job_type: 'user_feed_refresh',
    status: 'queued',
    user_id: 'user-me',
    result_json: {},
  };
  const terminalJob = {
    ...queuedJob,
    status: 'succeeded',
    result_json: { snapshot_id: 'snapshot-baseline-terminal', item_count: 2 },
  };
  let healthRequests = 0;
  const { context } = loadSubscriptions(async (url) => {
    const pathname = String(url).split('?')[0];
    if (pathname === '/api/me/feed-schedule') {
      return {
        ok: true,
        status: 200,
        async json() {
          return {
            ok: true,
            data: { active_job: null, last_job: terminalJob, worker_status: 'ready' },
          };
        },
      };
    }
    if (pathname === '/api/me/source-health') {
      healthRequests += 1;
      return {
        ok: true,
        status: 200,
        async json() { return { ok: true, data: healthPayload([healthItem()]) }; },
      };
    }
    throw new Error(`unexpected request: ${url}`);
  });
  context.state.feedSchedule = {
    active_job: queuedJob,
    last_job: queuedJob,
    worker_status: 'ready',
  };
  context.window.setTimeout = () => 71;
  context.window.clearTimeout = () => {};
  let feedReloads = 0;
  context.loadData = async () => { feedReloads += 1; return true; };

  context.startFeedScheduleWatcher();
  assert.equal(context.feedTerminalJobHandled(queuedJob.id), false);
  assert.equal(context.sourceHealthTerminalJobSynced(queuedJob.id), false);
  await context.checkFeedScheduleUpdates();

  assert.equal(healthRequests, 1);
  assert.equal(feedReloads, 1);
  assert.equal(context.feedTerminalJobHandled(queuedJob.id), true);
  assert.equal(context.sourceHealthTerminalJobSynced(queuedJob.id), true);
  context.stopFeedScheduleWatcher();
});

test('schedule watcher reloads Feed when it missed the running state of a completed refresh', async () => {
  const timers = [];
  const order = [];
  const terminalJob = {
    id: 'job-scheduled-terminal',
    job_type: 'user_feed_refresh',
    status: 'succeeded',
    user_id: 'user-me',
    result_json: { snapshot_id: 'snapshot-scheduled-terminal', item_count: 9 },
    created_at: '2026-07-11T13:00:00Z',
  };
  const { context } = loadSubscriptions(async (url) => {
    const pathname = String(url).split('?')[0];
    if (pathname === '/api/me/source-health') {
      order.push('health');
      return {
        ok: true,
        status: 200,
        async json() { return { ok: true, data: healthPayload([healthItem()]) }; },
      };
    }
    assert.equal(pathname, '/api/me/feed-schedule');
    order.push('schedule');
    return {
      ok: true,
      status: 200,
      async json() {
        return {
          ok: true,
          data: {
            schema_version: 1,
            enabled: true,
            interval_minutes: 360,
            active_job: null,
            last_job: terminalJob,
            worker_status: 'ready',
          },
        };
      },
    };
  });
  context.state.feedSchedule = {
    enabled: true,
    interval_minutes: 360,
    active_job: null,
    last_job: {
      id: 'job-scheduled-old',
      status: 'succeeded',
      result_json: { snapshot_id: 'snapshot-scheduled-old' },
    },
    worker_status: 'ready',
  };
  context.window.setTimeout = (callback, delay) => {
    timers.push({ callback, delay });
    return timers.length;
  };
  context.window.clearTimeout = () => {};
  let loadDataCalls = 0;
  context.loadData = async () => { order.push('feed'); loadDataCalls += 1; return true; };

  context.startFeedScheduleWatcher();
  const firstTick = timers.shift();
  await firstTick.callback();

  assert.equal(loadDataCalls, 1);
  assert.deepEqual(order, ['schedule', 'health', 'feed']);
  assert.equal(context.state.feedScheduleWatchLastJobId, 'job-scheduled-terminal');
  assert.equal(timers.length, 1);
  context.stopFeedScheduleWatcher();
});

test('schedule watcher and active job poll handle one terminal snapshot exactly once', async () => {
  const timers = [];
  let healthRequests = 0;
  let resolveJobResponse;
  const jobResponse = new Promise((resolve) => { resolveJobResponse = resolve; });
  const terminalJob = {
    id: 'job-shared-terminal',
    job_type: 'user_feed_refresh',
    status: 'succeeded',
    user_id: 'user-me',
    result_json: { snapshot_id: 'snapshot-shared-terminal', item_count: 5 },
    created_at: '2026-07-11T14:00:00Z',
  };
  const terminalSchedule = {
    schema_version: 1,
    enabled: true,
    interval_minutes: 360,
    active_job: null,
    last_job: terminalJob,
    worker_status: 'ready',
  };
  const { context } = loadSubscriptions(async (url) => {
    const pathname = String(url).split('?')[0];
    if (pathname === '/api/jobs/job-shared-terminal') return jobResponse;
    if (pathname === '/api/me/feed-schedule') {
      return {
        ok: true,
        status: 200,
        async json() { return { ok: true, data: terminalSchedule }; },
      };
    }
    if (pathname === '/api/me/source-health') {
      healthRequests += 1;
      return {
        ok: true,
        status: 200,
        async json() { return { ok: true, data: healthPayload([healthItem()]) }; },
      };
    }
    throw new Error(`unexpected request: ${url}`);
  });
  context.state.feedSchedule = {
    enabled: true,
    interval_minutes: 360,
    active_job: null,
    last_job: { id: 'job-before-shared-terminal', status: 'succeeded' },
    worker_status: 'ready',
  };
  context.window.setTimeout = (callback, delay) => {
    timers.push({ callback, delay });
    return timers.length;
  };
  context.window.clearTimeout = () => {};
  context.loadJobsPreview = async () => {};
  let loadDataCalls = 0;
  context.loadData = async () => { loadDataCalls += 1; return true; };

  context.startFeedScheduleWatcher();
  const pollPromise = context.pollJobUntilTerminal(
    terminalJob.id,
    terminalJob.job_type,
    Date.now()
  );
  await context.checkFeedScheduleUpdates();
  assert.equal(loadDataCalls, 0);
  resolveJobResponse({
    ok: true,
    status: 200,
    async json() { return { ok: true, data: terminalJob }; },
  });
  await pollPromise;

  assert.equal(loadDataCalls, 1);
  assert.equal(healthRequests, 1);
  assert.equal(context.state.feedScheduleHandledJobId, terminalJob.id);
  context.stopFeedScheduleWatcher();
});

test('stopping schedule watcher blocks an old-user response and cancels its active poll', async () => {
  const clearedTimers = [];
  let resolveScheduleResponse;
  const pendingSchedule = new Promise((resolve) => { resolveScheduleResponse = resolve; });
  const oldUserTerminal = {
    id: 'job-old-user-terminal',
    job_type: 'user_feed_refresh',
    status: 'succeeded',
    user_id: 'user-me',
    result_json: { snapshot_id: 'snapshot-old-user', item_count: 3 },
  };
  const { context } = loadSubscriptions(async (url) => {
    assert.match(String(url), /^\/api\/me\/feed-schedule\?/);
    return pendingSchedule;
  });
  context.state.feedSchedule = {
    enabled: true,
    interval_minutes: 360,
    active_job: null,
    last_job: { id: 'job-old-baseline', status: 'succeeded' },
    worker_status: 'ready',
  };
  let nextTimerId = 10;
  context.window.setTimeout = () => { nextTimerId += 1; return nextTimerId; };
  context.window.clearTimeout = (timerId) => { clearedTimers.push(timerId); };
  let loadDataCalls = 0;
  context.loadData = async () => { loadDataCalls += 1; return true; };

  context.startFeedScheduleWatcher();
  context.setSubscriptionJobPoll(
    'job-old-user-active',
    'user_feed_refresh',
    Date.now()
  );
  context.state.subscriptionJobPoll.timer = 99;
  const oldCheck = context.checkFeedScheduleUpdates();
  await new Promise((resolve) => setImmediate(resolve));
  context.stopFeedScheduleWatcher();
  context.state.auth.user = { id: 'user-new', username: 'new', role: 'member' };
  resolveScheduleResponse({
    ok: true,
    status: 200,
    async json() {
      return {
        ok: true,
        data: {
          schema_version: 1,
          enabled: true,
          interval_minutes: 360,
          active_job: null,
          last_job: oldUserTerminal,
          worker_status: 'ready',
        },
      };
    },
  });
  await oldCheck;

  assert.equal(loadDataCalls, 0);
  assert.equal(context.state.feedScheduleWatchLastJobId, null);
  assert.equal(context.state.subscriptionJobPoll, null);
  assert.ok(clearedTimers.includes(11));
  assert.ok(clearedTimers.includes(99));
});

test('watcher takes over a terminal snapshot after its active poll is cancelled', async () => {
  const terminalJob = {
    id: 'job-terminal-handoff',
    job_type: 'user_feed_refresh',
    status: 'succeeded',
    user_id: 'user-me',
    result_json: { snapshot_id: 'snapshot-terminal-handoff', item_count: 6 },
  };
  const schedule = {
    schema_version: 1,
    enabled: true,
    interval_minutes: 360,
    active_job: null,
    last_job: terminalJob,
    worker_status: 'ready',
  };
  let healthRequests = 0;
  const { context } = loadSubscriptions(async (url) => {
    const pathname = String(url).split('?')[0];
    if (pathname === '/api/me/source-health') {
      healthRequests += 1;
      return {
        ok: true,
        status: 200,
        async json() { return { ok: true, data: healthPayload([healthItem()]) }; },
      };
    }
    assert.equal(pathname, '/api/me/feed-schedule');
    return {
      ok: true,
      status: 200,
      async json() { return { ok: true, data: schedule }; },
    };
  });
  context.state.feedSchedule = {
    ...schedule,
    last_job: { id: 'job-before-handoff', status: 'succeeded' },
  };
  context.window.setTimeout = () => 41;
  context.window.clearTimeout = () => {};
  let loadDataCalls = 0;
  context.loadData = async () => { loadDataCalls += 1; return true; };

  context.startFeedScheduleWatcher();
  context.setSubscriptionJobPoll(terminalJob.id, terminalJob.job_type, Date.now());
  await context.checkFeedScheduleUpdates();
  assert.equal(loadDataCalls, 0);
  assert.equal(context.state.feedScheduleWatchLastJobId, 'job-before-handoff');

  context.cancelSubscriptionJobPoll();
  await context.checkFeedScheduleUpdates();
  assert.equal(healthRequests, 1);
  assert.equal(loadDataCalls, 1);
  assert.equal(context.state.feedScheduleHandledJobId, terminalJob.id);
  context.stopFeedScheduleWatcher();
});

test('watcher retries the same terminal snapshot when the first Feed load fails', async () => {
  const terminalJob = {
    id: 'job-terminal-retry',
    job_type: 'user_feed_refresh',
    status: 'succeeded',
    user_id: 'user-me',
    result_json: { snapshot_id: 'snapshot-terminal-retry', item_count: 8 },
  };
  const schedule = {
    schema_version: 1,
    enabled: true,
    interval_minutes: 360,
    active_job: null,
    last_job: terminalJob,
    worker_status: 'ready',
  };
  const { context } = loadSubscriptions(async () => ({
    ok: true,
    status: 200,
    async json() { return { ok: true, data: schedule }; },
  }));
  context.state.feedSchedule = {
    ...schedule,
    last_job: { id: 'job-before-retry', status: 'succeeded' },
  };
  context.window.setTimeout = () => 51;
  context.window.clearTimeout = () => {};
  let loadDataCalls = 0;
  context.loadData = async () => {
    loadDataCalls += 1;
    return loadDataCalls > 1;
  };

  context.startFeedScheduleWatcher();
  await context.checkFeedScheduleUpdates();
  assert.equal(loadDataCalls, 1);
  assert.notEqual(context.state.feedScheduleHandledJobId, terminalJob.id);
  await context.checkFeedScheduleUpdates();

  assert.equal(loadDataCalls, 2);
  assert.equal(context.state.feedScheduleHandledJobId, terminalJob.id);
  context.stopFeedScheduleWatcher();
});

test('watcher retries failed health sync before handling a failed scheduled terminal without a snapshot', async () => {
  const terminalJob = {
    id: 'job-scheduled-failed-no-snapshot',
    job_type: 'user_feed_refresh',
    status: 'failed',
    user_id: 'user-me',
    result_json: {},
    error_code: 'AllSourcesFailed',
    error_message: 'all source fetches failed',
  };
  const schedule = {
    schema_version: 1,
    enabled: true,
    interval_minutes: 360,
    active_job: null,
    last_job: terminalJob,
    worker_status: 'ready',
  };
  let healthRequests = 0;
  const { context } = loadSubscriptions(async (url) => {
    const pathname = String(url).split('?')[0];
    if (pathname === '/api/me/feed-schedule') {
      return {
        ok: true,
        status: 200,
        async json() { return { ok: true, data: schedule }; },
      };
    }
    if (pathname === '/api/me/source-health') {
      healthRequests += 1;
      if (healthRequests === 1) {
        return {
          ok: false,
          status: 503,
          async json() {
            return { ok: false, error: { code: 'health_unavailable', message: 'try again' } };
          },
        };
      }
      return {
        ok: true,
        status: 200,
        async json() { return { ok: true, data: healthPayload([healthItem()]) }; },
      };
    }
    throw new Error(`unexpected request: ${url}`);
  });
  context.state.feedSchedule = {
    ...schedule,
    last_job: { id: 'job-before-failed-no-snapshot', status: 'succeeded' },
  };
  context.window.setTimeout = () => 61;
  context.window.clearTimeout = () => {};
  let loadDataCalls = 0;
  context.loadData = async () => { loadDataCalls += 1; return true; };

  context.startFeedScheduleWatcher();
  await context.checkFeedScheduleUpdates();
  assert.equal(healthRequests, 1);
  assert.notEqual(context.state.feedScheduleHandledJobId, terminalJob.id);
  assert.notEqual(context.state.feedScheduleWatchLastJobId, terminalJob.id);

  await context.checkFeedScheduleUpdates();
  assert.equal(healthRequests, 2);
  assert.equal(loadDataCalls, 0);
  assert.equal(context.state.feedScheduleHandledJobId, terminalJob.id);
  assert.equal(context.state.feedScheduleWatchLastJobId, terminalJob.id);
  context.stopFeedScheduleWatcher();
});
