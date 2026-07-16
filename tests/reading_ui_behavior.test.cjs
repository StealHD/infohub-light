const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const readerSource = fs.readFileSync(
  path.join(__dirname, '..', 'src', 'ui', 'static', 'reader.js'),
  'utf8'
);
const utilsSource = fs.readFileSync(
  path.join(__dirname, '..', 'src', 'ui', 'static', 'utils.js'),
  'utf8'
);
const appSource = fs.readFileSync(
  path.join(__dirname, '..', 'src', 'ui', 'static', 'app.js'),
  'utf8'
);

function classList() {
  return { add() {}, remove() {}, toggle() {} };
}

function loadReader(overrides = {}) {
  const elements = {};
  ['readingQueue', 'readerPanel', 'contextPanel', 'configPanel', 'subscriptionPanel', 'readerShell', 'feedActivityBanner']
    .forEach((id) => { elements[id] = { classList: classList(), innerHTML: '' }; });
  const context = {
    console,
    state: {
      readItems: new Set(),
      itemState: {},
      selectedItemId: '',
    },
    document: {
      getElementById(id) {
        return elements[id] || null;
      },
    },
    window: { setTimeout, clearTimeout },
    ...overrides,
  };
  vm.createContext(context);
  vm.runInContext(readerSource, context, { filename: 'reader.js' });
  Object.assign(context, overrides);
  return { context, elements };
}

test('initial reader selection does not mark the item read locally', () => {
  const item = { id: 'article-one', title: 'One' };
  const { context } = loadReader();
  context.getFilteredItems = () => [item];
  context.getSelectedItem = (items) => {
    context.state.selectedItemId = items[0].id;
    return items[0];
  };
  context.renderQueue = () => {};
  context.renderReader = () => {};
  context.renderContext = () => {};
  context.markRead = (selected) => {
    context.state.readItems.add(selected.id);
    context.state.itemState[selected.id] = { is_read: true };
  };

  context.renderReaderView();

  assert.equal(context.state.selectedItemId, 'article-one');
  assert.equal(context.state.readItems.has('article-one'), false);
  assert.equal(Object.hasOwn(context.state.itemState, 'article-one'), false);
});

test('legacy local read cache is not treated as the read-state source of truth', () => {
  const context = {
    console,
    state: {
      data: null,
      historyData: null,
      readItems: new Set(['article-stale']),
      favorites: new Set(),
      readLater: new Set(),
    },
    document: { createElement: () => ({ innerHTML: '', value: '' }) },
  };
  vm.createContext(context);
  vm.runInContext(utilsSource, context, { filename: 'utils.js' });

  assert.equal(context.defaultUserItemState('article-stale').is_read, false);
});

test('mark read is one-way: repeated triggers send true only once and render a disabled read button', async () => {
  const requests = [];
  let currentState = { is_read: false, is_saved: false, is_later: false, dismissed: false };
  const item = {
    id: 'article-two',
    title: 'Two',
    source: 'Source',
    summary_zh: 'Summary',
    reason: 'Reason',
    url: 'https://example.com/two',
    score: 7,
  };
  const button = {
    disabled: false,
    getAttribute(name) {
      return {
        'data-item-id': 'article-two',
        'data-item-state-action': 'is_read',
      }[name] || '';
    },
  };
  const { context } = loadReader({
    fetch: async (url, options) => {
      requests.push({ url, options });
      return {
        ok: true,
        async json() {
          return { ok: true, data: { article_id: 'article-two', is_read: true } };
        },
      };
    },
    findKnownItem: () => item,
    itemUserState: () => currentState,
    applyUserItemState: (_id, value) => { currentState = { ...currentState, ...value }; },
    unwrapApiPayload: (payload) => payload.data,
    apiErrorMessage: (_payload, fallback) => fallback,
    renderItems: () => {},
    showCopyFeedback: () => {},
    escapeHtml: (value) => String(value == null ? '' : value),
    viewLabel: () => '今日动态',
    formatDate: () => '未知',
    itemChannel: () => 'AI',
    scoreText: (value) => Number(value || 0).toFixed(1),
    displayText: (value, fallback) => value || fallback,
    renderItemMedia: () => '',
  });
  const target = {
    closest(selector) {
      return selector === '[data-item-state-action]' ? button : null;
    },
  };

  context.handleReaderAction({ target });
  await new Promise((resolve) => setImmediate(resolve));
  context.handleReaderAction({ target });
  await new Promise((resolve) => setImmediate(resolve));
  context.renderReader(item);

  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/api/me/items/article-two/state');
  assert.equal(requests[0].options.method, 'PATCH');
  assert.deepEqual(JSON.parse(requests[0].options.body), { is_read: true });
  assert.equal(currentState.is_read, true);
  assert.match(
    context.document.getElementById('readerPanel').innerHTML,
    /data-item-state-action="is_read"[^>]*disabled[^>]*aria-disabled="true"[^>]*>已读<\/button>/
  );
});

