// Inteliscope static UI: reader module.
function renderMeta() {
  var metaLine = document.getElementById('metaLine');
  var data = getActiveData();
  if (!data) {
    metaLine.textContent = '等待数据';
    return;
  }
  var thresholds = data.thresholds || {};
  var todayCount = getTodayTotalCount(data);
  var countText = '';
  if (state.view === 'history') {
    var historyTotal = ((data.items || []).length);
    var currentHistoryCount = getBaseItems().length;
    countText = state.historyFilter === 'all'
      ? '历史 ' + historyTotal + ' 条'
      : viewLabel() + ' ' + currentHistoryCount + ' 条 / 历史 ' + historyTotal + ' 条';
  } else {
    countText = data.history_total_items
      ? '今日 ' + todayCount + ' 条 / 历史 ' + data.history_total_items + ' 条'
      : '抓取 ' + (data.total_fetched || 0) + ' 条';
  }
  var parts = [data.date || '未知日期', countText];
  if (data.ai_enabled === false) {
    parts.push('无评分模式');
  } else {
    parts.push('精选 ≥ ' + (thresholds.featured || 7.5));
    parts.push('推送 > ' + (thresholds.daily_push || 8.5));
  }
  metaLine.textContent = parts.join(' · ');
}

function scoreBadge(item) {
  if (item && item.scoring_disabled) return '未评分';
  return scoreText((item && item.score) || 0);
}

function renderQueueStats(data, items) {
  var el = document.getElementById('queueStats');
  var isHistory = state.view === 'history';
  var featuredCount = data && Array.isArray(data.featured_items) ? data.featured_items.length : items.length;
  var todayCount = getTodayTotalCount(data);
  var readLaterCount = getReadLaterItems().length;
  var allLabel = isHistory ? '历史动态' : '今日动态';
  var featuredLabel = isHistory ? '历史精选' : '今日精选';
  var allTitle = isHistory ? '查看全部历史动态' : '查看今日全部动态';
  var featuredTitle = isHistory ? '查看历史精选' : '查看今日精选';
  function statClass(action) {
    if (!isHistory) return 'queue-stat';
    return 'queue-stat' + (state.historyFilter === action ? ' active' : '');
  }
  el.innerHTML = [
    '<button class="' + statClass('all') + '" type="button" data-stat-action="all" title="' + allTitle + '"><strong>' + todayCount + '</strong><span>' + allLabel + '</span></button>',
    '<button class="' + statClass('featured') + '" type="button" data-stat-action="featured" title="' + featuredTitle + '"><strong>' + featuredCount + '</strong><span>' + featuredLabel + '</span></button>',
    '<button class="queue-stat" type="button" data-stat-action="readLater" title="查看稍后读"><strong>' + readLaterCount + '</strong><span>稍后读</span></button>',
  ].join('');
}

function renderQueue(items, selectedItem) {
  var list = document.getElementById('itemsList');
  document.getElementById('queueTitle').textContent = viewLabel();
  document.getElementById('queueDescription').textContent = viewDescription();
  renderQueueStats(getActiveData(), items);

  if (!items.length) {
    list.innerHTML = '<div class="empty">' + escapeHtml(emptyMessage()) + '</div>';
    return;
  }

  list.innerHTML = items.map(function (item) {
    var selected = selectedItem && item.id === selectedItem.id;
    var read = itemUserState(item).is_read;
    var storyTime = formatDate(item.published_at || item.fetched_at);
    var storyMetaParts = [
      item.source || item.source_type || '未知来源',
    ];
    if (storyTime && storyTime !== '未知') storyMetaParts.push(storyTime);
    storyMetaParts.push(itemChannel(item));
    var storySignal = signalLabel(item);
    if (storySignal) storyMetaParts.push(storySignal);
    return [
      '<button class="story' + (selected ? ' selected' : '') + (read ? ' read' : '') + '" type="button" data-select-item="' + escapeHtml(item.id) + '"' + (selected ? ' aria-current="true"' : '') + '>',
      '  <div>',
      '    <div class="story-meta">' + storyMetaParts.map(function (part) { return '<span>' + escapeHtml(part) + '</span>'; }).join('') + '</div>',
      '    <h3>' + escapeHtml(item.title) + '</h3>',
      '    <p>' + escapeHtml(displayText(item.summary_zh || item.reason, '暂无摘要')) + '</p>',
      renderItemMedia(item, 'story'),
      '  </div>',
      '  <span class="score ' + scoreClass(item.score || 0) + '">' + scoreBadge(item) + '</span>',
      '</button>',
    ].join('');
  }).join('');
}

