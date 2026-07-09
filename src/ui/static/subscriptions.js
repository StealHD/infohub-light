// Inteliscope static UI: subscription console module.
'use strict';

function subscriptionUserIsViewer() {
  return !!(state.auth.user && state.auth.user.role === 'viewer');
}

function subscriptionUserIsAdmin() {
  return !!(state.auth.user && ['owner', 'admin'].indexOf(state.auth.user.role) >= 0);
}

function setSubscriptionMessage(message, type) {
  var el = document.getElementById('subscriptionMessage');
  if (!el) return;
  el.textContent = message || '';
  el.className = 'config-message' + (type ? ' ' + type : '');
}

async function fetchSubscriptionApi(path, options) {
  var response = await fetch(path, options || {});
  var payload = await response.json();
  if (!response.ok) {
    if (response.status === 401 && typeof handleConfigUnauthorized === 'function') {
      await handleConfigUnauthorized(apiErrorMessage(payload, '登录已失效，请重新登录。'));
    }
    throw new Error(apiErrorMessage(payload, 'HTTP ' + response.status));
  }
  return unwrapApiPayload(payload);
}

async function loadSubscriptionConsole() {
  if (!canUseConfig()) {
    showLoginGate('请先登录后管理订阅。');
    return;
  }
  if (state.subscriptionConsoleLoading) return;
  state.subscriptionConsoleLoading = true;
  document.getElementById('subscriptionSummary').textContent = '正在读取订阅状态';
  document.getElementById('subscriptionConsole').innerHTML = '<div class="empty">正在读取订阅控制台...</div>';
  setSubscriptionMessage('', '');
  try {
    var results = await Promise.all([
      fetchSubscriptionApi('/api/dashboard/summary?ts=' + Date.now()),
      fetchSubscriptionApi('/api/catalog/sources?ts=' + Date.now()),
      fetchSubscriptionApi('/api/catalog/source-types?ts=' + Date.now()),
      fetchSubscriptionApi('/api/me/subscriptions?ts=' + Date.now()),
      fetchSubscriptionApi('/api/jobs?ts=' + Date.now()),
      fetchSubscriptionApi('/api/feed/history?ts=' + Date.now()),
      fetchSubscriptionApi('/api/archive/source-quality?ts=' + Date.now()),
    ]);
    state.subscriptionConsole = {
      summary: results[0] || {},
      sources: (results[1] && results[1].sources) || [],
      sourceTypes: (results[2] && results[2].source_types) || [],
      subscriptions: (results[3] && results[3].subscriptions) || [],
      jobs: (results[4] && results[4].jobs) || [],
      apiStatus: {
        history: results[5] || {},
        sourceQuality: (results[6] && results[6].sources) || [],
      },
    };
    state.subscriptionConsoleLoaded = true;
    renderSubscriptionConsole(state.subscriptionConsole);
  } catch (err) {
    document.getElementById('subscriptionConsole').innerHTML = '<div class="empty">订阅控制台读取失败。</div>';
    setSubscriptionMessage('读取失败：' + err.message, 'error');
  } finally {
    state.subscriptionConsoleLoading = false;
  }
}

function sourceScopeLabel(scope) {
  return {
    public: '公共',
    workspace: '小组',
    private: '私有',
  }[scope] || scope || '未知';
}

function jobTypeLabel(type) {
  return {
    source_test: '测试源',
    source_fetch: '抓取源',
    user_feed_refresh: '刷新信息流',
  }[type] || type || '任务';
}

function subscriptionSourceMap(subscriptions) {
  var map = {};
  (subscriptions || []).forEach(function (subscription) {
    map[subscription.source_id] = subscription;
  });
  return map;
}

function topicText(topics) {
  return (topics || []).length ? topics.join('、') : '未设置主题';
}