test('feed freshness renders minutes and safely handles future or missing timestamps', () => {
  const context = {
    console,
    state: {},
    document: { createElement: () => ({ innerHTML: '', value: '' }) },
  };
  vm.createContext(context);
  vm.runInContext(utilsSource, context, { filename: 'utils.js' });
  const now = Date.parse('2026-07-11T12:05:00Z');

  assert.equal(context.formatFeedFreshness('2026-07-11T12:00:00Z', now), 'Feed 更新于 5 分钟前');
  assert.equal(context.formatFeedFreshness('2026-07-11T12:06:00Z', now), 'Feed 刚刚更新');
  assert.equal(context.formatFeedFreshness(null, now), 'Feed 更新时间未知');
});

test('safe external URLs allow http links and reject script or credential URLs', () => {
  const context = {
    console,
    state: {},
    URL,
    document: { createElement: () => ({ innerHTML: '', value: '' }) },
  };
  vm.createContext(context);
  vm.runInContext(utilsSource, context, { filename: 'utils.js' });

  assert.equal(context.safeExternalUrl('https://example.com/post?id=1'), 'https://example.com/post?id=1');
  assert.equal(context.safeExternalUrl('http://example.com/post'), 'http://example.com/post');
  assert.equal(context.safeExternalUrl('javascript:alert(1)'), '');
  assert.equal(context.safeExternalUrl('https://user:password@example.com/private'), '');
  assert.equal(context.safeExternalUrl('not a url'), '');
});

test('reader activity banner renders queued running succeeded partial failed and cancelled states', () => {
  const { context, elements } = loadReader({
    escapeHtml: (value) => String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;'),
    formatDate: (value) => value ? `DATE(${value})` : '未知',
    Date: class extends Date {
      static now() { return Date.parse('2026-07-12T12:02:00Z'); }
    },
  });
  const cases = [
    [{ id: 'job-q', status: 'queued', created_at: '2026-07-12T12:00:00Z' }, 'stale', /排队中[\s\S]*Worker stale/],
    [{ id: 'job-r', status: 'running', started_at: '2026-07-12T12:00:00Z' }, 'ready', /正在刷新[\s\S]*已运行 2 分钟/],
    [{ id: 'job-s', status: 'succeeded', finished_at: '2026-07-12T12:01:00Z', result_json: { item_count: 12 } }, 'ready', /刷新完成[\s\S]*12 条[\s\S]*DATE\(2026-07-12T12:01:00Z\)/],
    [{
      id: 'job-p',
      status: 'partial',
      result_json: {
        issues: [{ code: '<Timeout>', message: '<b>slow</b> ' + 'x'.repeat(220), retryable: true }],
      },
    }, 'ready', /部分完成[\s\S]*&lt;Timeout&gt;[\s\S]*可重试[\s\S]*查看失败来源/],
    [{ id: 'job-f', status: 'failed', error_code: 'FetchError', error_message: 'upstream failed' }, 'ready', /刷新失败[\s\S]*FetchError[\s\S]*重试/],
    [{ id: 'job-c', status: 'cancelled' }, 'ready', /已取消[\s\S]*重试/],
  ];

  for (const [job, workerStatus, expected] of cases) {
    context.state.feedActivity = { job, workerStatus };
    context.renderFeedActivityBanner();
    assert.match(elements.feedActivityBanner.innerHTML, expected);
  }
  assert.doesNotMatch(elements.feedActivityBanner.innerHTML, /x{180}/);
});

