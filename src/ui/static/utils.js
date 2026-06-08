// Inteliscope static UI: utils module.
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

function scoreText(score) {
  return (Number(score) || 0).toFixed(1);
}

function getBaseItems() {
  if (!state.data) return [];
  if (state.view === 'readLater') return getReadLaterItems();
  if (state.view === 'history') return getHistoryBaseItems();
  if (state.view === 'daily') return state.data.daily_push_items || [];
  if (state.view === 'personal') return state.data.personal_items || [];
  if (state.view === 'featured') return state.data.featured_items || [];
  if (state.view === 'all') return state.data.today_items || state.data.items || [];
  return state.data.items || [];
}

function getHistoryBaseItems() {
  var history = state.historyData || state.data || {};
  if (state.historyFilter === 'featured') return history.featured_items || [];
  if (state.historyFilter === 'personal') return history.personal_items || [];
  if (state.historyFilter === 'daily') return history.daily_push_items || [];
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

function getActiveData() {
  if (state.view === 'history' && state.historyData) return state.historyData;
  return state.data;
}

function viewLabel() {
  if (state.view === 'history') {
    if (state.historyFilter === 'featured') return '历史精选';
    if (state.historyFilter === 'personal') return '历史个人关注';
    if (state.historyFilter === 'daily') return '历史推送';
    return '历史归档';
  }
  if (state.view === 'daily') return '每日推送';
  if (state.view === 'readLater') return '稍后读';
  if (state.view === 'personal') return '个人关注';
  if (state.view === 'all') return '今日动态';
  return '今日精选';
}

function viewDescription() {
  if (state.view === 'history') {
    if (state.historyFilter === 'featured') return '历史累计精选内容，适合回看高分信息。';
    if (state.historyFilter === 'personal') return '历史累计个人关注内容，适合按个人标签回看。';
    if (state.historyFilter === 'daily') return '历史累计达到每日推送阈值的内容。';
    return '历史累计内容按时间回看，适合复盘信息源质量。';
  }
  if (state.view === 'daily') return '只显示达到每日推送阈值的最高优先级内容。';
  if (state.view === 'readLater') return '本机保存的待读清单。移出只会取消标记，不会删除原始动态。';
  if (state.view === 'personal') return '按你的个人标签和偏好展示，不参与 AI 行业评分排序。';
  if (state.view === 'all') return '显示今天进入本轮信息流的全部动态，不混入历史归档。';
  return '按 AI 评分和可行动性排序，默认只展示超过精选阈值的内容。';
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
    (item.personal_tags || []).join(' '),
  ].join(' ').toLowerCase();
  return haystack.indexOf(state.query.toLowerCase()) !== -1;
}

function getFilteredItems() {
  return getBaseItems().filter(function (item) {
    if ((item.score || 0) < state.minScore) return false;
    if (state.tag && !itemHasTag(item, state.tag)) return false;
    if (state.source && item.source !== state.source) return false;
    if (state.favoritesOnly && !state.favorites.has(item.id)) return false;
    return matchesQuery(item);
  });
}

function itemHasTag(item, tag) {
  return (item.tags || []).indexOf(tag) >= 0 || (item.personal_tags || []).indexOf(tag) >= 0;
}

function chooseViewForTag(tag) {
  if (!tag || getBaseItems().some(function (item) { return itemHasTag(item, tag); })) return;
  if (((state.data || {}).personal_items || []).some(function (item) { return itemHasTag(item, tag); })) {
    state.view = 'personal';
    state.selectedItemId = '';
    return;
  }
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

function markRead(item) {
  if (!item || !item.id || state.readItems.has(item.id)) return;
  state.readItems.add(item.id);
  saveSet(STORAGE_READ_ITEMS, state.readItems);
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
  if (!aiTags.length && !(state.config && Array.isArray(state.config.tags))) {
    aiTags = uniqueValues([].concat((data && data.tag_library) || [], (data && data.tags) || []));
  }
  if (!personalTags.length && !(state.config && Array.isArray(state.config.personal_tags))) {
    personalTags = uniqueValues([].concat((data && data.personal_tag_library) || [], (data && data.personal_tags) || []));
  }
  return [
    { label: 'AI 大类', values: aiTags },
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