function renderSourceCard(source, subscribed) {
  var viewer = subscriptionUserIsViewer();
  var scope = source.scope || '';
  var secretLine = source.secret_env
    ? '<span class="subscription-badge">密钥变量 ' + escapeHtml(source.secret_env) + '</span>'
    : '';
  var action = subscribed
    ? '<button type="button" data-unsubscribe-source="' + escapeHtml(source.id) + '"' + (viewer ? ' disabled' : '') + '>取消订阅</button>'
    : '<button class="primary" type="button" data-subscribe-source="' + escapeHtml(source.id) + '"' + (viewer ? ' disabled' : '') + '>订阅</button>';
  return [
    '<article class="subscription-card">',
    '  <div class="subscription-card-head">',
    '    <div>',
    '      <h4>' + escapeHtml(source.display_name || source.type || '未命名源') + '</h4>',
    '      <div class="subscription-meta">',
    '        <span>' + escapeHtml(source.type || 'source') + '</span>',
    '        <span>' + escapeHtml(source.default_channel || '未设置频道') + '</span>',
    '      </div>',
    '    </div>',
    '    <span class="subscription-badge ' + escapeHtml(scope) + '">' + escapeHtml(sourceScopeLabel(scope)) + '</span>',
    '  </div>',
    source.description ? '<p class="subscription-muted">' + escapeHtml(source.description) + '</p>' : '',
    '  <div class="subscription-meta">',
    '    <span class="subscription-badge">' + escapeHtml(topicText(source.default_topics)) + '</span>',
    secretLine,
    subscribed ? '<span class="subscription-badge">已订阅</span>' : '',
    '  </div>',
    '  <div class="subscription-card-actions">',
    action,
    '    <button type="button" data-source-test="' + escapeHtml(source.id) + '"' + (viewer ? ' disabled' : '') + '>测试</button>',
    '    <button type="button" data-source-fetch="' + escapeHtml(source.id) + '"' + (viewer ? ' disabled' : '') + '>抓取</button>',
    '  </div>',
    '</article>',
  ].join('');
}

function renderSubscriptionCard(subscription) {
  var viewer = subscriptionUserIsViewer();
  var enabled = subscription.enabled !== false;
  return [
    '<article class="subscription-card">',
    '  <div class="subscription-card-head">',
    '    <div>',
    '      <h4>' + escapeHtml(subscription.source_display_name || subscription.source_id || '订阅源') + '</h4>',
    '      <div class="subscription-meta">',
    '        <span>' + escapeHtml(subscription.source_type || 'source') + '</span>',
    '        <span>' + escapeHtml(subscription.override_channel || '使用源默认频道') + '</span>',
    '      </div>',
    '    </div>',
    '    <span class="subscription-badge ' + (enabled ? '' : 'disabled') + '">' + (enabled ? '启用' : '停用') + '</span>',
    '  </div>',
    '  <div class="subscription-meta">',
    '    <span class="subscription-badge">' + escapeHtml(topicText(subscription.override_topics)) + '</span>',
    '    <span class="subscription-badge">' + escapeHtml(subscription.analysis_mode || 'full') + '</span>',
    '    <span class="subscription-badge">优先级 ' + escapeHtml(String(subscription.priority || 0)) + '</span>',
    '  </div>',
    '  <div class="subscription-card-actions">',
    '    <button type="button" data-toggle-subscription="' + escapeHtml(subscription.id) + '" data-enabled="' + (enabled ? '0' : '1') + '"' + (viewer ? ' disabled' : '') + '>' + (enabled ? '停用' : '启用') + '</button>',
    '    <button type="button" data-unsubscribe-source="' + escapeHtml(subscription.source_id) + '"' + (viewer ? ' disabled' : '') + '>取消订阅</button>',
    '  </div>',
    '</article>',
  ].join('');
}

function privateSourceTopicOptions() {
  var tags = [];
  if (typeof getConfigTagLibrary === 'function') {
    tags = getConfigTagLibrary();
  }
  if (!tags.length && state.config && Array.isArray(state.config.tags)) {
    tags = state.config.tags;
  }
  if (!tags.length) tags = TAG_LIBRARY_OPTIONS;
  return tags.slice(0, 18);
}