test('view failed sources switches to subscriptions with the attention filter active', () => {
  let renders = 0;
  const { context } = loadReader({
    renderAll() { renders += 1; },
  });
  context.state.view = 'all';
  context.state.subscriptionConsoleLoaded = true;
  context.state.sourceHealthFilter = '';

  context.viewFailedSourceHealth();

  assert.equal(context.state.view, 'subscriptions');
  assert.equal(context.state.sourceHealthFilter, 'attention');
  assert.equal(context.state.subscriptionConsoleLoaded, false);
  assert.equal(renders, 1);
});

test('loading reader data also loads schedule so an active job can be restored', async () => {
  const elements = {
    itemsList: { innerHTML: '' },
    metaLine: { textContent: '' },
    readerPanel: { innerHTML: '' },
    contextPanel: { innerHTML: '' },
  };
  let scheduleLoads = 0;
  const context = {
    console,
    state: { hideDismissed: false, unreadFirst: false, view: 'all' },
    Date,
    document: {
      addEventListener() {},
      getElementById(id) { return elements[id] || null; },
    },
    canUseConfig: () => true,
    showLoginGate() {},
    fetch: async (url) => ({
      ok: true,
      status: 200,
      async json() {
        return { ok: true, data: String(url).startsWith('/api/feed/history') ? { snapshots: [] } : { items: [] } };
      },
    }),
    unwrapApiPayload: (payload) => payload.data,
    apiErrorMessage: (_payload, fallback) => fallback,
    handleConfigUnauthorized: async () => {},
    syncUserItemStateFromFeed() {},
    refreshUserItemStates: async () => {},
    loadConfig: async () => {},
    loadFeedSchedule: async () => { scheduleLoads += 1; },
    renderAll() {},
    escapeHtml: (value) => String(value),
    applyReaderDensity() {},
    bindMediaErrorHandlers() {},
    bindEvents() {},
    loadAuthStatus: async () => {},
  };
  vm.createContext(context);
  vm.runInContext(appSource, context, { filename: 'app.js' });

  await context.loadData();

  assert.equal(scheduleLoads, 1);
});

test('an old user slow Feed response cannot overwrite a newer user load', async () => {
  const elements = {
    itemsList: { innerHTML: '' },
    metaLine: { textContent: '' },
    readerPanel: { innerHTML: '' },
    contextPanel: { innerHTML: '' },
  };
  let resolveOldFeed;
  const oldFeedResponse = new Promise((resolve) => { resolveOldFeed = resolve; });
  let feedRequestCount = 0;
  const renders = [];
  const context = {
    console,
    state: {
      hideDismissed: false,
      unreadFirst: false,
      view: 'all',
      auth: { user: { id: 'user-old' } },
      feedDataLoadToken: 0,
    },
    Date,
    document: {
      addEventListener() {},
      getElementById(id) { return elements[id] || null; },
    },
    canUseConfig: () => true,
    showLoginGate() {},
    fetch: async (url) => {
      if (String(url).startsWith('/api/feed/latest')) {
        feedRequestCount += 1;
        if (feedRequestCount === 1) return oldFeedResponse;
        return {
          ok: true,
          status: 200,
          async json() { return { ok: true, data: { owner: 'new', items: [] } }; },
        };
      }
      return {
        ok: true,
        status: 200,
        async json() { return { ok: true, data: { snapshots: [] } }; },
      };
    },
    unwrapApiPayload: (payload) => payload.data,
    apiErrorMessage: (_payload, fallback) => fallback,
    handleConfigUnauthorized: async () => {},
    syncUserItemStateFromFeed() {},
    refreshUserItemStates: async () => {},
    loadConfig: async () => {},
    loadFeedSchedule: async () => {},
    renderAll() { renders.push(context.state.data.owner); },
    escapeHtml: (value) => String(value),
    applyReaderDensity() {},
    bindMediaErrorHandlers() {},
    bindEvents() {},
    loadAuthStatus: async () => {},
    startFeedScheduleWatcher() {},
  };
  vm.createContext(context);
  vm.runInContext(appSource, context, { filename: 'app.js' });

  const oldLoad = context.loadData();
  await new Promise((resolve) => setImmediate(resolve));
  context.state.auth.user = { id: 'user-new' };
  const newLoad = context.loadData();
  await newLoad;
  resolveOldFeed({
    ok: true,
    status: 200,
    async json() { return { ok: true, data: { owner: 'old', items: [] } }; },
  });
  await oldLoad;

  assert.deepEqual(renders, ['new']);
  assert.equal(context.state.data.owner, 'new');
});