function renderTags(tags) {
  return (tags || []).slice(0, 6).map(function (tag) {
    return '<span class="tag">' + escapeHtml(tag) + '</span>';
  }).join('');
}

function itemTopics(item) {
  return (item && (item.topics || item.tags)) || [];
}

function signalLabel(item) {
  if (!item) return '';
  var strength = {
    strong: 'Strong signal',
    developing: 'Developing signal',
    thin: 'Thin signal',
  }[item.signal_strength || ''];
  var type = item.signal_type ? String(item.signal_type).replace(/_/g, ' ') : '';
  return [strength, type].filter(Boolean).join(' · ');
}

function emptyMessage() {
  if (state.view === 'readLater') return '还没有稍后读内容。点击条目里的“稍后读”即可加入。';
  return '没有匹配的动态。';
}

function renderInsightBlocks(item, actionSuggestion) {
  if (item && item.scoring_disabled) {
    return [
      '<section class="article-note">',
      '  <strong>阅读策略</strong>',
      '  <p>无评分模式：按发布时间和信源优先级阅读，打开原文后自行判断是否需要跟进。</p>',
      '</section>',
    ].join('');
  }
  return [
    '  <section class="article-block">',
    '    <h3>为什么值得读</h3>',
    '    <p>' + escapeHtml(displayText(item && item.reason, '暂无推荐理由。')) + '</p>',
    '  </section>',
    '  <section class="article-block">',
    '    <h3>我该关注什么</h3>',
    '    <p>' + escapeHtml(displayText(actionSuggestion, '阅读原文后判断是否需要跟进。')) + '</p>',
    '  </section>',
    '  <section class="article-block">',
    '    <h3>阅读判断</h3>',
    '    <p>' + escapeHtml(readingJudgement(item)) + '</p>',
    '  </section>',
  ].join('');
}

function renderReader(item) {
  var panel = document.getElementById('readerPanel');
  if (!item) {
    panel.innerHTML = '<div class="reader-toolbar">暂无可读内容</div><div class="empty">没有匹配的动态。</div>';
    return;
  }

  var userState = itemUserState(item);
  var read = userState.is_read;
  var favored = userState.is_saved;
  var later = userState.is_later;
  var dismissed = userState.dismissed;
  var actionSuggestion = item.action_suggestion || '阅读原文后判断是否需要跟进。';
  var sourceLine = [
    item.source || item.source_type || '未知来源',
    formatDate(item.published_at),
    itemChannel(item),
    signalLabel(item),
    scoreBadge(item),
  ].filter(Boolean).join(' · ');

  panel.innerHTML = [
    '<div class="reader-toolbar">',
    '  <span>预计阅读 3 分钟 · 已按' + escapeHtml(viewLabel()) + '过滤</span>',
    '  <div class="reader-tools">',
    '    <button class="' + (read ? 'active' : '') + '" type="button" data-item-state-action="is_read" data-item-id="' + escapeHtml(item.id) + '">' + (read ? '已读' : '标记已读') + '</button>',
    '    <button class="' + (later ? 'active' : '') + '" type="button" data-item-state-action="is_later" data-item-id="' + escapeHtml(item.id) + '">' + (later ? '已稍后读' : '稍后读') + '</button>',
    '    <button class="' + (favored ? 'active' : '') + '" type="button" data-item-state-action="is_saved" data-item-id="' + escapeHtml(item.id) + '">' + (favored ? '已收藏' : '收藏') + '</button>',
    '    <button type="button" data-copy-summary="' + escapeHtml(item.id) + '">复制摘要</button>',
    '  </div>',
    '</div>',
    '<article class="article">',
    '  <div class="article-source">' + escapeHtml(sourceLine) + '</div>',
    '  <h2>' + escapeHtml(item.title) + '</h2>',
    '  <p class="article-lead">' + escapeHtml(displayText(item.summary_zh, '暂无摘要')) + '</p>',
    renderItemMedia(item, 'article'),
    renderInsightBlocks(item, actionSuggestion),
    '  <div class="reading-actions">',
    '    <a class="button-link" href="' + escapeHtml(item.url) + '" target="_blank" rel="noreferrer">打开原文</a>',
    '    <button class="text-link" type="button" data-preview-url="' + escapeHtml(item.url || '') + '">站内预览</button>',
    '    <button class="text-link" type="button" data-item-state-action="is_saved" data-item-id="' + escapeHtml(item.id) + '">' + (favored ? '取消收藏' : '加入收藏') + '</button>',
    '    <button class="text-link" type="button" data-item-state-action="is_later" data-item-id="' + escapeHtml(item.id) + '">' + (later ? '移出稍后读' : '稍后读') + '</button>',
    '    <button class="text-link" type="button" data-item-state-action="dismissed" data-item-id="' + escapeHtml(item.id) + '">' + (dismissed ? '已忽略' : '忽略') + '</button>',
    '    <button class="text-link" type="button" data-feedback-action="more_like_this" data-item-id="' + escapeHtml(item.id) + '">更多类似</button>',
    '    <button class="text-link" type="button" data-feedback-action="less_like_this" data-item-id="' + escapeHtml(item.id) + '">减少类似</button>',
    '    <button class="text-link" type="button" data-feedback-action="not_relevant" data-item-id="' + escapeHtml(item.id) + '">不相关</button>',
    '  </div>',
    '  <div class="tag-row">' + renderTags(itemTopics(item)) + '</div>',
    '  <section id="inlinePreview" class="inline-preview hidden" aria-live="polite"></section>',
    '</article>',
  ].join('');
}