function renderPrivateSourceForm() {
  var viewer = subscriptionUserIsViewer();
  var channelOptions = HUB_CHANNEL_OPTIONS.map(function (channel) {
    return '<option value="' + escapeHtml(channel) + '">' + escapeHtml(channel) + '</option>';
  }).join('');
  var topicOptions = privateSourceTopicOptions().map(function (topic) {
    return [
      '<label>',
      '  <input type="checkbox" name="default_topics" value="' + escapeHtml(topic) + '"' + (viewer ? ' disabled' : '') + ' />',
      '  <span>' + escapeHtml(topic) + '</span>',
      '</label>',
    ].join('');
  }).join('');
  return [
    '<form id="privateSourceForm" class="private-source-form">',
    '  <label class="field"><span>名称</span><input name="display_name" type="text" placeholder="我的 RSS 源" required' + (viewer ? ' disabled' : '') + ' /></label>',
    '  <label class="field"><span>RSS URL</span><input name="feed_url" type="url" placeholder="https://example.com/feed.xml" required' + (viewer ? ' disabled' : '') + ' /></label>',
    '  <label class="field"><span>Hub 频道</span><select name="default_channel"' + (viewer ? ' disabled' : '') + '>' + channelOptions + '</select></label>',
    '  <label class="field"><span>密钥环境变量名</span><input name="secret_env" type="text" placeholder="RSS_PRIVATE_TOKEN" autocomplete="off"' + (viewer ? ' disabled' : '') + ' /></label>',
    '  <div class="subscription-topic-list" aria-label="阅读主题">' + topicOptions + '</div>',
    '  <div class="form-actions"><button type="submit"' + (viewer ? ' disabled' : '') + '>创建并订阅</button></div>',
    '</form>',
  ].join('');
}

function renderAdvancedSourceForm(sourceTypes) {
  var viewer = subscriptionUserIsViewer();
  var types = sourceTypes && sourceTypes.length ? sourceTypes : [
    { type: 'github_release', label: 'GitHub Releases', template: { owner: 'openai', repo: 'codex' } },
  ];
  var first = types[0] || {};
  var typeOptions = types.map(function (sourceType) {
    return '<option value="' + escapeHtml(sourceType.type) + '">' + escapeHtml(sourceType.label || sourceType.type) + '</option>';
  }).join('');
  var channelOptions = HUB_CHANNEL_OPTIONS.map(function (channel) {
    return '<option value="' + escapeHtml(channel) + '">' + escapeHtml(channel) + '</option>';
  }).join('');
  var template = JSON.stringify(first.template || {}, null, 2);
  return [
    '<form id="advancedSourceForm" class="advanced-source-form">',
    '  <label class="field"><span>source_type</span><select name="source_type"' + (viewer ? ' disabled' : '') + '>' + typeOptions + '</select></label>',
    '  <label class="field"><span>显示名称</span><input name="display_name" type="text" placeholder="高级源名称"' + (viewer ? ' disabled' : '') + ' /></label>',
    '  <label class="field"><span>Hub 频道</span><select name="default_channel"' + (viewer ? ' disabled' : '') + '><option value="">不设置</option>' + channelOptions + '</select></label>',
    '  <label class="field"><span>密钥环境变量名</span><input name="secret_env" type="text" placeholder="GITHUB_TOKEN / APIFY_TOKEN" autocomplete="off"' + (viewer ? ' disabled' : '') + ' /></label>',
    '  <label class="field wide"><span>config JSON</span><textarea name="config_json" rows="8" spellcheck="false"' + (viewer ? ' disabled' : '') + '>' + escapeHtml(template) + '</textarea></label>',
    '  <label class="field wide"><span>默认主题（逗号分隔）</span><input name="default_topics" type="text" placeholder="AI Agent, 产品机会"' + (viewer ? ' disabled' : '') + ' /></label>',
    '  <div class="form-actions"><button type="submit"' + (viewer ? ' disabled' : '') + '>创建并订阅</button></div>',
    '</form>',
  ].join('');
}

