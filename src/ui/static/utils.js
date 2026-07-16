// Inteliscope static UI: utils module.
function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function unwrapApiPayload(payload) {
  if (payload && payload.ok === true && Object.prototype.hasOwnProperty.call(payload, 'data')) {
    return payload.data;
  }
  return payload;
}

function apiErrorMessage(payload, fallback) {
  var error = payload && payload.error;
  if (error && typeof error === 'object') {
    return error.message || error.code || fallback;
  }
  return error || fallback;
}

function plainText(value) {
  var text = String(value || '');
  if (!text) return '';
  var blockNormalized = text
    .replace(/<\s*br\s*\/?>/gi, '\n')
    .replace(/<\/\s*(p|div|li|h[1-6])\s*>/gi, '\n');
  var withoutTags = blockNormalized.replace(/<[^>]*>/g, ' ');
  var textarea = document.createElement('textarea');
  textarea.innerHTML = withoutTags;
  return textarea.value.replace(/\s+/g, ' ').trim();
}

function displayText(value, fallback) {
  return plainText(value) || fallback;
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

function safeExternalUrl(value) {
  try {
    var parsed = new URL(String(value || ''));
    if (['http:', 'https:'].indexOf(parsed.protocol) < 0) return '';
    if (parsed.username || parsed.password) return '';
    return parsed.href;
  } catch (err) {
    return '';
  }
}

function formatFeedFreshness(value, now) {
  if (!value) return 'Feed 更新时间未知';
  var timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return 'Feed 更新时间未知';
  var current = Number.isFinite(Number(now)) ? Number(now) : Date.now();
  var elapsedSeconds = Math.floor((current - timestamp) / 1000);
  if (elapsedSeconds < 60) return 'Feed 刚刚更新';
  var elapsedMinutes = Math.floor(elapsedSeconds / 60);
  if (elapsedMinutes < 60) return 'Feed 更新于 ' + elapsedMinutes + ' 分钟前';
  var elapsedHours = Math.floor(elapsedMinutes / 60);
  if (elapsedHours < 24) return 'Feed 更新于 ' + elapsedHours + ' 小时前';
  return 'Feed 更新于 ' + Math.floor(elapsedHours / 24) + ' 天前';
}

function scoreClass(score) {
  if (score >= 8.5) return 'score-high';
  if (score >= 7.5) return 'score-featured';
  if (score >= 6) return 'score-mid';
  return 'score-low';
}

function scoreText(score) {
  return (Number(score) || 0).toFixed(1);
}

function getBaseItems() {
  if (!state.data) return [];
  if (state.view === 'readLater') return getReadLaterItems();
  if (state.view === 'history') return getHistoryBaseItems();
  if (state.view === 'daily') return state.data.daily_push_items || [];
  if (state.view === 'featured') return state.data.featured_items || [];
  if (state.view === 'all') return state.data.today_items || state.data.items || [];
  return state.data.items || [];
}

function getHistoryBaseItems() {
  var history = state.historyData || state.data || {};
  if (state.historyFilter === 'featured') return history.featured_items || [];
  return history.items || [];
}

function getAllKnownItems() {
  var data = state.data || {};
  var history = state.historyData || {};
  var seen = {};
  return []
    .concat(data.today_items || [])
    .concat(data.items || [])
    .concat(history.items || [])
    .concat(data.featured_items || [])
    .concat(history.featured_items || [])
    .concat(data.daily_push_items || [])
    .concat(history.daily_push_items || [])
    .concat(data.personal_items || [])
    .concat(history.personal_items || [])
    .filter(function (item) {
      if (!item || !item.id || seen[item.id]) return false;
      seen[item.id] = true;
      return true;
    });
}

function getReadLaterItems() {
  var byId = {};
  getAllKnownItems().forEach(function (item) {
    byId[item.id] = item;
  });
  return Array.from(state.readLater)
    .map(function (id) { return byId[id]; })
    .filter(Boolean);
}

function findKnownItem(itemId) {
  return getAllKnownItems().find(function (item) {
    return item && item.id === itemId;
  }) || null;
}

function defaultUserItemState(articleId) {
  return {
    article_id: articleId,
    is_read: false,
    is_saved: state.favorites.has(articleId),
    is_later: state.readLater.has(articleId),
    dismissed: false,
    read_at: null,
    saved_at: null,
    later_at: null,
    dismissed_at: null,
    updated_at: null,
  };
}

function normalizeUserItemState(articleId, value) {
  var base = defaultUserItemState(articleId);
  if (!value || typeof value !== 'object') return base;
  return {
    article_id: value.article_id || articleId,
    is_read: !!value.is_read,
    is_saved: !!value.is_saved,
    is_later: !!value.is_later,
    dismissed: !!value.dismissed,
    read_at: value.read_at || null,
    saved_at: value.saved_at || null,
    later_at: value.later_at || null,
    dismissed_at: value.dismissed_at || null,
    updated_at: value.updated_at || null,
  };
}

function applyUserItemState(articleId, value) {
  if (!articleId) return defaultUserItemState('');
  var normalized = normalizeUserItemState(articleId, value);
  state.itemState[articleId] = normalized;
  var item = findKnownItem(articleId);
  if (item) item.user_state = normalized;
  if (normalized.is_read) state.readItems.add(articleId);
  else state.readItems.delete(articleId);
  if (normalized.is_saved) state.favorites.add(articleId);
  else state.favorites.delete(articleId);
  if (normalized.is_later) state.readLater.add(articleId);
  else state.readLater.delete(articleId);
  saveSet(STORAGE_FAVORITES, state.favorites);
  saveSet(STORAGE_READ_LATER, state.readLater);
  return normalized;
}

function syncUserItemStateFromFeed() {
  state.itemState = {};
  getAllKnownItems().forEach(function (item) {
    if (item && item.id && item.user_state) {
      applyUserItemState(item.id, item.user_state);
    }
  });
}

function itemUserState(item) {
  if (!item || !item.id) return defaultUserItemState('');
  if (state.itemState[item.id]) return state.itemState[item.id];
  if (item.user_state) return applyUserItemState(item.id, item.user_state);
  return defaultUserItemState(item.id);
}

async function refreshUserItemStates(options) {
  options = options || {};
  var isCurrent = typeof options.isCurrent === 'function' ? options.isCurrent : function () { return true; };
  if (!isCurrent()) return false;
  var ids = getAllKnownItems()
    .map(function (item) { return item && item.id; })
    .filter(Boolean);
  if (!ids.length) return true;
  var response = await fetch('/api/me/item-state?article_ids=' + encodeURIComponent(ids.join(',')));
  var payload = await response.json();
  if (!isCurrent()) return false;
  if (!response.ok) throw new Error(apiErrorMessage(payload, '读取状态失败'));
  var data = unwrapApiPayload(payload);
  var states = (data && data.states) || {};
  if (!isCurrent()) return false;
  Object.keys(states).forEach(function (articleId) {
    applyUserItemState(articleId, states[articleId]);
  });
  return true;
}

function getActiveData() {
  if (state.view === 'history' && state.historyData) return state.historyData;
  return state.data;
}

function viewLabel() {
  if (state.view === 'history') {
    if (state.historyFilter === 'featured') return '历史精选';
    return '历史归档';
  }
  if (!isAiScoringEnabled() && state.view === 'featured') return '全部动态';
  if (!isAiScoringEnabled() && state.view === 'daily') return '全部动态';
  if (state.view === 'daily') return '日报';
  if (state.view === 'readLater') return '稍后读';
  if (state.view === 'all') return '今日动态';
  return '今日精选';
}

function isAiScoringEnabled() {
  return !state.data || state.data.ai_enabled !== false;
}

function getEffectiveMinScore() {
  return isAiScoringEnabled() ? state.minScore : 0;
}

function shouldShowScoreControls() {
  return isAiScoringEnabled();
}

function viewDescription() {
  if (state.view === 'history') {
    if (state.historyFilter === 'featured') return '历史累计精选内容，适合回看高分信息。';
    return '回看已经离开最新 Feed 的信息。';
  }
  if (!isAiScoringEnabled() && (state.view === 'featured' || state.view === 'daily' || state.view === 'all')) {
    return '无评分模式下按发布时间展示你配置的信源内容。';
  }
  if (state.view === 'daily') return '只显示达到每日推送阈值的最高优先级内容。';
  if (state.view === 'readLater') return '本机保存的待读清单。移出只会取消标记，不会删除原始动态。';
  if (state.view === 'all') {
    return '显示今天进入本轮信息流的全部动态，不混入历史归档。';
  }
  return '按 AI 评分和可行动性排序，默认只展示超过精选阈值的内容。';
}

function matchesQuery(item) {
  if (!state.query) return true;
  var haystack = [
    item.title,
    item.source,
    item.summary_zh,
    item.action_suggestion,
    item.presentation && item.presentation.source && item.presentation.source.name,
    item.presentation && item.presentation.author && item.presentation.author.name,
    item.presentation && item.presentation.content && item.presentation.content.excerpt,
    item.channel,
    item.category,
    (item.topics || []).join(' '),
    (item.tags || []).join(' '),
    (item.personal_tags || []).join(' '),
    item.signal_strength,
    item.signal_type,
    (item.entities || []).join(' '),
  ].join(' ').toLowerCase();
  return haystack.indexOf(state.query.toLowerCase()) !== -1;
}

function normalizeHubChannel(value) {
  var raw = String(value || '').trim();
  var key = raw.toLowerCase().replace(/[\s_\\/#:：,，.\-]+/g, '');
  var aliases = {
    ai: 'AI',
    人工智能: 'AI',
    ai编程: 'AI',
    aicoding: 'AI',
    aiagent: 'AI',
    agent: 'AI',
    codex: 'AI',
    模型发布: 'AI',
    ragmcp: 'AI',
    aiinfra: 'AI',
    投资: '投资',
    finance: '投资',
    美股: '投资',
    估值: '投资',
    宏观: '投资',
    产品机会: '产品机会',
    产品创业: '产品机会',
    价格监控: '产品机会',
    工作项目: '工作/项目',
    朋友动态: '朋友动态',
    生活: '生活',
    政策风险: '政策/风险',
    安全治理: '政策/风险',
    其他: '其他',
  };
  if (HUB_CHANNEL_OPTIONS.indexOf(raw) >= 0) return raw;
  return aliases[key] || '';
}

function itemChannel(item) {
  return normalizeHubChannel(item && (item.channel || item.category)) || '其他';
}

function getFilteredItems() {
  var minScore = getEffectiveMinScore();
  var items = getBaseItems().filter(function (item) {
    var userState = itemUserState(item);
    if (state.hideDismissed && userState.dismissed) return false;
    if (isAiScoringEnabled() && (item.score || 0) < minScore) return false;
    if (state.channel && itemChannel(item) !== state.channel) return false;
    if (state.tag && !itemHasTag(item, state.tag)) return false;
    if (state.source && item.source !== state.source) return false;
    if (state.favoritesOnly && !state.favorites.has(item.id)) return false;
    return matchesQuery(item);
  });
  if (state.unreadFirst) {
    items.sort(function (a, b) {
      return (itemUserState(a).is_read ? 1 : 0) - (itemUserState(b).is_read ? 1 : 0);
    });
  }
  return items;
}

function itemHasTag(item, tag) {
  return (item.topics || item.tags || []).indexOf(tag) >= 0 || (item.personal_tags || []).indexOf(tag) >= 0;
}

function getChannelFilterOptions(data) {
  return uniqueValues(
    []
      .concat(HUB_CHANNEL_OPTIONS)
      .concat((data && data.channels) || [])
      .concat(getBaseItems().map(function (item) { return itemChannel(item); }))
      .map(normalizeHubChannel)
  );
}

function chooseViewForTag(tag) {
  if (!tag || getBaseItems().some(function (item) { return itemHasTag(item, tag); })) return;
  if ([].concat(((state.data || {}).today_items) || [], ((state.data || {}).items) || []).some(function (item) { return itemHasTag(item, tag); })) {
    state.view = 'all';
    state.selectedItemId = '';
    return;
  }
  if (((state.historyData || {}).items || []).some(function (item) { return itemHasTag(item, tag); })) {
    state.view = 'history';
    state.historyFilter = 'all';
    state.selectedItemId = '';
  }
}

function getSelectedItem(items) {
  if (!items.length) {
    state.selectedItemId = '';
    return null;
  }
  var selected = items.find(function (item) { return item.id === state.selectedItemId; });
  if (!selected) {
    selected = items[0];
    state.selectedItemId = selected.id;
  }
  return selected;
}

function renderSelectOptions(select, values, allLabel) {
  var current = select.value;
  select.innerHTML = '<option value="">' + allLabel + '</option>' +
    values.map(function (value) {
      return '<option value="' + escapeHtml(value) + '">' + escapeHtml(value) + '</option>';
    }).join('');
  select.value = values.indexOf(current) >= 0 ? current : '';
}

function renderGroupedTagSelectOptions(select, groups, allLabel) {
  if (!select) return;
  var current = select.value;
  var known = [];
  var html = ['<option value="">' + escapeHtml(allLabel) + '</option>'];
  groups.forEach(function (group) {
    if (!group.values.length) return;
    html.push('<optgroup label="' + escapeHtml(group.label) + '">');
    group.values.forEach(function (value) {
      known.push(value);
      html.push('<option value="' + escapeHtml(value) + '">' + escapeHtml(value) + '</option>');
    });
    html.push('</optgroup>');
  });
  select.innerHTML = html.join('');
  select.value = known.indexOf(current) >= 0 ? current : '';
}

function uniqueValues(values) {
  var seen = {};
  return values.filter(function (value) {
    var key = String(value || '').trim();
    if (!key || seen[key]) return false;
    seen[key] = true;
    return true;
  });
}

function getTagFilterOptions(data) {
  var aiTags = getConfigTagLibrary();
  var personalTags = getConfigPersonalTagLibrary();
  var scopedItems = state.channel
    ? getBaseItems().filter(function (item) { return itemChannel(item) === state.channel; })
    : [];
  var scopedTopics = uniqueValues(scopedItems.reduce(function (acc, item) {
    return acc.concat(item.topics || item.tags || []);
  }, []));
  var scopedPersonalTags = uniqueValues(scopedItems.reduce(function (acc, item) {
    return acc.concat(item.personal_tags || []);
  }, []));
  if (!aiTags.length && !(state.config && Array.isArray(state.config.tags))) {
    aiTags = uniqueValues([].concat((data && data.tag_library) || [], (data && data.tags) || []));
  }
  if (!personalTags.length && !(state.config && Array.isArray(state.config.personal_tags))) {
    personalTags = uniqueValues([].concat((data && data.personal_tag_library) || [], (data && data.personal_tags) || []));
  }
  if (state.channel && scopedTopics.length) aiTags = scopedTopics;
  if (state.channel && scopedPersonalTags.length) personalTags = scopedPersonalTags;
  return [
    { label: '阅读主题', values: aiTags },
    { label: '个人标签', values: personalTags },
  ];
}

function syncConfigTagLibrary(config) {
  if (!config || !Array.isArray(config.tags)) return;
  var tags = getConfigTagLibrary(config);
  var personalTags = getConfigPersonalTagLibrary(config);
  var allTags = tags.concat(personalTags);
  if (state.data) {
    state.data.tag_library = tags.slice();
    state.data.personal_tag_library = personalTags.slice();
    state.data.tags = filterKnownTags(state.data.tags || [], tags);
    state.data.personal_tags = filterKnownTags(state.data.personal_tags || [], personalTags);
  }
  if (state.historyData) {
    state.historyData.tag_library = tags.slice();
    state.historyData.personal_tag_library = personalTags.slice();
    state.historyData.tags = filterKnownTags(state.historyData.tags || [], tags);
    state.historyData.personal_tags = filterKnownTags(state.historyData.personal_tags || [], personalTags);
  }
  if (state.tag && allTags.indexOf(state.tag) === -1) {
    state.tag = '';
    var tagSelect = document.getElementById('tagSelect');
    if (tagSelect) tagSelect.value = '';
  }
}

function getConfigTagLibrary(config) {
  var source = config || state.config || {};
  return uniqueValues(Array.isArray(source.tags) ? source.tags : []);
}

function getConfigPersonalTagLibrary(config) {
  var source = config || state.config || {};
  return uniqueValues(Array.isArray(source.personal_tags) ? source.personal_tags : []);
}

function filterKnownTags(values, allowedTags) {
  var allowed = {};
  allowedTags.forEach(function (tag) {
    allowed[tag] = true;
  });
  return uniqueValues(values || []).filter(function (tag) {
    return allowed[tag];
  });
}

function getTodayTotalCount(data) {
  if (!data) return 0;
  if (Object.prototype.hasOwnProperty.call(data, 'today_total_items')) {
    return Number(data.today_total_items) || 0;
  }
  if (Array.isArray(data.today_items)) return data.today_items.length;
  return Array.isArray(data.items) ? data.items.length : 0;
}