function readingJudgement(item) {
  if (item.scoring_disabled) {
    return '当前为无评分模式。建议按信源可信度、发布时间和个人兴趣自行判断是否需要跟进。';
  }
  var score = Number(item.score) || 0;
  if (score >= 8.5) {
    return '这是高优先级条目，建议尽快阅读原文并判断是否需要进入今日行动清单。';
  }
  if (score >= 7.5) {
    return '这是值得点开但仍需验证的条目。适合快速阅读摘要、检查来源，再决定是否深入跟进。';
  }
  return '这是补充阅读条目。可在完成高优先级内容后，用于扩展背景或观察趋势。';
}

function countBy(items, key) {
  var counts = {};
  items.forEach(function (item) {
    var value = String(item[key] || '未知');
    counts[value] = (counts[value] || 0) + 1;
  });
  return Object.keys(counts).map(function (name) {
    return { name: name, count: counts[name] };
  }).sort(function (a, b) {
    return b.count - a.count || a.name.localeCompare(b.name);
  });
}

function renderContext(items, selectedItem) {
  var panel = document.getElementById('contextPanel');
  var data = getActiveData() || {};
  var thresholds = data.thresholds || {};
  var dailyCount = (data.daily_push_items || []).length;
  var scoringEnabled = data.ai_enabled !== false;
  var highestScore = items.reduce(function (max, item) {
    return Math.max(max, Number(item.score) || 0);
  }, 0);
  var sources = countBy(items, 'source').slice(0, 4);
  var maxSourceCount = sources.reduce(function (max, item) {
    return Math.max(max, item.count);
  }, 1);

  panel.innerHTML = [
    '<section class="context-card" data-context-card="summary">',
    '  <div class="context-title"><strong>今日摘要</strong><span>' + (scoringEnabled ? '高优先级 > ' + escapeHtml(thresholds.daily_push || 8.5) : '无评分模式') + '</span></div>',
    '  <p class="brief">' + escapeHtml(contextBrief(items, selectedItem)) + '</p>',
    '  <div class="priority">',
    '    <div class="priority-row"><i class="dot"></i><span>高优先级</span><strong>' + (scoringEnabled ? dailyCount : '关闭') + '</strong></div>',
    '    <div class="priority-row"><i class="dot orange"></i><span>精选阈值</span><strong>' + (scoringEnabled ? escapeHtml(thresholds.featured || 7.5) : '关闭') + '</strong></div>',
    '    <div class="priority-row"><i class="dot red"></i><span>最高评分</span><strong>' + (scoringEnabled ? scoreText(highestScore) : '未评分') + '</strong></div>',
    '  </div>',
    '</section>',
    '<section class="context-card" data-context-card="sources">',
    '  <div class="context-title"><strong>信源分布</strong><span>' + ((data.sources || []).length || sources.length) + ' 个</span></div>',
    '  <div class="source-bars">',
    sources.length ? sources.map(function (source) {
      var width = Math.max(12, Math.round((source.count / maxSourceCount) * 100));
      return '<div class="bar-row"><span>' + escapeHtml(source.name) + '</span><div class="bar-track"><i style="width: ' + width + '%"></i></div><strong>' + source.count + '</strong></div>';
    }).join('') : '<p class="brief">暂无信源数据。</p>',
    '  </div>',
    '</section>',
  ].join('');
}