function renderJobs(jobs) {
  var visibleJobs = (jobs || []).slice(0, 8);
  if (!visibleJobs.length) return '<div class="empty">暂无任务。</div>';
  return [
    '<div class="subscription-job-list">',
    visibleJobs.map(function (job) {
      var canCancel = job.status === 'queued' && !subscriptionUserIsViewer();
      var canRetry = ['failed', 'partial', 'cancelled'].indexOf(job.status) >= 0 && !subscriptionUserIsViewer();
      return [
        '<div class="subscription-job-row">',
        '  <strong>' + escapeHtml(job.id || '') + '</strong>',
        '  <span>' + escapeHtml(jobTypeLabel(job.job_type)) + '</span>',
        '  <span>' + escapeHtml(job.status || '') + '</span>',
        '  <span>' + escapeHtml(String(job.attempts || 0)) + ' / ' + escapeHtml(String(job.max_attempts || 1)) + '</span>',
        '  <span>' + escapeHtml(formatDate(job.updated_at || job.created_at)) + '</span>',
        job.error_message ? '  <span class="subscription-job-error">' + escapeHtml(job.error_message) + '</span>' : '',
        '  <div class="subscription-job-actions">',
        canCancel ? '    <button type="button" data-cancel-job="' + escapeHtml(job.id) + '">取消</button>' : '',
        canRetry ? '    <button type="button" data-retry-job="' + escapeHtml(job.id) + '">重试</button>' : '',
        '  </div>',
        '</div>',
      ].join('');
    }).join(''),
    '</div>',
  ].join('');
}

function percentText(value) {
  var number = Number(value || 0);
  if (!Number.isFinite(number)) number = 0;
  return Math.round(number * 100) + '%';
}

function renderApiStatus(apiStatus, summary) {
  apiStatus = apiStatus || {};
  summary = summary || {};
  var snapshots = (apiStatus.history && apiStatus.history.snapshots) || [];
  var latest = snapshots[0] || {};
  var qualityRows = (apiStatus.sourceQuality || []).slice(0, 5);
  return [
    '<div class="subscription-api-status">',
    '  <div class="subscription-api-metrics">',
    '    <div><span>最新 snapshot</span><strong>' + escapeHtml(formatDate(latest.generated_at || summary.latest_generated_at || '')) + '</strong></div>',
    '    <div><span>可见 item</span><strong>' + escapeHtml(String(latest.item_count != null ? latest.item_count : 0)) + '</strong></div>',
    '    <div><span>失败任务</span><strong>' + escapeHtml(String(summary.failed_job_count || 0)) + '</strong></div>',
    '  </div>',
    qualityRows.length ? [
      '  <div class="subscription-quality-list">',
      qualityRows.map(function (row) {
        return [
          '    <div>',
          '      <strong>' + escapeHtml(row.source || 'unknown') + '</strong>',
          '      <span>' + escapeHtml(String(row.total_items || 0)) + ' 条 · 命中 ' + escapeHtml(percentText(row.hit_rate)) + ' · 空主题 ' + escapeHtml(percentText(row.empty_topics_rate)) + '</span>',
          '    </div>',
        ].join('');
      }).join(''),
      '  </div>',
    ].join('') : '  <div class="empty">还没有用户作用域归档数据。</div>',
    '</div>',
  ].join('');
}

