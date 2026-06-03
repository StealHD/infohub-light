(function () {
  'use strict';

  var state = {
    data: null,
    view: 'featured',
    query: '',
    minScore: 0,
    tag: '',
    source: '',
    favoritesOnly: false,
    favorites: loadFavorites(),
    configLoaded: false,
    config: null,
    historyData: null,
  };

  function loadFavorites() {
    try {
      return new Set(JSON.parse(localStorage.getItem('ai-radar-favorites') || '[]'));
    } catch (err) {
      return new Set();
    }
  }

  function saveFavorites() {
    try {
      localStorage.setItem('ai-radar-favorites', JSON.stringify(Array.from(state.favorites)));
    } catch (err) {
      /* ignore storage failures */
    }
  }

  function escapeHtml(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatDate(value) {
    if (!value) return '未知';
    var date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat('zh-CN', {
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(date);
  }

  function scoreClass(score) {
    if (score >= 8.5) return 'score-high';
    if (score >= 7.5) return 'score-featured';
    if (score >= 6) return 'score-mid';
    return 'score-low';
  }

  function getBaseItems() {
    if (!state.data) return [];
    if (state.view === 'history') return (state.historyData || state.data).items || [];
    if (state.view === 'daily') return state.data.daily_push_items || [];
    if (state.view === 'featured') return state.data.featured_items || [];
    return state.data.items || [];
  }

  function getActiveData() {
    if (state.view === 'history' && state.historyData) return state.historyData;
    return state.data;
  }

  function matchesQuery(item) {
    if (!state.query) return true;
    var haystack = [
      item.title,
      item.source,
      item.summary_zh,
      item.reason,
      item.action_suggestion,
      item.category,
      (item.tags || []).join(' '),
    ].join(' ').toLowerCase();
    return haystack.indexOf(state.query.toLowerCase()) !== -1;
  }

  function getFilteredItems() {
    return getBaseItems().filter(function (item) {
      if ((item.score || 0) < state.minScore) return false;
      if (state.tag && (item.tags || []).indexOf(state.tag) === -1) return false;
      if (state.source && item.source !== state.source) return false;
      if (state.favoritesOnly && !state.favorites.has(item.id)) return false;
      return matchesQuery(item);
    });
  }

  function renderSelectOptions(select, values, allLabel) {
    var current = select.value;
    select.innerHTML = '<option value="">' + allLabel + '</option>' +
      values.map(function (value) {
        return '<option value="' + escapeHtml(value) + '">' + escapeHtml(value) + '</option>';
      }).join('');
    select.value = values.indexOf(current) >= 0 ? current : '';
  }

  function renderMeta() {
    var metaLine = document.getElementById('metaLine');
    var data = getActiveData();
    if (!data) {
      metaLine.textContent = '等待数据';
      return;
    }
    var thresholds = data.thresholds || {};
    var countText = (state.view === 'history')
      ? '历史累计 ' + ((data.items || []).length) + ' 条'
      : data.history_total_items
        ? '最新 ' + ((data.items || []).length) + ' 条 / 历史 ' + data.history_total_items + ' 条'
        : '抓取 ' + (data.total_fetched || 0) + ' 条';
    metaLine.textContent = [
      data.date || '未知日期',
      countText,
      '精选 ≥ ' + (thresholds.featured || 7.5),
      '推送 ≥ ' + (thresholds.daily_push || 8.5),
    ].join(' · ');
  }

  function renderSummaryStrip(items) {
    var el = document.getElementById('summaryStrip');
    if (state.view === 'config') {
      el.innerHTML = '<span>表单化配置</span><span>密钥只从 .env 读取</span>';
      return;
    }
    var data = getActiveData();
    if (!data) {
      el.innerHTML = '';
      return;
    }
    var label = state.view === 'daily'
      ? '每日推送'
      : state.view === 'featured'
        ? '精选'
        : state.view === 'history'
          ? '历史'
          : '全部';
    el.innerHTML = [
      '<span>' + label + '：' + items.length + ' 条</span>',
      '<span>收藏：' + state.favorites.size + ' 条</span>',
      '<span>标签：' + (data.tags || []).length + ' 个</span>',
      '<span>来源：' + (data.sources || []).length + ' 个</span>',
    ].join('');
  }

  function renderTags(tags) {
    return (tags || []).slice(0, 6).map(function (tag) {
      return '<span class="tag">#' + escapeHtml(tag) + '</span>';
    }).join('');
  }

  function renderItem(item) {
    var favored = state.favorites.has(item.id);
    var discussion = item.discussion_url
      ? '<a href="' + escapeHtml(item.discussion_url) + '" target="_blank" rel="noreferrer">关联讨论</a>'
      : '';
    return [
      '<article class="item">',
      '  <div class="item-head">',
      '    <div>',
      '      <h2>' + escapeHtml(item.title) + '</h2>',
      '      <div class="meta">' + escapeHtml(item.source) + ' · ' + formatDate(item.published_at) + '</div>',
      '    </div>',
      '    <div class="item-actions">',
      '      <span class="score ' + scoreClass(item.score || 0) + '">' + (item.score || 0).toFixed(1) + '</span>',
      '      <button class="favorite' + (favored ? ' active' : '') + '" type="button" data-favorite="' + escapeHtml(item.id) + '" title="收藏">' + (favored ? '已收藏' : '收藏') + '</button>',
      '    </div>',
      '  </div>',
      '  <div class="tags">' + renderTags(item.tags) + '</div>',
      '  <p class="summary">' + escapeHtml(item.summary_zh || '暂无摘要') + '</p>',
      '  <p class="reason"><strong>推荐理由</strong> ' + escapeHtml(item.reason || '暂无') + '</p>',
      '  <p class="action"><strong>我该关注什么</strong> ' + escapeHtml(item.action_suggestion || '阅读原文后判断是否需要跟进。') + '</p>',
      '  <div class="links">',
      '    <a href="' + escapeHtml(item.url) + '" target="_blank" rel="noreferrer">原文链接</a>',
      discussion,
      '  </div>',
      '</article>',
    ].join('');
  }

  function renderItems() {
    var configPanel = document.getElementById('configPanel');
    var list = document.getElementById('itemsList');
    if (state.view === 'config') {
      list.classList.add('hidden');
      configPanel.classList.remove('hidden');
      renderSummaryStrip([]);
      if (!state.configLoaded) loadConfig();
      return;
    }

    configPanel.classList.add('hidden');
    list.classList.remove('hidden');
    var items = getFilteredItems();
    renderSummaryStrip(items);
    if (!items.length) {
      list.innerHTML = '<div class="empty">没有匹配的动态。</div>';
      return;
    }
    list.innerHTML = items.map(renderItem).join('');
  }

  function renderAll() {
    var data = getActiveData();
    if (data) {
      renderSelectOptions(document.getElementById('tagSelect'), data.tags || [], '全部标签');
      renderSelectOptions(document.getElementById('sourceSelect'), data.sources || [], '全部来源');
    }
    renderMeta();
    renderItems();
  }

  function bindEvents() {
    document.getElementById('refreshBtn').addEventListener('click', loadData);
    document.getElementById('clearFiltersBtn').addEventListener('click', clearFilters);
    document.getElementById('reloadConfigBtn').addEventListener('click', function () {
      state.configLoaded = false;
      loadConfig();
    });
    document.getElementById('configForms').addEventListener('submit', handleConfigFormSubmit);
    document.getElementById('configForms').addEventListener('click', handleConfigFormClick);
    document.getElementById('configForms').addEventListener('change', handleConfigFormChange);
    document.getElementById('searchInput').addEventListener('input', function (event) {
      state.query = event.target.value.trim();
      renderItems();
    });
    document.getElementById('minScoreInput').addEventListener('input', function (event) {
      state.minScore = parseFloat(event.target.value) || 0;
      document.getElementById('minScoreValue').textContent = state.minScore.toFixed(1);
      renderItems();
    });
    document.getElementById('tagSelect').addEventListener('change', function (event) {
      state.tag = event.target.value;
      renderItems();
    });
    document.getElementById('sourceSelect').addEventListener('change', function (event) {
      state.source = event.target.value;
      renderItems();
    });
    document.getElementById('favoritesOnly').addEventListener('change', function (event) {
      state.favoritesOnly = event.target.checked;
      renderItems();
    });
    document.querySelectorAll('.tab').forEach(function (button) {
      button.addEventListener('click', function () {
        document.querySelectorAll('.tab').forEach(function (tab) { tab.classList.remove('active'); });
        button.classList.add('active');
        state.view = button.dataset.view;
        renderAll();
      });
    });
    document.getElementById('itemsList').addEventListener('click', function (event) {
      var button = event.target.closest('[data-favorite]');
      if (!button) return;
      var id = button.getAttribute('data-favorite');
      if (state.favorites.has(id)) state.favorites.delete(id);
      else state.favorites.add(id);
      saveFavorites();
      renderItems();
    });
  }

  function clearFilters() {
    state.query = '';
    state.minScore = 0;
    state.tag = '';
    state.source = '';
    state.favoritesOnly = false;
    document.getElementById('searchInput').value = '';
    document.getElementById('minScoreInput').value = '0';
    document.getElementById('minScoreValue').textContent = '0';
    document.getElementById('tagSelect').value = '';
    document.getElementById('sourceSelect').value = '';
    document.getElementById('favoritesOnly').checked = false;
    if (state.view === 'config') {
      state.view = 'featured';
      document.querySelectorAll('.tab').forEach(function (tab) {
        tab.classList.toggle('active', tab.dataset.view === 'featured');
      });
    }
    renderAll();
  }

  function renderEnvStatus(items) {
    var el = document.getElementById('envStatus');
    if (!items || !items.length) {
      el.innerHTML = '<div class="env-item">没有发现配置引用的环境变量。</div>';
      return;
    }
    el.innerHTML = items.map(function (item) {
      return [
        '<div class="env-item">',
        '<span class="env-dot ' + (item.set ? 'ok' : 'missing') + '"></span>',
        '<strong>' + escapeHtml(item.name) + '</strong>',
        '<span>' + (item.set ? '已设置' : '未设置') + '</span>',
        '<small>' + escapeHtml((item.used_by || []).join(', ')) + '</small>',
        '</div>',
      ].join('');
    }).join('');
  }

  function checked(value) {
    return value ? ' checked' : '';
  }

  function selected(current, value) {
    return String(current || '') === String(value) ? ' selected' : '';
  }

  function inputValue(value) {
    return escapeHtml(value == null ? '' : value);
  }

  function renderConfigForms(config) {
    var forms = document.getElementById('configForms');
    forms.innerHTML = [
      renderAiForm(config.ai || {}),
      renderTagLibraryForm(config.tags || []),
      renderFilteringForm(config.filtering || {}),
      renderWebhookForm(config.webhook || {}),
      renderHackerNewsForm((config.sources || {}).hackernews || {}),
      renderNewSourceForm(),
      renderExistingSources(config.sources || {}),
    ].join('');
  }

  function renderTagLibraryForm(tags) {
    return [
      '<section class="config-card">',
      '<h3>标签库</h3>',
      '<form data-action="set_tags" class="config-grid">',
      fieldTextarea('tags', '可选标签，逗号或换行分隔', (tags || []).join('\\n')),
      '<div class="tag-hints">' + (tags || []).map(function (tag) {
        return '<span class="tag">#' + escapeHtml(tag) + '</span>';
      }).join('') + '</div>',
      '<div class="form-actions"><button type="submit">保存标签库</button></div>',
      '</form>',
      '</section>',
    ].join('');
  }

  function renderAiForm(ai) {
    return [
      '<section class="config-card">',
      '<h3>AI 模型</h3>',
      '<form data-action="set_ai" class="config-grid">',
      fieldSelect('provider', 'Provider', ai.provider || 'openai', ['openai', 'anthropic', 'gemini', 'xiaomi', 'deepseek', 'minimax', 'ali', 'doubao', 'azure', 'ollama']),
      fieldInput('model', 'Model', ai.model || '', 'text'),
      fieldInput('api_key_env', 'API Key 环境变量名', ai.api_key_env || 'OPENAI_API_KEY', 'text'),
      fieldInput('base_url', 'Base URL 可选', ai.base_url || '', 'url'),
      fieldInput('languages', '输出语言，逗号分隔', (ai.languages || ['zh']).join(','), 'text'),
      '<div class="form-actions"><button type="submit">保存 AI 设置</button></div>',
      '</form>',
      '</section>',
    ].join('');
  }

  function renderFilteringForm(filtering) {
    return [
      '<section class="config-card">',
      '<h3>评分和展示阈值</h3>',
      '<form data-action="set_filtering" class="config-grid">',
      fieldInput('ai_score_threshold', '兼容阈值', filtering.ai_score_threshold || 7.5, 'number', '0.5', '0', '10'),
      fieldInput('featured_score_threshold', '精选阈值', filtering.featured_score_threshold || 7.5, 'number', '0.5', '0', '10'),
      fieldInput('daily_push_score_threshold', '每日推送阈值', filtering.daily_push_score_threshold || 8.5, 'number', '0.5', '0', '10'),
      fieldInput('daily_push_limit', '每日推送条数', filtering.daily_push_limit || 10, 'number', '1', '1', '50'),
      fieldInput('homepage_min_score', '首页最低分', filtering.homepage_min_score || 6, 'number', '0.5', '0', '10'),
      fieldInput('time_window_hours', '抓取时间窗口小时', filtering.time_window_hours || 24, 'number', '1', '1', '720'),
      fieldInput('recent_item_limit', '最新动态条数', filtering.recent_item_limit || 20, 'number', '1', '1', '200'),
      '<div class="form-actions"><button type="submit">保存阈值</button></div>',
      '</form>',
      '</section>',
    ].join('');
  }

  function renderWebhookForm(webhook) {
    return [
      '<section class="config-card">',
      '<h3>每日推送 Webhook</h3>',
      '<form data-action="set_webhook" class="config-grid">',
      fieldCheckbox('enabled', '启用 Webhook', !!webhook.enabled),
      fieldInput('url_env', 'Webhook URL 环境变量名', webhook.url_env || 'HORIZON_WEBHOOK_URL', 'text'),
      fieldSelect('platform', '平台', webhook.platform || 'generic', ['generic', 'feishu', 'lark', 'dingtalk', 'slack', 'discord']),
      fieldSelect('delivery', '发送方式', webhook.delivery || 'summary_and_items', ['summary', 'summary_and_items']),
      fieldSelect('layout', '布局', webhook.layout || 'markdown', ['markdown', 'collapsible']),
      fieldSelect('overview_position', '总览位置', webhook.overview_position || 'last', ['first', 'last']),
      fieldInput('languages', '推送语言，逗号分隔', (webhook.languages || ['zh']).join(','), 'text'),
      fieldTextarea('request_text', '消息模板 text', ((webhook.request_body || {}).text || '#{message_title}\\n\\n#{summary?limit=3500&split=---}')),
      fieldTextarea('headers', '自定义 Headers 可选', webhook.headers || ''),
      '<input type="hidden" name="fallback_layout" value="' + inputValue(webhook.fallback_layout || 'markdown') + '">',
      '<div class="form-actions"><button type="submit">保存 Webhook</button></div>',
      '</form>',
      '</section>',
    ].join('');
  }

  function renderHackerNewsForm(hn) {
    return [
      '<section class="config-card">',
      '<h3>Hacker News</h3>',
      '<form data-action="set_hackernews" class="config-grid">',
      '<input type="hidden" name="source_type" value="hackernews">',
      fieldCheckbox('enabled', '启用 Hacker News', hn.enabled !== false),
      fieldInput('fetch_top_stories', '抓取 top stories 数量', hn.fetch_top_stories || 40, 'number', '1', '1', '500'),
      fieldInput('min_score', '最低分数', hn.min_score || 80, 'number', '1', '0'),
      '<div class="form-actions"><button type="button" data-test-source="hackernews">测试订阅</button><button type="submit">保存 HN 设置</button></div>',
      '</form>',
      '</section>',
    ].join('');
  }

  function renderNewSourceForm() {
    return [
      '<section class="config-card">',
      '<h3>新增信源</h3>',
      '<form id="newSourceForm" data-new-source="true" class="config-grid">',
      fieldSelect('source_type', '信源类型', 'rss', ['rss', 'github_release', 'github_user', 'reddit_subreddit', 'telegram_channel']),
      '<div class="dynamic-fields" data-source-fields="rss">',
      fieldInput('name', 'RSS 名称', '', 'text'),
      fieldInput('url', 'RSS/Atom URL', '', 'url'),
      fieldInput('category', '分类', '', 'text'),
      fieldInput('tags', '标签，逗号分隔', '', 'text'),
      fieldCheckbox('enabled', '启用', true),
      '</div>',
      '<div class="form-actions"><button type="button" data-test-source="new">测试订阅</button><button type="submit">新增信源</button></div>',
      '</form>',
      '</section>',
    ].join('');
  }

  function renderExistingSources(sources) {
    var parts = ['<section class="config-card"><h3>已配置的信源</h3><div class="source-list">'];
    (sources.rss || []).forEach(function (item, index) {
      parts.push(renderRssCard(item, index));
    });
    (sources.github || []).forEach(function (item, index) {
      parts.push(renderGithubCard(item, index));
    });
    (((sources.reddit || {}).subreddits) || []).forEach(function (item, index) {
      parts.push(renderRedditCard(item, index));
    });
    (((sources.telegram || {}).channels) || []).forEach(function (item, index) {
      parts.push(renderTelegramCard(item, index));
    });
    if (parts.length === 1) {
      parts.push('<div class="empty-inline">暂无信源。</div>');
    }
    parts.push('</div></section>');
    return parts.join('');
  }

  function renderRssCard(item, index) {
    return [
      '<form data-action="upsert_rss" class="source-card">',
      '<input type="hidden" name="index" value="' + index + '">',
      '<div class="source-card-head"><strong>RSS / Atom</strong><button type="button" data-delete-action="delete_rss" data-index="' + index + '">删除</button></div>',
      fieldInput('name', '名称', item.name || '', 'text'),
      fieldInput('url', 'URL', item.url || '', 'url'),
      fieldInput('category', '分类', item.category || '', 'text'),
      fieldInput('tags', '标签，逗号分隔', (item.tags || []).join(', '), 'text'),
      fieldCheckbox('enabled', '启用', item.enabled !== false),
      '<div class="form-actions"><button type="button" data-test-source="rss">测试订阅</button><button type="submit">保存</button></div>',
      '</form>',
    ].join('');
  }

  function renderGithubCard(item, index) {
    var isRelease = item.type === 'repo_releases';
    return [
      '<form data-action="' + (isRelease ? 'upsert_github_release' : 'upsert_github_user') + '" class="source-card">',
      '<input type="hidden" name="index" value="' + index + '">',
      '<div class="source-card-head"><strong>' + (isRelease ? 'GitHub Release' : 'GitHub 用户动态') + '</strong><button type="button" data-delete-action="delete_github" data-index="' + index + '">删除</button></div>',
      isRelease ? fieldInput('owner', 'Owner', item.owner || '', 'text') : fieldInput('username', 'Username', item.username || '', 'text'),
      isRelease ? fieldInput('repo', 'Repo', item.repo || '', 'text') : '',
      fieldInput('tags', '标签，逗号分隔', (item.tags || []).join(', '), 'text'),
      fieldCheckbox('enabled', '启用', item.enabled !== false),
      '<div class="form-actions"><button type="button" data-test-source="' + (isRelease ? 'github_release' : 'github_user') + '">测试订阅</button><button type="submit">保存</button></div>',
      '</form>',
    ].join('');
  }

  function renderRedditCard(item, index) {
    return [
      '<form data-action="upsert_reddit_subreddit" class="source-card">',
      '<input type="hidden" name="index" value="' + index + '">',
      '<div class="source-card-head"><strong>Reddit Subreddit</strong><button type="button" data-delete-action="delete_reddit_subreddit" data-index="' + index + '">删除</button></div>',
      fieldInput('subreddit', 'Subreddit', item.subreddit || '', 'text'),
      fieldSelect('sort', '排序', item.sort || 'hot', ['hot', 'new', 'top', 'rising']),
      fieldSelect('time_filter', '时间范围', item.time_filter || 'day', ['hour', 'day', 'week', 'month', 'year', 'all']),
      fieldInput('fetch_limit', '抓取数量', item.fetch_limit || 20, 'number', '1', '1', '100'),
      fieldInput('min_score', '最低分数', item.min_score || 10, 'number', '1', '0'),
      fieldInput('tags', '标签，逗号分隔', (item.tags || []).join(', '), 'text'),
      fieldCheckbox('enabled', '启用', item.enabled !== false),
      '<input type="hidden" name="reddit_enabled" value="true">',
      '<div class="form-actions"><button type="button" data-test-source="reddit_subreddit">测试订阅</button><button type="submit">保存</button></div>',
      '</form>',
    ].join('');
  }

  function renderTelegramCard(item, index) {
    return [
      '<form data-action="upsert_telegram_channel" class="source-card">',
      '<input type="hidden" name="index" value="' + index + '">',
      '<div class="source-card-head"><strong>Telegram 公共频道</strong><button type="button" data-delete-action="delete_telegram_channel" data-index="' + index + '">删除</button></div>',
      fieldInput('channel', 'Channel，不含 @', item.channel || '', 'text'),
      fieldInput('fetch_limit', '抓取数量', item.fetch_limit || 20, 'number', '1', '1', '100'),
      fieldInput('tags', '标签，逗号分隔', (item.tags || []).join(', '), 'text'),
      fieldCheckbox('enabled', '启用', item.enabled !== false),
      '<input type="hidden" name="telegram_enabled" value="true">',
      '<div class="form-actions"><button type="button" data-test-source="telegram_channel">测试订阅</button><button type="submit">保存</button></div>',
      '</form>',
    ].join('');
  }

  function fieldInput(name, label, value, type, step, min, max) {
    return [
      '<label class="config-field">',
      '<span>' + escapeHtml(label) + '</span>',
      '<input name="' + escapeHtml(name) + '" type="' + escapeHtml(type || 'text') + '" value="' + inputValue(value) + '"' +
        (step ? ' step="' + escapeHtml(step) + '"' : '') +
        (min != null ? ' min="' + escapeHtml(min) + '"' : '') +
        (max != null ? ' max="' + escapeHtml(max) + '"' : '') +
      '>',
      '</label>',
    ].join('');
  }

  function fieldTextarea(name, label, value) {
    return [
      '<label class="config-field config-field-wide">',
      '<span>' + escapeHtml(label) + '</span>',
      '<textarea name="' + escapeHtml(name) + '" spellcheck="false">' + escapeHtml(value || '') + '</textarea>',
      '</label>',
    ].join('');
  }

  function fieldCheckbox(name, label, value) {
    return [
      '<label class="config-check">',
      '<input name="' + escapeHtml(name) + '" type="checkbox"' + checked(value) + '>',
      '<span>' + escapeHtml(label) + '</span>',
      '</label>',
    ].join('');
  }

  function fieldSelect(name, label, value, options) {
    return [
      '<label class="config-field">',
      '<span>' + escapeHtml(label) + '</span>',
      '<select name="' + escapeHtml(name) + '">',
      options.map(function (option) {
        return '<option value="' + escapeHtml(option) + '"' + selected(value, option) + '>' + escapeHtml(option) + '</option>';
      }).join(''),
      '</select>',
      '</label>',
    ].join('');
  }

  function setConfigMessage(text, kind) {
    var el = document.getElementById('configMessage');
    el.textContent = text || '';
    el.className = 'config-message ' + (kind || '');
  }

  async function loadConfig() {
    setConfigMessage('正在读取配置...', '');
    try {
      var response = await fetch('./api/config?ts=' + Date.now());
      var payload = await response.json();
      if (!response.ok) throw new Error(payload.error || ('HTTP ' + response.status));
      document.getElementById('configPath').textContent = payload.path || 'data/config.json';
      state.config = payload.config || {};
      renderEnvStatus(payload.env_status || []);
      renderConfigForms(state.config);
      state.configLoaded = true;
      setConfigMessage('配置已读取。通过表单提交后，后端会校验并保存。', 'ok');
    } catch (err) {
      setConfigMessage('读取失败：' + err.message, 'error');
    }
  }

  function formPayload(form) {
    var payload = {};
    Array.from(new FormData(form).entries()).forEach(function (entry) {
      payload[entry[0]] = entry[1];
    });
    form.querySelectorAll('input[type="checkbox"]').forEach(function (input) {
      payload[input.name] = input.checked;
    });
    return payload;
  }

  async function submitConfigAction(action, payload) {
    setConfigMessage('正在提交...', '');
    try {
      var response = await fetch('./api/config/action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: action, payload: payload }),
      });
      var result = await response.json();
      if (!response.ok) throw new Error(result.error || ('HTTP ' + response.status));
      state.config = result.config || state.config;
      renderEnvStatus(result.env_status || []);
      renderConfigForms(state.config);
      setConfigMessage('设置成功。旧配置已备份为 config.json.bak。手动运行一次抓取后数据会刷新。', 'ok');
    } catch (err) {
      setConfigMessage('设置失败：' + err.message, 'error');
    }
  }

  function handleConfigFormSubmit(event) {
    var form = event.target.closest('form');
    if (!form) return;
    event.preventDefault();

    if (form.dataset.newSource) {
      var payload = formPayload(form);
      var type = payload.source_type;
      delete payload.source_type;
      var actionByType = {
        rss: 'upsert_rss',
        github_release: 'upsert_github_release',
        github_user: 'upsert_github_user',
        reddit_subreddit: 'upsert_reddit_subreddit',
        telegram_channel: 'upsert_telegram_channel',
      };
      submitConfigAction(actionByType[type], payload);
      return;
    }

    submitConfigAction(form.dataset.action, formPayload(form));
  }

  function handleConfigFormClick(event) {
    var testButton = event.target.closest('[data-test-source]');
    if (testButton) {
      var form = testButton.closest('form');
      var payload = formPayload(form);
      if (testButton.dataset.testSource === 'new') {
        payload.source_type = payload.source_type || 'rss';
      } else {
        payload.source_type = testButton.dataset.testSource;
      }
      testSource(payload);
      return;
    }

    var button = event.target.closest('[data-delete-action]');
    if (!button) return;
    submitConfigAction(button.dataset.deleteAction, { index: button.dataset.index });
  }

  async function testSource(payload) {
    setConfigMessage('正在测试订阅源...', '');
    try {
      var response = await fetch('./api/source/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      var result = await response.json();
      if (!response.ok) throw new Error(result.error || ('HTTP ' + response.status));
      var detail = result.sample_title
        ? ' 示例：' + result.sample_title + (result.sample_url ? ' · ' + result.sample_url : '')
        : '';
      setConfigMessage('测试成功：' + (result.message || '订阅源可用。') + detail, 'ok');
    } catch (err) {
      setConfigMessage('测试失败：' + err.message, 'error');
    }
  }

  function handleConfigFormChange(event) {
    if (event.target.name === 'source_type') {
      var fields = event.target.closest('form').querySelector('[data-source-fields]');
      fields.innerHTML = newSourceFields(event.target.value);
      return;
    }
    if (event.target.name === 'provider') {
      applyProviderDefaults(event.target.closest('form'), event.target.value);
    }
  }

  function applyProviderDefaults(form, provider) {
    if (!form || form.dataset.action !== 'set_ai') return;
    var model = form.querySelector('[name="model"]');
    var apiKeyEnv = form.querySelector('[name="api_key_env"]');
    var baseUrl = form.querySelector('[name="base_url"]');
    var defaults = {
      openai: { model: 'gpt-4o-mini', env: 'OPENAI_API_KEY', baseUrl: '' },
      anthropic: { model: 'claude-3-5-sonnet-latest', env: 'ANTHROPIC_API_KEY', baseUrl: '' },
      gemini: { model: 'gemini-2.5-flash', env: 'GOOGLE_API_KEY', baseUrl: '' },
      xiaomi: { model: 'mimo-v2.5-pro', env: 'XIAOMI_API_KEY', baseUrl: 'https://token-plan-cn.xiaomimimo.com/v1' },
      deepseek: { model: 'deepseek-chat', env: 'DEEPSEEK_API_KEY', baseUrl: '' },
      minimax: { model: 'MiniMax-Text-01', env: 'MINIMAX_API_KEY', baseUrl: '' },
      ali: { model: 'qwen-plus', env: 'DASHSCOPE_API_KEY', baseUrl: '' },
      doubao: { model: 'doubao-1-5-pro-32k-250115', env: 'DOUBAO_API_KEY', baseUrl: '' },
      azure: { model: 'your-deployment-name', env: 'AZURE_OPENAI_API_KEY', baseUrl: '' },
      ollama: { model: 'llama3.1', env: 'OLLAMA_API_KEY', baseUrl: 'http://localhost:11434/v1' },
    };
    var next = defaults[provider];
    if (!next) return;
    if (model) model.value = next.model;
    if (apiKeyEnv) apiKeyEnv.value = next.env;
    if (baseUrl) baseUrl.value = next.baseUrl;
  }

  function newSourceFields(type) {
    if (type === 'github_release') {
      return fieldInput('owner', 'Owner', '', 'text') +
        fieldInput('repo', 'Repo', '', 'text') +
        fieldInput('tags', '标签，逗号分隔', '', 'text') +
        fieldCheckbox('enabled', '启用', true);
    }
    if (type === 'github_user') {
      return fieldInput('username', 'Username', '', 'text') +
        fieldInput('tags', '标签，逗号分隔', '', 'text') +
        fieldCheckbox('enabled', '启用', true);
    }
    if (type === 'reddit_subreddit') {
      return fieldInput('subreddit', 'Subreddit', '', 'text') +
        fieldSelect('sort', '排序', 'hot', ['hot', 'new', 'top', 'rising']) +
        fieldSelect('time_filter', '时间范围', 'day', ['hour', 'day', 'week', 'month', 'year', 'all']) +
        fieldInput('fetch_limit', '抓取数量', 20, 'number', '1', '1', '100') +
        fieldInput('min_score', '最低分数', 10, 'number', '1', '0') +
        fieldInput('tags', '标签，逗号分隔', '', 'text') +
        '<input type="hidden" name="reddit_enabled" value="true">' +
        fieldCheckbox('enabled', '启用', true);
    }
    if (type === 'telegram_channel') {
      return fieldInput('channel', 'Channel，不含 @', '', 'text') +
        fieldInput('fetch_limit', '抓取数量', 20, 'number', '1', '1', '100') +
        fieldInput('tags', '标签，逗号分隔', '', 'text') +
        '<input type="hidden" name="telegram_enabled" value="true">' +
        fieldCheckbox('enabled', '启用', true);
    }
    return fieldInput('name', 'RSS 名称', '', 'text') +
      fieldInput('url', 'RSS/Atom URL', '', 'url') +
      fieldInput('category', '分类', '', 'text') +
      fieldInput('tags', '标签，逗号分隔', '', 'text') +
      fieldCheckbox('enabled', '启用', true);
  }

  async function loadData() {
    var list = document.getElementById('itemsList');
    list.innerHTML = '<div class="empty">正在读取数据...</div>';
    try {
      var response = await fetch('./radar-data.json?ts=' + Date.now());
      if (!response.ok) throw new Error('HTTP ' + response.status);
      state.data = await response.json();
      state.historyData = null;
      try {
        var historyResponse = await fetch('./history-data.json?ts=' + Date.now());
        if (historyResponse.ok) state.historyData = await historyResponse.json();
      } catch (historyErr) {
        state.historyData = null;
      }
      renderAll();
    } catch (err) {
      document.getElementById('metaLine').textContent = '未找到 radar-data.json';
      list.innerHTML = '<div class="empty">还没有生成数据。请先运行一次抓取任务。</div>';
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    bindEvents();
    loadData();
  });
})();