function contextBrief(items, selectedItem) {
  if (!items.length) return '当前筛选条件下没有可读内容。';
  var categories = countBy(items.map(function (item) {
    return Object.assign({}, item, { channel: itemChannel(item) });
  }), 'channel').slice(0, 3).map(function (item) {
    return item.name;
  });
  var selectedText = selectedItem ? '当前选中“' + selectedItem.title + '”。' : '';
  if (!isAiScoringEnabled()) {
    return '当前列表按发布时间展示，重点集中在 ' + categories.join('、') + '。建议按你订阅的信源优先级自行阅读。' + selectedText;
  }
  return '当前列表重点集中在 ' + categories.join('、') + '。建议优先处理高分条目，再按标签扩展阅读。' + selectedText;
}

function renderConfigView() {
  document.getElementById('readingQueue').classList.add('hidden');
  document.getElementById('readerPanel').classList.add('hidden');
  document.getElementById('contextPanel').classList.add('hidden');
  document.getElementById('subscriptionPanel').classList.add('hidden');
  document.getElementById('configPanel').classList.remove('hidden');
  document.getElementById('readerShell').classList.add('config-mode');
  if (!canUseConfig()) {
    renderAuthGate();
    return;
  }
  if (!state.configLoaded) {
    loadConfig();
    return;
  }
  renderEnvStatus(state.envStatus || []);
  renderConfigForms(state.config || {});
}

function renderSubscriptionView() {
  document.getElementById('readingQueue').classList.add('hidden');
  document.getElementById('readerPanel').classList.add('hidden');
  document.getElementById('contextPanel').classList.add('hidden');
  document.getElementById('configPanel').classList.add('hidden');
  document.getElementById('subscriptionPanel').classList.remove('hidden');
  document.getElementById('readerShell').classList.add('config-mode');
  if (!canUseConfig()) {
    showLoginGate('请先登录后管理订阅。');
    return;
  }
  if (!state.subscriptionConsoleLoaded && typeof loadSubscriptionConsole === 'function') {
    loadSubscriptionConsole();
    return;
  }
  if (typeof renderSubscriptionConsole === 'function') {
    renderSubscriptionConsole(state.subscriptionConsole || {});
  }
}

function renderReaderView() {
  document.getElementById('readingQueue').classList.remove('hidden');
  document.getElementById('readerPanel').classList.remove('hidden');
  document.getElementById('contextPanel').classList.remove('hidden');
  document.getElementById('configPanel').classList.add('hidden');
  document.getElementById('subscriptionPanel').classList.add('hidden');
  document.getElementById('readerShell').classList.remove('config-mode');
  var items = getFilteredItems();
  var selectedItem = getSelectedItem(items);
  markRead(selectedItem);
  renderQueue(items, selectedItem);
  renderReader(selectedItem);
  renderContext(items, selectedItem);
}

function renderItems() {
  if (state.view === 'config') {
    renderConfigView();
    return;
  }
  if (state.view === 'subscriptions') {
    renderSubscriptionView();
    return;
  }
  renderReaderView();
}

function renderAll() {
  var data = getActiveData();
  if (data) {
    renderSelectOptions(document.getElementById('channelSelect'), getChannelFilterOptions(data), '全部频道');
    renderGroupedTagSelectOptions(document.getElementById('tagSelect'), getTagFilterOptions(data), '全部主题');
    renderSelectOptions(document.getElementById('sourceSelect'), data.sources || [], '全部来源');
  }
  renderMeta();
  updateActiveTab();
  applyReaderDensity();
  renderItems();
}

function updateActiveTab() {
  document.querySelectorAll('.tab').forEach(function (tab) {
    tab.classList.toggle('active', tab.dataset.view === state.view);
  });
}