function renderSubscriptionConsole(data) {
  data = data || {};
  var summary = data.summary || {};
  var sources = data.sources || [];
  var subscriptions = data.subscriptions || [];
  var jobs = data.jobs || [];
  var apiStatus = data.apiStatus || {};
  var sourceTypes = data.sourceTypes || [];
  var subscribedBySource = subscriptionSourceMap(subscriptions);
  var user = summary.current_user || state.auth.user || {};
  var viewer = subscriptionUserIsViewer();
  var admin = subscriptionUserIsAdmin();
  document.getElementById('subscriptionSummary').textContent = [
    user.username || state.auth.username || '当前用户',
    user.role || '',
    '可见源 ' + (summary.source_count != null ? summary.source_count : sources.length),
    '我的订阅 ' + (summary.subscription_count != null ? summary.subscription_count : subscriptions.length),
    '队列 ' + (summary.queued_job_count || 0),
  ].filter(Boolean).join(' · ');
  document.getElementById('refreshMyFeedBtn').disabled = viewer;

  document.getElementById('subscriptionConsole').innerHTML = [
    '<section class="subscription-section">',
    '  <div class="subscription-section-head"><h3>公共源市场</h3><span>' + sources.length + ' 个可见源</span></div>',
    sources.length ? '<div class="subscription-card-grid">' + sources.map(function (source) {
      return renderSourceCard(source, subscribedBySource[source.id]);
    }).join('') + '</div>' : '<div class="empty">还没有公共或私有源。</div>',
    '</section>',
    '<section class="subscription-section">',
    '  <div class="subscription-section-head"><h3>我的订阅</h3><span>' + subscriptions.length + ' 个</span></div>',
    subscriptions.length ? '<div class="subscription-card-grid">' + subscriptions.map(renderSubscriptionCard).join('') + '</div>' : '<div class="empty">还没有订阅。可以从公共源市场订阅。</div>',
    '</section>',
    '<section class="subscription-section">',
    '  <div class="subscription-section-head"><h3>私有 RSS 源</h3><span>' + (viewer ? 'viewer 只读' : '仅自己可见') + '</span></div>',
    renderPrivateSourceForm(),
    '</section>',
    '<section class="subscription-section">',
    '  <div class="subscription-section-head"><h3>高级源测试</h3><span>' + sourceTypes.length + ' 种 source_type</span></div>',
    admin ? '<div class="subscription-actions"><button type="button" data-import-config-sources>导入旧配置源</button></div>' : '',
    renderAdvancedSourceForm(sourceTypes),
    '</section>',
    '<section class="subscription-section">',
    '  <div class="subscription-section-head"><h3>API 状态</h3><span>用户作用域 feed / archive</span></div>',
    renderApiStatus(apiStatus, summary),
    '</section>',
    '<section class="subscription-section">',
    '  <div class="subscription-section-head"><h3>任务队列</h3><span>' + jobs.length + ' 条最近任务</span></div>',
    renderJobs(jobs),
    '</section>',
  ].join('');
}

async function subscribeToSource(sourceId) {
  if (!sourceId) return;
  setSubscriptionMessage('正在订阅...', '');
  try {
    await fetchSubscriptionApi('/api/catalog/sources/' + encodeURIComponent(sourceId) + '/subscribe', {
      method: 'POST',
    });
    state.subscriptionConsoleLoaded = false;
    setSubscriptionMessage('订阅已更新。', '');
    await loadSubscriptionConsole();
  } catch (err) {
    setSubscriptionMessage('订阅失败：' + err.message, 'error');
  }
}

async function unsubscribeFromSource(sourceId) {
  if (!sourceId) return;
  setSubscriptionMessage('正在取消订阅...', '');
  try {
    await fetchSubscriptionApi('/api/catalog/sources/' + encodeURIComponent(sourceId) + '/subscription', {
      method: 'DELETE',
    });
    state.subscriptionConsoleLoaded = false;
    setSubscriptionMessage('已取消订阅。', '');
    await loadSubscriptionConsole();
  } catch (err) {
    setSubscriptionMessage('取消订阅失败：' + err.message, 'error');
  }
}

async function toggleSubscription(subscriptionId, enabled) {
  if (!subscriptionId) return;
  setSubscriptionMessage('正在更新订阅...', '');
  try {
    await fetchSubscriptionApi('/api/me/subscriptions/' + encodeURIComponent(subscriptionId), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !!enabled }),
    });
    state.subscriptionConsoleLoaded = false;
    setSubscriptionMessage('订阅状态已更新。', '');
    await loadSubscriptionConsole();
  } catch (err) {
    setSubscriptionMessage('更新订阅失败：' + err.message, 'error');
  }
}

async function queueSourceJob(sourceId, kind) {
  if (!sourceId) return;
  var endpoint = kind === 'source_fetch' ? '/api/jobs/source-fetch' : '/api/jobs/source-test';
  setSubscriptionMessage('正在创建任务...', '');
  try {
    var job = await fetchSubscriptionApi(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_id: sourceId, payload: { reason: 'subscription_console' } }),
    });
    setSubscriptionMessage('任务已排队：' + job.id, '');
    await loadJobsPreview();
  } catch (err) {
    setSubscriptionMessage('创建任务失败：' + err.message, 'error');
  }
}

async function refreshMyFeed() {
  setSubscriptionMessage('正在创建刷新任务...', '');
  try {
    var job = await fetchSubscriptionApi('/api/jobs/user-feed-refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ payload: { reason: 'manual_subscription_console' } }),
    });
    setSubscriptionMessage('任务已排队：' + job.id, '');
    await loadJobsPreview();
  } catch (err) {
    setSubscriptionMessage('刷新任务失败：' + err.message, 'error');
  }
}

async function loadJobsPreview() {
  try {
    var data = await fetchSubscriptionApi('/api/jobs?limit=20&ts=' + Date.now());
    state.subscriptionConsole = state.subscriptionConsole || {};
    state.subscriptionConsole.jobs = data.jobs || [];
    renderSubscriptionConsole(state.subscriptionConsole);
  } catch (err) {
    setSubscriptionMessage('任务列表读取失败：' + err.message, 'error');
  }
}

async function cancelJob(jobId) {
  if (!jobId) return;
  setSubscriptionMessage('正在取消任务...', '');
  try {
    var job = await fetchSubscriptionApi('/api/jobs/' + encodeURIComponent(jobId) + '/cancel', {
      method: 'POST',
    });
    setSubscriptionMessage('任务已取消：' + job.id, '');
    await loadJobsPreview();
  } catch (err) {
    setSubscriptionMessage('取消任务失败：' + err.message, 'error');
  }
}

async function retryJob(jobId) {
  if (!jobId) return;
  setSubscriptionMessage('正在重试任务...', '');
  try {
    var job = await fetchSubscriptionApi('/api/jobs/' + encodeURIComponent(jobId) + '/retry', {
      method: 'POST',
    });
    setSubscriptionMessage('任务已重新排队：' + job.id, '');
    await loadJobsPreview();
  } catch (err) {
    setSubscriptionMessage('重试任务失败：' + err.message, 'error');
  }
}