function applyReaderDensity() {
  document.body.classList.toggle('density-compact', state.readerDensity === 'compact');
  var button = document.getElementById('densityToggleBtn');
  if (button) {
    button.title = state.readerDensity === 'compact' ? '切换到舒适阅读' : '切换到紧凑阅读';
  }
}

function bindEvents() {
  bindPressFeedback();
  document.getElementById('refreshBtn').addEventListener('click', loadData);
  document.getElementById('clearFiltersBtn').addEventListener('click', clearFilters);
  document.getElementById('densityToggleBtn').addEventListener('click', function () {
    state.readerDensity = state.readerDensity === 'compact' ? 'comfortable' : 'compact';
    saveReaderDensity();
    applyReaderDensity();
  });
  document.getElementById('reloadConfigBtn').addEventListener('click', function () {
    state.configLoaded = false;
    if (!canUseConfig()) renderAuthGate();
    else loadConfig();
  });
  document.getElementById('logoutBtn').addEventListener('click', handleAuthLogout);
  document.getElementById('configForms').addEventListener('submit', handleConfigFormSubmit);
  document.getElementById('configForms').addEventListener('click', handleConfigFormClick);
  document.getElementById('configForms').addEventListener('change', handleConfigFormChange);
  if (typeof bindSubscriptionEvents === 'function') bindSubscriptionEvents();
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
    chooseViewForTag(state.tag);
    renderAll();
  });
  document.getElementById('channelSelect').addEventListener('change', function (event) {
    state.channel = event.target.value;
    state.tag = '';
    state.selectedItemId = '';
    renderAll();
  });
  document.getElementById('sourceSelect').addEventListener('change', function (event) {
    state.source = event.target.value;
    renderItems();
  });
  document.getElementById('favoritesOnly').addEventListener('change', function (event) {
    state.favoritesOnly = event.target.checked;
    renderItems();
  });
  document.getElementById('hideDismissed').addEventListener('change', function (event) {
    state.hideDismissed = event.target.checked;
    state.selectedItemId = '';
    loadData();
  });
  document.getElementById('unreadFirst').addEventListener('change', function (event) {
    state.unreadFirst = event.target.checked;
    state.selectedItemId = '';
    loadData();
  });
  document.querySelectorAll('.tab').forEach(function (button) {
    button.addEventListener('click', function () {
      state.view = button.dataset.view;
      if (state.view === 'history') state.historyFilter = 'all';
      if (state.view === 'subscriptions') state.subscriptionConsoleLoaded = false;
      renderAll();
    });
  });
  document.getElementById('readingQueue').addEventListener('click', function (event) {
    var stat = event.target.closest('[data-stat-action]');
    if (!stat) return;
    handleQueueStat(stat.getAttribute('data-stat-action'));
  });
  document.getElementById('itemsList').addEventListener('click', function (event) {
    var story = event.target.closest('[data-select-item]');
    if (!story) return;
    state.selectedItemId = story.getAttribute('data-select-item') || '';
    renderItems();
  });
  document.getElementById('readerPanel').addEventListener('click', handleReaderAction);
  document.getElementById('articleGraphButton').addEventListener('click', openArticleGraph);
  document.getElementById('articleGraphPanel').addEventListener('click', handleArticleGraphClick);
  document.addEventListener('click', handleLightboxClick);
  document.addEventListener('keydown', handleLightboxKeydown);
}

function bindPressFeedback() {
  document.addEventListener('pointerdown', function (event) {
    var target = event.target.closest('button, a.button-link, a.text-link');
    if (!target || target.disabled) return;
    target.classList.remove('press-feedback');
    void target.offsetWidth;
    target.classList.add('press-feedback');
    window.setTimeout(function () {
      if (document.body.contains(target)) target.classList.remove('press-feedback');
    }, 190);
  });
}

function handleQueueStat(action) {
  if (state.view === 'history' && (action === 'all' || action === 'featured')) {
    state.historyFilter = action;
    state.selectedItemId = '';
    renderAll();
    document.getElementById('readerPanel').scrollIntoView({ block: 'start', behavior: 'smooth' });
    return;
  }
  if (action === 'all' || action === 'featured' || action === 'readLater') {
    state.view = action;
    state.selectedItemId = '';
    renderAll();
    document.getElementById('readerPanel').scrollIntoView({ block: 'start', behavior: 'smooth' });
    return;
  }
}