async function createPrivateSource(event) {
  event.preventDefault();
  var form = event.target.closest('form');
  if (!form) return;
  var topics = Array.from(form.querySelectorAll('input[name="default_topics"]:checked')).map(function (item) {
    return item.value;
  });
  var payload = {
    scope: "private",
    type: 'rss',
    display_name: form.elements.display_name.value.trim(),
    default_channel: form.elements.default_channel.value,
    default_topics: topics,
    config: {
      name: form.elements.display_name.value.trim(),
      url: form.elements.feed_url.value.trim(),
    },
    secret_env: form.elements.secret_env.value.trim() || null,
    enabled: true,
  };
  setSubscriptionMessage('正在创建私有源...', '');
  try {
    var source = await fetchSubscriptionApi('/api/catalog/sources', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    await fetchSubscriptionApi('/api/catalog/sources/' + encodeURIComponent(source.id) + '/subscribe', {
      method: 'POST',
    });
    form.reset();
    state.subscriptionConsoleLoaded = false;
    setSubscriptionMessage('私有源已创建并订阅。', '');
    await loadSubscriptionConsole();
  } catch (err) {
    setSubscriptionMessage('创建私有源失败：' + err.message, 'error');
  }
}

async function createAdvancedSource(event) {
  event.preventDefault();
  var form = event.target.closest('form');
  if (!form) return;
  var config = {};
  try {
    config = JSON.parse(form.elements.config_json.value || '{}');
  } catch (err) {
    setSubscriptionMessage('config JSON 解析失败：' + err.message, 'error');
    return;
  }
  var topics = (form.elements.default_topics.value || '')
    .split(',')
    .map(function (item) { return item.trim(); })
    .filter(Boolean);
  var sourceType = form.elements.source_type.value;
  var payload = {
    type: sourceType,
    display_name: form.elements.display_name.value.trim() || sourceType,
    default_channel: form.elements.default_channel.value || null,
    default_topics: topics,
    config: config,
    secret_env: form.elements.secret_env.value.trim() || null,
    enabled: true,
  };
  setSubscriptionMessage('正在创建高级源...', '');
  try {
    var source = await fetchSubscriptionApi('/api/catalog/sources', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    await fetchSubscriptionApi('/api/catalog/sources/' + encodeURIComponent(source.id) + '/subscribe', {
      method: 'POST',
    });
    state.subscriptionConsoleLoaded = false;
    setSubscriptionMessage('高级源已创建并订阅。', '');
    await loadSubscriptionConsole();
  } catch (err) {
    setSubscriptionMessage('创建高级源失败：' + err.message, 'error');
  }
}

async function importConfigSources() {
  setSubscriptionMessage('正在导入旧配置源...', '');
  try {
    var result = await fetchSubscriptionApi('/api/catalog/import-config-sources', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subscribe_current_user: true }),
    });
    state.subscriptionConsoleLoaded = false;
    setSubscriptionMessage(
      '导入完成：新建 ' + result.created + '，更新 ' + result.updated + '，跳过 ' + result.skipped + '。',
      result.errors && result.errors.length ? 'error' : ''
    );
    await loadSubscriptionConsole();
  } catch (err) {
    setSubscriptionMessage('导入失败：' + err.message, 'error');
  }
}

function bindSubscriptionEvents() {
  var panel = document.getElementById('subscriptionPanel');
  if (!panel) return;
  document.getElementById('reloadSubscriptionsBtn').addEventListener('click', function () {
    state.subscriptionConsoleLoaded = false;
    loadSubscriptionConsole();
  });
  document.getElementById('refreshMyFeedBtn').addEventListener('click', refreshMyFeed);
  panel.addEventListener('submit', function (event) {
    if (event.target && event.target.id === 'privateSourceForm') {
      createPrivateSource(event);
    }
    if (event.target && event.target.id === 'advancedSourceForm') {
      createAdvancedSource(event);
    }
  });
  panel.addEventListener('click', function (event) {
    var importButton = event.target.closest('[data-import-config-sources]');
    if (importButton) {
      importConfigSources();
      return;
    }
    var subscribeButton = event.target.closest('[data-subscribe-source]');
    if (subscribeButton) {
      subscribeToSource(subscribeButton.getAttribute('data-subscribe-source'));
      return;
    }
    var unsubscribeButton = event.target.closest('[data-unsubscribe-source]');
    if (unsubscribeButton) {
      unsubscribeFromSource(unsubscribeButton.getAttribute('data-unsubscribe-source'));
      return;
    }
    var toggleButton = event.target.closest('[data-toggle-subscription]');
    if (toggleButton) {
      toggleSubscription(
        toggleButton.getAttribute('data-toggle-subscription'),
        toggleButton.getAttribute('data-enabled') === '1'
      );
      return;
    }
    var testButton = event.target.closest('[data-source-test]');
    if (testButton) {
      queueSourceJob(testButton.getAttribute('data-source-test'), 'source_test');
      return;
    }
    var fetchButton = event.target.closest('[data-source-fetch]');
    if (fetchButton) {
      queueSourceJob(fetchButton.getAttribute('data-source-fetch'), 'source_fetch');
      return;
    }
    var cancelButton = event.target.closest('[data-cancel-job]');
    if (cancelButton) {
      cancelJob(cancelButton.getAttribute('data-cancel-job'));
      return;
    }
    var retryButton = event.target.closest('[data-retry-job]');
    if (retryButton) {
      retryJob(retryButton.getAttribute('data-retry-job'));
    }
  });
}