async function updateRemoteItemState(articleId, action, button) {
  var item = findKnownItem(articleId);
  var current = itemUserState(item || { id: articleId });
  var patch = {};
  if (action === 'dismissed') patch.dismissed = !current.dismissed;
  if (action === 'is_read') patch.is_read = !current.is_read;
  if (action === 'is_saved') patch.is_saved = !current.is_saved;
  if (action === 'is_later') patch.is_later = !current.is_later;
  if (!Object.keys(patch).length) return;

  if (button) button.disabled = true;
  try {
    var response = await fetch('/api/me/items/' + encodeURIComponent(articleId) + '/state', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    var payload = await response.json();
    if (!response.ok) throw new Error(apiErrorMessage(payload, '状态更新失败'));
    applyUserItemState(articleId, unwrapApiPayload(payload));
    if (action === 'dismissed' && state.hideDismissed) state.selectedItemId = '';
    renderItems();
  } catch (err) {
    if (button) showCopyFeedback(button, err.message || '状态更新失败', false, 1800);
  } finally {
    if (button) button.disabled = false;
  }
}

async function submitItemFeedback(articleId, feedbackType, button) {
  if (button) button.disabled = true;
  try {
    var response = await fetch('/api/me/items/' + encodeURIComponent(articleId) + '/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        feedback_type: feedbackType,
        metadata: { surface: 'reader' },
      }),
    });
    var payload = await response.json();
    if (!response.ok) throw new Error(apiErrorMessage(payload, '反馈提交失败'));
    if (button) showCopyFeedback(button, '已记录', true, 1200);
  } catch (err) {
    if (button) showCopyFeedback(button, err.message || '反馈提交失败', false, 1800);
  } finally {
    if (button) button.disabled = false;
  }
}

function handleReaderAction(event) {
  var mediaThumb = event.target.closest('[data-media-thumb]');
  if (mediaThumb) {
    var thumbItemId = mediaThumb.getAttribute('data-media-thumb') || '';
    setMediaIndex(thumbItemId, mediaThumb.getAttribute('data-media-index'));
    renderReader(findKnownItem(thumbItemId));
    return;
  }

  var mediaOpen = event.target.closest('[data-open-media]');
  if (mediaOpen) {
    openLightbox(
      mediaOpen.getAttribute('data-open-media') || '',
      mediaOpen.getAttribute('data-media-index')
    );
    return;
  }

  var stateButton = event.target.closest('[data-item-state-action]');
  if (stateButton) {
    updateRemoteItemState(
      stateButton.getAttribute('data-item-id') || '',
      stateButton.getAttribute('data-item-state-action') || '',
      stateButton
    );
    return;
  }

  var feedbackButton = event.target.closest('[data-feedback-action]');
  if (feedbackButton) {
    submitItemFeedback(
      feedbackButton.getAttribute('data-item-id') || '',
      feedbackButton.getAttribute('data-feedback-action') || '',
      feedbackButton
    );
    return;
  }

  var favoriteButton = event.target.closest('[data-favorite-action]');
  if (favoriteButton) {
    var favoriteId = favoriteButton.getAttribute('data-favorite-action');
    if (state.favorites.has(favoriteId)) state.favorites.delete(favoriteId);
    else state.favorites.add(favoriteId);
    saveSet(STORAGE_FAVORITES, state.favorites);
    renderItems();
    return;
  }

  var laterButton = event.target.closest('[data-read-later-action]');
  if (laterButton) {
    var laterId = laterButton.getAttribute('data-read-later-action');
    if (state.readLater.has(laterId)) state.readLater.delete(laterId);
    else state.readLater.add(laterId);
    saveSet(STORAGE_READ_LATER, state.readLater);
    renderItems();
    return;
  }

  var copyButton = event.target.closest('[data-copy-summary]');
  if (copyButton) {
    copySelectedSummary(copyButton.getAttribute('data-copy-summary'), copyButton);
    return;
  }

  var previewButton = event.target.closest('[data-preview-url]');
  if (previewButton) {
    toggleInlinePreview(previewButton.getAttribute('data-preview-url'));
  }
}

function ensureLightbox() {
  var existing = document.getElementById('mediaLightbox');
  if (existing) return existing;
  var lightbox = document.createElement('div');
  lightbox.id = 'mediaLightbox';
  lightbox.className = 'media-lightbox hidden';
  lightbox.setAttribute('role', 'dialog');
  lightbox.setAttribute('aria-modal', 'true');
  lightbox.setAttribute('aria-label', '图片预览');
  document.body.appendChild(lightbox);
  return lightbox;
}

function openLightbox(itemId, index) {
  var item = findKnownItem(itemId);
  var urls = getMediaUrls(item);
  if (!item || !urls.length) return;
  setMediaIndex(itemId, index);
  state.lightbox = {
    itemId: itemId,
    index: selectedMediaIndex(item),
  };
  renderLightbox();
}

function closeLightbox() {
  state.lightbox = null;
  var lightbox = document.getElementById('mediaLightbox');
  if (lightbox) {
    lightbox.classList.add('hidden');
    lightbox.innerHTML = '';
  }
}

function moveLightbox(delta) {
  if (!state.lightbox) return;
  var item = findKnownItem(state.lightbox.itemId);
  var urls = getMediaUrls(item);
  if (!item || !urls.length) return;
  var next = (Number(state.lightbox.index) || 0) + delta;
  if (next < 0) next = urls.length - 1;
  if (next >= urls.length) next = 0;
  state.lightbox.index = next;
  state.mediaIndexByItem[item.id] = next;
  renderLightbox();
  renderReader(item);
}

function renderLightbox() {
  var lightbox = ensureLightbox();
  if (!state.lightbox) {
    lightbox.classList.add('hidden');
    return;
  }
  var item = findKnownItem(state.lightbox.itemId);
  var urls = getMediaUrls(item);
  if (!item || !urls.length) {
    closeLightbox();
    return;
  }
  var index = Number(state.lightbox.index) || 0;
  if (index < 0) index = 0;
  if (index >= urls.length) index = urls.length - 1;
  var currentUrl = urls[index];
  lightbox.innerHTML = [
    '<div class="media-lightbox-backdrop" data-lightbox-action="close"></div>',
    '<div class="media-lightbox-frame">',
    '  <div class="media-lightbox-head">',
    '    <strong>' + escapeHtml(item.title || '图片') + '</strong>',
    '    <span>' + (index + 1) + ' / ' + urls.length + '</span>',
    '    <button type="button" data-lightbox-action="close" aria-label="关闭">×</button>',
    '  </div>',
    '  <div class="media-lightbox-stage">',
    urls.length > 1 ? '    <button class="media-lightbox-nav prev" type="button" data-lightbox-action="prev" aria-label="上一张">‹</button>' : '',
    '    <img src="' + escapeHtml(currentUrl) + '" alt="' + escapeHtml(mediaAlt(item, index, urls.length)) + '" data-media-image>',
    urls.length > 1 ? '    <button class="media-lightbox-nav next" type="button" data-lightbox-action="next" aria-label="下一张">›</button>' : '',
    '  </div>',
    urls.length > 1 ? [
      '  <div class="media-lightbox-thumbs">',
      urls.map(function (url, thumbIndex) {
        return [
          '<button class="' + (thumbIndex === index ? 'active' : '') + '" type="button" data-lightbox-thumb="' + thumbIndex + '" aria-label="查看第 ' + (thumbIndex + 1) + ' 张">',
          '  <img src="' + escapeHtml(url) + '" alt="' + escapeHtml(mediaAlt(item, thumbIndex, urls.length)) + '" loading="lazy" data-media-image>',
          '</button>',
        ].join('');
      }).join(''),
      '  </div>',
    ].join('') : '',
    '</div>',
  ].join('');
  lightbox.classList.remove('hidden');
}

function handleLightboxClick(event) {
  var actionNode = event.target.closest('[data-lightbox-action]');
  if (actionNode) {
    var action = actionNode.getAttribute('data-lightbox-action');
    if (action === 'close') closeLightbox();
    if (action === 'prev') moveLightbox(-1);
    if (action === 'next') moveLightbox(1);
    return;
  }
  var thumbNode = event.target.closest('[data-lightbox-thumb]');
  if (thumbNode && state.lightbox) {
    state.lightbox.index = Number(thumbNode.getAttribute('data-lightbox-thumb')) || 0;
    state.mediaIndexByItem[state.lightbox.itemId] = state.lightbox.index;
    renderLightbox();
    renderReader(findKnownItem(state.lightbox.itemId));
  }
}

function handleLightboxKeydown(event) {
  if (!state.lightbox) return;
  if (event.key === 'Escape') closeLightbox();
  if (event.key === 'ArrowLeft') moveLightbox(-1);
  if (event.key === 'ArrowRight') moveLightbox(1);
}

function toggleInlinePreview(url) {
  var preview = document.getElementById('inlinePreview');
  if (!preview || !url) return;
  var iframe = preview.querySelector('iframe');
  if (!preview.classList.contains('hidden') && iframe && iframe.src === url) {
    preview.classList.add('hidden');
    iframe.removeAttribute('src');
    return;
  }
  preview.innerHTML = [
    '<div class="inline-preview-head">',
    '  <strong>原网页预览</strong>',
    '  <span>如果来源禁止嵌入，请在本窗口打开。</span>',
    '  <a class="preview-open-link" href="">在本窗口打开</a>',
    '</div>',
    '<iframe title="原网页预览" loading="lazy" referrerpolicy="no-referrer"></iframe>',
  ].join('');
  preview.querySelector('.preview-open-link').href = url;
  preview.querySelector('iframe').src = url;
  preview.classList.remove('hidden');
  preview.scrollIntoView({ block: 'start', behavior: 'smooth' });
}

function showCopyFeedback(button, message, ok, duration) {
  if (!button) return;
  window.clearTimeout(copyFeedbackTimer);
  button.textContent = message;
  button.classList.toggle('copy-ok', ok);
  button.classList.toggle('copy-error', !ok);
  button.setAttribute('aria-label', message);
  if (duration === 0) return;
  copyFeedbackTimer = window.setTimeout(function () {
    if (!document.body.contains(button)) return;
    button.textContent = '复制摘要';
    button.classList.remove('copy-ok', 'copy-error');
    button.removeAttribute('aria-label');
  }, duration || 1600);
}

function writeClipboardText(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    return navigator.clipboard.writeText(text).catch(function () {
      return writeClipboardTextFallback(text);
    });
  }
  return writeClipboardTextFallback(text);
}

function writeClipboardTextFallback(text) {
  return new Promise(function (resolve, reject) {
    var textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.top = '-9999px';
    document.body.appendChild(textarea);
    textarea.select();
    try {
      if (document.execCommand('copy')) resolve();
      else reject(new Error('copy command failed'));
    } catch (err) {
      reject(err);
    } finally {
      document.body.removeChild(textarea);
    }
  });
}

function copySelectedSummary(id, button) {
  var item = getBaseItems().find(function (candidate) { return candidate.id === id; });
  if (!item) {
    showCopyFeedback(button, '无内容', false);
    return;
  }
  var text = [
    item.title,
    '',
    item.summary_zh || '',
    '',
    '推荐理由：' + (item.reason || '暂无'),
    '我该关注什么：' + (item.action_suggestion || '阅读原文后判断是否需要跟进。'),
    item.url || '',
  ].join('\n');
  showCopyFeedback(button, '复制中', true, 0);
  writeClipboardText(text)
    .then(function () {
      showCopyFeedback(button, '已复制', true);
    })
    .catch(function () {
      showCopyFeedback(button, '复制失败', false, 2200);
    });
}

function clearFilters() {
  state.query = '';
  state.minScore = 0;
  state.channel = '';
  state.tag = '';
  state.source = '';
  state.favoritesOnly = false;
  state.selectedItemId = '';
  document.getElementById('searchInput').value = '';
  document.getElementById('minScoreInput').value = '0';
  document.getElementById('minScoreValue').textContent = '0';
  document.getElementById('channelSelect').value = '';
  document.getElementById('tagSelect').value = '';
  document.getElementById('sourceSelect').value = '';
  document.getElementById('favoritesOnly').checked = false;
  state.hideDismissed = false;
  state.unreadFirst = false;
  document.getElementById('hideDismissed').checked = false;
  document.getElementById('unreadFirst').checked = false;
  if (state.view === 'config') state.view = 'featured';
  if (state.view === 'subscriptions') state.view = 'featured';
  renderAll();
}
