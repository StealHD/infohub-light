(function () {
  'use strict';

  var STORAGE_FAVORITES = 'ai-radar-favorites';
  var STORAGE_READ_LATER = 'ai-radar-read-later';
  var STORAGE_READ_ITEMS = 'ai-radar-read-items';
  var STORAGE_READER_DENSITY = 'ai-radar-reader-density';
  var VIEW_OPTIONS = ['featured', 'personal', 'all', 'readLater', 'history', 'daily', 'config'];
  var TAG_LIBRARY_OPTIONS = [
    'AI Agent',
    'AI 编程',
    '模型发布',
    'RAG/MCP',
    'AI Infra',
    '开源模型',
    '推理框架',
    '产品创业',
    '研究论文',
    '安全治理',
    '行业动态',
  ];
  var APIFY_SOCIAL_KIND_OPTIONS = {
    x: [
      ['profile', 'X 账号'],
      ['keyword', 'X 关键词'],
    ],
    instagram: [
      ['profile', 'Instagram 主页'],
      ['hashtag', 'Instagram hashtag'],
    ],
    facebook: [
      ['page', 'Facebook Page'],
      ['group', 'Facebook Group'],
      ['post', 'Facebook 帖子 URL'],
    ],
    telegram: [
      ['channel', 'Telegram 频道（Apify）'],
    ],
  };

  var state = {
    data: null,
    view: getInitialView(),
    query: '',
    minScore: 0,
    tag: '',
    source: '',
    favoritesOnly: false,
    favorites: loadSet(STORAGE_FAVORITES),
    readLater: loadSet(STORAGE_READ_LATER),
    readItems: loadSet(STORAGE_READ_ITEMS),
    readerDensity: loadReaderDensity(),
    selectedItemId: '',
    mediaIndexByItem: {},
    lightbox: null,
    configLoaded: false,
    config: null,
    envStatus: [],
    historyData: null,
  };
  var copyFeedbackTimer = 0;

  function getInitialView() {
    try {
      var view = new URLSearchParams(window.location.search).get('view') || '';
      return VIEW_OPTIONS.indexOf(view) >= 0 ? view : 'featured';
    } catch (err) {
      return 'featured';
    }
  }

  function loadSet(key) {
    try {
      var value = JSON.parse(localStorage.getItem(key) || '[]');
      return new Set(Array.isArray(value) ? value : []);
    } catch (err) {
      return new Set();
    }
  }

  function saveSet(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(Array.from(value)));
    } catch (err) {
      /* ignore storage failures */
    }
  }

  function loadReaderDensity() {
    try {
      return localStorage.getItem(STORAGE_READER_DENSITY) === 'comfortable' ? 'comfortable' : 'compact';
    } catch (err) {
      return 'compact';
    }
  }

  function saveReaderDensity() {
    try {
      localStorage.setItem(STORAGE_READER_DENSITY, state.readerDensity);
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

  function scoreText(score) {
    return (Number(score) || 0).toFixed(1);
  }

  function getBaseItems() {
    if (!state.data) return [];
    if (state.view === 'readLater') return getReadLaterItems();
    if (state.view === 'history') return (state.historyData || state.data).items || [];
    if (state.view === 'daily') return state.data.daily_push_items || [];
    if (state.view === 'personal') return state.data.personal_items || [];
    if (state.view === 'featured') return state.data.featured_items || [];
    return state.data.items || [];
  }

  function getAllKnownItems() {
    var data = state.data || {};
    var history = state.historyData || {};
    var seen = {};
    return []
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
    if (state.view === 'history') return '历史归档';
    if (state.view === 'daily') return '每日推送';
    if (state.view === 'readLater') return '稍后读';
    if (state.view === 'personal') return '个人关注';
    if (state.view === 'all') return '全部动态';
    return '今日精选';
  }

  function viewDescription() {
    if (state.view === 'history') return '历史累计内容按时间回看，适合复盘信息源质量。';
    if (state.view === 'daily') return '只显示达到每日推送阈值的最高优先级内容。';
    if (state.view === 'readLater') return '本机保存的待读清单。移出只会取消标记，不会删除原始动态。';
    if (state.view === 'personal') return '按你的个人标签和偏好展示，不参与 AI 行业评分排序。';
    if (state.view === 'all') return '保留最近动态，适合搜索、筛选和补充阅读。';
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
    if (((state.data || {}).items || []).some(function (item) { return itemHasTag(item, tag); })) {
      state.view = 'all';
      state.selectedItemId = '';
      return;
    }
    if (((state.historyData || {}).items || []).some(function (item) { return itemHasTag(item, tag); })) {
      state.view = 'history';
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
    var configuredTags = getConfigTagLibrary();
    if (configuredTags.length || (state.config && Array.isArray(state.config.tags))) {
      return configuredTags;
    }
    return uniqueValues([].concat((data && data.tag_library) || [], (data && data.tags) || []));
  }

  function syncConfigTagLibrary(config) {
    if (!config || !Array.isArray(config.tags)) return;
    var tags = getConfigTagLibrary(config);
    if (state.data) {
      state.data.tag_library = tags.slice();
      state.data.tags = filterKnownTags(state.data.tags || [], tags);
    }
    if (state.historyData) {
      state.historyData.tag_library = tags.slice();
      state.historyData.tags = filterKnownTags(state.historyData.tags || [], tags);
    }
    if (state.tag && tags.indexOf(state.tag) === -1) {
      state.tag = '';
      var tagSelect = document.getElementById('tagSelect');
      if (tagSelect) tagSelect.value = '';
    }
  }

  function getConfigTagLibrary(config) {
    var source = config || state.config || {};
    return uniqueValues(Array.isArray(source.tags) ? source.tags : []);
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

  function getMediaUrls(item) {
    if (!item) return [];
    return uniqueValues([item.image_url].concat(Array.isArray(item.media_urls) ? item.media_urls : []));
  }

  function mediaAlt(item, index, total) {
    var suffix = total > 1 ? '（' + (index + 1) + '/' + total + '）' : '';
    return (item && item.title ? item.title : '图片') + suffix;
  }

  function selectedMediaIndex(item) {
    var urls = getMediaUrls(item);
    if (!item || !item.id || !urls.length) return 0;
    var index = Number(state.mediaIndexByItem[item.id]) || 0;
    if (index < 0) index = 0;
    if (index >= urls.length) index = urls.length - 1;
    return index;
  }

  function setMediaIndex(itemId, index) {
    var item = findKnownItem(itemId);
    var urls = getMediaUrls(item);
    if (!item || !urls.length) return;
    var next = Number(index) || 0;
    if (next < 0) next = 0;
    if (next >= urls.length) next = urls.length - 1;
    state.mediaIndexByItem[itemId] = next;
  }

  function renderItemMedia(item, mode) {
    var urls = getMediaUrls(item);
    if (!urls.length) return '';
    if (mode === 'story') {
      if (urls.length === 1) {
        return '<img class="story-media" src="' + escapeHtml(urls[0]) + '" alt="' + escapeHtml(mediaAlt(item, 0, 1)) + '" loading="lazy" referrerpolicy="no-referrer" data-media-image>';
      }
      return [
        '<div class="story-media-strip" aria-label="共 ' + urls.length + ' 张图片">',
        urls.map(function (url, index) {
          return '<img class="story-media story-media-thumb" src="' + escapeHtml(url) + '" alt="' + escapeHtml(mediaAlt(item, index, urls.length)) + '" loading="lazy" referrerpolicy="no-referrer" data-media-image>';
        }).join(''),
        '<span class="media-count">' + urls.length + ' 图</span>',
        '</div>',
      ].join('');
    }

    var selectedIndex = selectedMediaIndex(item);
    var selectedUrl = urls[selectedIndex];
    var itemId = item && item.id ? item.id : '';
    return [
      '<figure class="article-media-wrap" data-media-gallery="' + escapeHtml(itemId) + '">',
      '  <button class="article-media-button" type="button" data-open-media="' + escapeHtml(itemId) + '" data-media-index="' + selectedIndex + '" aria-label="查看大图">',
      '    <img class="article-media" src="' + escapeHtml(selectedUrl) + '" alt="' + escapeHtml(mediaAlt(item, selectedIndex, urls.length)) + '" loading="lazy" referrerpolicy="no-referrer" data-media-image>',
      urls.length > 1 ? '    <span class="article-media-count">' + (selectedIndex + 1) + '/' + urls.length + '</span>' : '',
      '  </button>',
      '  <div class="media-fallback" hidden>图片加载失败，建议打开原文查看。</div>',
      urls.length > 1 ? [
        '  <div class="article-media-thumbs" aria-label="图片缩略图">',
        urls.map(function (url, index) {
          return [
            '<button class="article-media-thumb' + (index === selectedIndex ? ' active' : '') + '" type="button" data-media-thumb="' + escapeHtml(itemId) + '" data-media-index="' + index + '" aria-label="切换到第 ' + (index + 1) + ' 张图片">',
            '  <img src="' + escapeHtml(url) + '" alt="' + escapeHtml(mediaAlt(item, index, urls.length)) + '" loading="lazy" referrerpolicy="no-referrer" data-media-image>',
            '</button>',
          ].join('');
        }).join(''),
        '  </div>',
      ].join('') : '',
      '</figure>',
    ].join('');
  }

  function bindMediaErrorHandlers() {
    document.addEventListener('error', function (event) {
      var target = event.target;
      if (!target || !target.matches || !target.matches('[data-media-image]')) return;
      target.classList.add('is-broken');
      var wrap = target.closest ? target.closest('.article-media-wrap') : null;
      if (wrap) {
        wrap.classList.add('is-broken');
        var fallback = wrap.querySelector('.media-fallback');
        if (fallback) fallback.hidden = false;
      }
    }, true);
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
      ? '历史 ' + ((data.items || []).length) + ' 条'
      : data.history_total_items
        ? '最新 ' + ((data.items || []).length) + ' 条 / 历史 ' + data.history_total_items + ' 条'
        : '抓取 ' + (data.total_fetched || 0) + ' 条';
    metaLine.textContent = [
      data.date || '未知日期',
      countText,
      '精选 ≥ ' + (thresholds.featured || 7.5),
      '推送 > ' + (thresholds.daily_push || 8.5),
    ].join(' · ');
  }

  function renderQueueStats(data, items) {
    var el = document.getElementById('queueStats');
    var dailyCount = data && Array.isArray(data.daily_push_items) ? data.daily_push_items.length : 0;
    var featuredCount = data && Array.isArray(data.featured_items) ? data.featured_items.length : items.length;
    var personalCount = data && Array.isArray(data.personal_items) ? data.personal_items.length : 0;
    var readLaterCount = getReadLaterItems().length;
    el.innerHTML = [
      '<button class="queue-stat" type="button" data-stat-action="all" title="查看全部动态"><strong>' + ((data && (data.items || []).length) || 0) + '</strong><span>最新动态</span></button>',
      '<button class="queue-stat" type="button" data-stat-action="featured" title="查看今日精选"><strong>' + featuredCount + '</strong><span>今日精选</span></button>',
      '<button class="queue-stat" type="button" data-stat-action="personal" title="查看个人关注"><strong>' + personalCount + '</strong><span>个人关注</span></button>',
      '<button class="queue-stat" type="button" data-stat-action="readLater" title="查看稍后读"><strong>' + readLaterCount + '</strong><span>稍后读</span></button>',
      '<button class="queue-stat" type="button" data-stat-action="daily" title="查看每日推送"><strong>' + dailyCount + '</strong><span>每日推送</span></button>',
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
      var read = state.readItems.has(item.id);
      var storyTime = formatDate(item.published_at || item.fetched_at);
      var storyMetaParts = [
        item.source || item.source_type || '未知来源',
      ];
      if (storyTime && storyTime !== '未知') storyMetaParts.push(storyTime);
      storyMetaParts.push(item.category || '未分类');
      return [
        '<button class="story' + (selected ? ' selected' : '') + (read ? ' read' : '') + '" type="button" data-select-item="' + escapeHtml(item.id) + '"' + (selected ? ' aria-current="true"' : '') + '>',
        '  <div>',
        '    <div class="story-meta">' + storyMetaParts.map(function (part) { return '<span>' + escapeHtml(part) + '</span>'; }).join('') + '</div>',
        '    <h3>' + escapeHtml(item.title) + '</h3>',
        '    <p>' + escapeHtml(item.summary_zh || item.reason || '暂无摘要') + '</p>',
        renderItemMedia(item, 'story'),
        '  </div>',
        '  <span class="score ' + scoreClass(item.score || 0) + '">' + scoreText(item.score) + '</span>',
        '</button>',
      ].join('');
    }).join('');
  }

  function renderTags(tags) {
    return (tags || []).slice(0, 6).map(function (tag) {
      return '<span class="tag">' + escapeHtml(tag) + '</span>';
    }).join('');
  }

  function emptyMessage() {
    if (state.view === 'readLater') return '还没有稍后读内容。点击条目里的“稍后读”即可加入。';
    return '没有匹配的动态。';
  }

  function renderReader(item) {
    var panel = document.getElementById('readerPanel');
    if (!item) {
      panel.innerHTML = '<div class="reader-toolbar">暂无可读内容</div><div class="empty">没有匹配的动态。</div>';
      return;
    }

    var favored = state.favorites.has(item.id);
    var later = state.readLater.has(item.id);
    var actionSuggestion = item.action_suggestion || '阅读原文后判断是否需要跟进。';
    var sourceLine = [
      item.source || item.source_type || '未知来源',
      formatDate(item.published_at),
      item.category || '未分类',
      scoreText(item.score),
    ].join(' · ');

    panel.innerHTML = [
      '<div class="reader-toolbar">',
      '  <span>预计阅读 3 分钟 · 已按' + escapeHtml(viewLabel()) + '过滤</span>',
      '  <div class="reader-tools">',
      '    <button class="' + (later ? 'active' : '') + '" type="button" data-read-later-action="' + escapeHtml(item.id) + '">' + (later ? '已稍后读' : '稍后读') + '</button>',
      '    <button class="' + (favored ? 'active' : '') + '" type="button" data-favorite-action="' + escapeHtml(item.id) + '">' + (favored ? '已收藏' : '收藏') + '</button>',
      '    <button type="button" data-copy-summary="' + escapeHtml(item.id) + '">复制摘要</button>',
      '  </div>',
      '</div>',
      '<article class="article">',
      '  <div class="article-source">' + escapeHtml(sourceLine) + '</div>',
      '  <h2>' + escapeHtml(item.title) + '</h2>',
      '  <p class="article-lead">' + escapeHtml(item.summary_zh || '暂无摘要') + '</p>',
      renderItemMedia(item, 'article'),
      '  <section class="article-block">',
      '    <h3>为什么值得读</h3>',
      '    <p>' + escapeHtml(item.reason || '暂无推荐理由。') + '</p>',
      '  </section>',
      '  <section class="article-block">',
      '    <h3>我该关注什么</h3>',
      '    <p>' + escapeHtml(actionSuggestion) + '</p>',
      '  </section>',
      '  <section class="article-block">',
      '    <h3>阅读判断</h3>',
      '    <p>' + escapeHtml(readingJudgement(item)) + '</p>',
      '  </section>',
      '  <div class="reading-actions">',
      '    <a class="button-link" href="' + escapeHtml(item.url) + '" target="_blank" rel="noreferrer">打开原文</a>',
      '    <button class="text-link" type="button" data-preview-url="' + escapeHtml(item.url || '') + '">站内预览</button>',
      '    <button class="text-link" type="button" data-favorite-action="' + escapeHtml(item.id) + '">' + (favored ? '取消收藏' : '加入收藏') + '</button>',
      '    <button class="text-link" type="button" data-read-later-action="' + escapeHtml(item.id) + '">' + (later ? '移出稍后读' : '稍后读') + '</button>',
      '  </div>',
      '  <div class="tag-row">' + renderTags(item.tags) + '</div>',
      '  <section id="inlinePreview" class="inline-preview hidden" aria-live="polite"></section>',
      '</article>',
    ].join('');
  }

  function readingJudgement(item) {
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
    var highestScore = items.reduce(function (max, item) {
      return Math.max(max, Number(item.score) || 0);
    }, 0);
    var sources = countBy(items, 'source').slice(0, 4);
    var maxSourceCount = sources.reduce(function (max, item) {
      return Math.max(max, item.count);
    }, 1);

    panel.innerHTML = [
      '<section class="context-card" data-context-card="summary">',
      '  <div class="context-title"><strong>今日摘要</strong><span>推送 > ' + escapeHtml(thresholds.daily_push || 8.5) + '</span></div>',
      '  <p class="brief">' + escapeHtml(contextBrief(items, selectedItem)) + '</p>',
      '  <div class="priority">',
      '    <div class="priority-row"><i class="dot"></i><span>进入每日推送</span><strong>' + dailyCount + '</strong></div>',
      '    <div class="priority-row"><i class="dot orange"></i><span>精选阈值</span><strong>' + escapeHtml(thresholds.featured || 7.5) + '</strong></div>',
      '    <div class="priority-row"><i class="dot red"></i><span>最高评分</span><strong>' + scoreText(highestScore) + '</strong></div>',
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
    var categories = countBy(items, 'category').slice(0, 3).map(function (item) {
      return item.name;
    });
    var selectedText = selectedItem ? '当前选中“' + selectedItem.title + '”。' : '';
    return '当前列表重点集中在 ' + categories.join('、') + '。建议优先处理高分条目，再按标签扩展阅读。' + selectedText;
  }

  function renderConfigView() {
    document.getElementById('readingQueue').classList.add('hidden');
    document.getElementById('readerPanel').classList.add('hidden');
    document.getElementById('contextPanel').classList.add('hidden');
    document.getElementById('configPanel').classList.remove('hidden');
    document.getElementById('readerShell').classList.add('config-mode');
    if (!state.configLoaded) {
      loadConfig();
      return;
    }
    renderEnvStatus(state.envStatus || []);
    renderConfigForms(state.config || {});
  }

  function renderReaderView() {
    document.getElementById('readingQueue').classList.remove('hidden');
    document.getElementById('readerPanel').classList.remove('hidden');
    document.getElementById('contextPanel').classList.remove('hidden');
    document.getElementById('configPanel').classList.add('hidden');
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
    renderReaderView();
  }

  function renderAll() {
    var data = getActiveData();
    if (data) {
      renderSelectOptions(document.getElementById('tagSelect'), getTagFilterOptions(data), '全部标签');
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
      chooseViewForTag(state.tag);
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
    document.querySelectorAll('.tab').forEach(function (button) {
      button.addEventListener('click', function () {
        state.view = button.dataset.view;
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
    if (action === 'all' || action === 'featured' || action === 'personal' || action === 'readLater' || action === 'daily') {
      state.view = action;
      state.selectedItemId = '';
      renderAll();
      document.getElementById('readerPanel').scrollIntoView({ block: 'start', behavior: 'smooth' });
      return;
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
    state.tag = '';
    state.source = '';
    state.favoritesOnly = false;
    state.selectedItemId = '';
    document.getElementById('searchInput').value = '';
    document.getElementById('minScoreInput').value = '0';
    document.getElementById('minScoreValue').textContent = '0';
    document.getElementById('tagSelect').value = '';
    document.getElementById('sourceSelect').value = '';
    document.getElementById('favoritesOnly').checked = false;
    if (state.view === 'config') state.view = 'featured';
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
      renderApifySocialSettings((config.sources || {}).apify_social || {}),
      renderNewSourceForm(),
      renderExistingSources(config.sources || {}),
    ].join('');
  }

  function renderTagLibraryForm(tags) {
    var selectedTags = normalizeTagLibrary(tags || []);
    return [
      '<section class="config-card">',
      '<h3>固定标签大类</h3>',
      '<form data-action="set_tags" class="config-grid">',
      '<input type="hidden" name="tags" data-tag-library-value value="' + inputValue(selectedTags.join(', ')) + '">',
      '<div class="tag-editor">',
      '  <label class="config-field tag-add-field">',
      '    <span>添加大类</span>',
      '    <select data-tag-add-select>' + renderTagAddOptions(selectedTags) + '</select>',
      '  </label>',
      '  <button type="button" data-tag-add>添加预设</button>',
      '  <label class="config-field tag-add-field">',
      '    <span>自定义大类</span>',
      '    <input type="text" data-tag-custom-input placeholder="例如：价格监控">',
      '  </label>',
      '  <button type="button" data-tag-custom-add>添加自定义</button>',
      '</div>',
      '<div class="tag-library-list" data-tag-library-list>' + renderTagLibraryChips(selectedTags) + '</div>',
      '<div class="form-actions"><button type="submit">保存固定大类</button></div>',
      '</form>',
      '</section>',
    ].join('');
  }

  function normalizeTagLibrary(tags) {
    var seen = {};
    return (tags || []).map(normalizeCustomTag).filter(function (tag) {
      if (!tag || seen[tag]) return false;
      seen[tag] = true;
      return true;
    });
  }

  function normalizeCustomTag(value) {
    var tag = String(value || '').trim().replace(/^#+/, '').trim().replace(/\s+/g, ' ');
    if (!tag || tag.length > 32) return '';
    if (/[,，\n\r\t<>$`{}]/.test(tag)) return '';
    return tag;
  }

  function renderTagAddOptions(selectedTags) {
    var available = TAG_LIBRARY_OPTIONS.filter(function (tag) {
      return selectedTags.indexOf(tag) === -1;
    });
    if (!available.length) return '<option value="">已添加全部大类</option>';
    return '<option value="">选择一个固定大类</option>' + available.map(function (tag) {
      return '<option value="' + escapeHtml(tag) + '">' + escapeHtml(tag) + '</option>';
    }).join('');
  }

  function renderTagLibraryChips(tags) {
    if (!tags.length) return '<div class="empty-inline">尚未选择固定大类。</div>';
    return tags.map(function (tag) {
      return [
        '<span class="tag editable-tag">',
        escapeHtml(tag),
        '<button type="button" aria-label="移除 ' + escapeHtml(tag) + '" data-tag-remove="' + escapeHtml(tag) + '">×</button>',
        '</span>',
      ].join('');
    }).join('');
  }

  function getTagLibraryTags(form) {
    var input = form.querySelector('[data-tag-library-value]');
    if (!input || !input.value.trim()) return [];
    return normalizeTagLibrary(input.value.split(',').map(function (tag) { return tag.trim(); }));
  }

  function setTagLibraryTags(form, tags) {
    var nextTags = normalizeTagLibrary(tags);
    var input = form.querySelector('[data-tag-library-value]');
    var list = form.querySelector('[data-tag-library-list]');
    var select = form.querySelector('[data-tag-add-select]');
    if (input) input.value = nextTags.join(', ');
    if (list) list.innerHTML = renderTagLibraryChips(nextTags);
    if (select) select.innerHTML = renderTagAddOptions(nextTags);
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
      fieldInput('daily_push_limit', '每日推送条数（兼容字段，当前不截断）', filtering.daily_push_limit || 10, 'number', '1', '1', '50'),
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

  function renderApifySocialSettings(apifySocial) {
    var actors = apifySocial.actors || {};
    var tokenEnvNames = apifyTokenEnvNames(apifySocial);
    function actorValue(platform, fallback) {
      return ((actors[platform] || {}).actor_id) || fallback;
    }
    return [
      '<section class="config-card">',
      '<h3>Apify 社交信源</h3>',
      '<form data-action="set_apify_social_settings" class="config-grid">',
      fieldCheckbox('enabled', '启用 Apify 社交源', apifySocial.enabled !== false),
      '<input type="hidden" name="token_env" value="' + inputValue(tokenEnvNames[0] || 'APIFY_TOKEN') + '">',
      fieldTextarea('token_envs', 'Apify Token 环境变量名，每行一个', tokenEnvNames.join('\n')),
      fieldInput('timeout_seconds', 'Actor 超时秒数', apifySocial.timeout_seconds || 180, 'number', '1', '1', '900'),
      fieldInput('actor_x', 'X Actor ID', actorValue('x', 'altimis~scweet'), 'text'),
      fieldInput('actor_instagram', 'Instagram Actor ID', actorValue('instagram', 'apify/instagram-api-scraper'), 'text'),
      fieldInput('actor_facebook', 'Facebook Actor ID', actorValue('facebook', 'whoareyouanas/facebook-group-scraper'), 'text'),
      fieldInput('actor_telegram', 'Telegram Actor ID', actorValue('telegram', 'thescrapelab/apify-telegram-scraper'), 'text'),
      '<div class="form-actions"><button type="submit">保存 Apify 设置</button></div>',
      '</form>',
      '</section>',
    ].join('');
  }

  function apifyTokenEnvNames(apifySocial) {
    var names = Array.isArray(apifySocial.token_envs) ? apifySocial.token_envs.slice() : [];
    if (!names.length && apifySocial.token_env) names.push(apifySocial.token_env);
    if (!names.length) names.push('APIFY_TOKEN');
    return uniqueValues(names);
  }

  function renderNewSourceForm() {
    return [
      '<section class="config-card">',
      '<h3>新增信源</h3>',
      '<form id="newSourceForm" data-new-source="true" class="config-grid">',
      fieldSelect('source_type', '信源类型', 'rss', ['rss', 'github_release', 'github_user', 'reddit_subreddit', 'telegram_channel', 'apify_social']),
      sourceTypeOptions('rss'),
      '<div class="dynamic-fields" data-source-fields="rss">',
      fieldInput('name', 'RSS 名称', '', 'text'),
      fieldInput('url', 'RSS/Atom URL', '', 'url'),
      fieldInput('category', '分类', '', 'text'),
      fieldInput('tags', '固定标签大类，逗号分隔', '', 'text'),
      fieldCheckbox('enabled', '启用', true),
      '</div>',
      '<div class="form-actions"><button type="button" data-test-source="new">测试订阅</button><button type="submit">新增信源</button></div>',
      '</form>',
      '</section>',
    ].join('');
  }

  function sourceTypeOptions(selectedType) {
    var options = [
      ['rss', 'RSS / Atom'],
      ['github_release', 'GitHub Releases'],
      ['github_user', 'GitHub 用户动态'],
      ['reddit_subreddit', 'Reddit'],
      ['telegram_channel', 'Telegram 频道'],
      ['apify_social', 'Apify 社交信源'],
    ];
    return [
      '<div class="source-type-options" aria-label="新增信源类型">',
      options.map(function (option) {
        var value = option[0];
        var label = option[1];
        return '<button class="' + (value === selectedType ? 'active' : '') + '" type="button" data-source-type-option="' + escapeHtml(value) + '">' + escapeHtml(label) + '</button>';
      }).join(''),
      '</div>',
    ].join('');
  }

  function renderExistingSources(sources) {
    var parts = ['<section class="config-card"><h3>已配置的信源</h3><div class="source-list source-groups">'];
    var groupCount = 0;
    function addGroup(label, items, renderer) {
      if (!items.length) return;
      groupCount += 1;
      var enabledCards = [];
      var disabledCards = [];
      items.forEach(function (item, index) {
        var card = renderer(item, index);
        if (item.enabled === false) disabledCards.push(card);
        else enabledCards.push(card);
      });
      parts.push(renderSourceGroup(label, [
        renderSourceStateGroup('已启用', 'enabled', enabledCards),
        renderSourceStateGroup('未启用', 'disabled', disabledCards),
      ].filter(Boolean)));
    }
    addGroup('RSS / Atom', sources.rss || [], renderRssCard);
    addGroup('GitHub', sources.github || [], renderGithubCard);
    addGroup('Reddit', (((sources.reddit || {}).subreddits) || []), renderRedditCard);
    addGroup('Telegram', (((sources.telegram || {}).channels) || []), renderTelegramCard);
    addGroup('Apify 社交信源', ((((sources.apify_social || {}).subscriptions) || [])), renderApifySocialCard);
    if (!groupCount) {
      parts.push('<div class="empty-inline">暂无信源。</div>');
    }
    parts.push('</div></section>');
    return parts.join('');
  }

  function renderSourceGroup(label, sections) {
    var total = sections.reduce(function (count, section) {
      return count + section.count;
    }, 0);
    return [
      '<details class="source-group" data-source-group="' + escapeHtml(label) + '">',
      '<summary><span>' + escapeHtml(label) + '</span><strong>' + total + '</strong></summary>',
      '<div class="source-group-body">',
      sections.map(function (section) { return section.html; }).join(''),
      '</div>',
      '</details>',
    ].join('');
  }

  function renderSourceStateGroup(label, stateName, cards) {
    return {
      count: cards.length,
      html: [
        '<details class="source-state-group" data-source-state="' + escapeHtml(stateName) + '" data-source-state-count="' + cards.length + '">',
        '<summary><span>' + escapeHtml(label) + '</span><strong>' + cards.length + '</strong></summary>',
        '<div class="source-state-body">',
        cards.length ? cards.join('') : '<div class="empty-inline">暂无' + escapeHtml(label) + '信源。</div>',
        '</div>',
        '</details>',
      ].join(''),
    };
  }

  function renderRssCard(item, index) {
    return [
      '<form data-action="upsert_rss" class="source-card">',
      '<input type="hidden" name="index" value="' + index + '">',
      '<div class="source-card-head"><strong>RSS / Atom</strong><button type="button" data-delete-action="delete_rss" data-index="' + index + '">删除</button></div>',
      fieldInput('name', '名称', item.name || '', 'text'),
      fieldInput('url', 'URL', item.url || '', 'url'),
      fieldInput('category', '分类', item.category || '', 'text'),
      fieldInput('tags', '固定标签大类，逗号分隔', (item.tags || []).join(', '), 'text'),
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
      fieldInput('tags', '固定标签大类，逗号分隔', (item.tags || []).join(', '), 'text'),
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
      fieldInput('tags', '固定标签大类，逗号分隔', (item.tags || []).join(', '), 'text'),
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
      fieldInput('tags', '固定标签大类，逗号分隔', (item.tags || []).join(', '), 'text'),
      fieldCheckbox('enabled', '启用', item.enabled !== false),
      '<input type="hidden" name="telegram_enabled" value="true">',
      '<div class="form-actions"><button type="button" data-test-source="telegram_channel">测试订阅</button><button type="submit">保存</button></div>',
      '</form>',
    ].join('');
  }

  function renderApifySocialCard(item, index) {
    var platform = item.platform || 'x';
    var kind = item.kind || defaultApifyKind(platform);
    return [
      '<form data-action="upsert_apify_social_subscription" class="source-card" data-apify-social-form="true">',
      '<input type="hidden" name="index" value="' + index + '">',
      '<div class="source-card-head"><strong>Apify 社交信源</strong><button type="button" data-delete-action="delete_apify_social_subscription" data-index="' + index + '">删除</button></div>',
      fieldSelect('platform', '平台', platform, ['x', 'instagram', 'facebook', 'telegram']),
      fieldSelectOptions('kind', '类型', kind, apifyKindOptions(platform)),
      fieldInput('target', 'URL / handle / 关键词', item.target || '', 'text'),
      fieldInput('fetch_limit', '抓取数量', item.fetch_limit || 20, 'number', '1', '1', '100'),
      fieldInput('tags', '固定标签大类，逗号分隔', (item.tags || []).join(', '), 'text'),
      fieldCheckbox('enabled', '启用', item.enabled !== false),
      '<input type="hidden" name="apify_social_enabled" value="true">',
      '<div class="form-actions"><button type="button" data-test-source="apify_social">测试订阅</button><button type="submit">保存</button></div>',
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

  function fieldSelectOptions(name, label, value, options) {
    return [
      '<label class="config-field">',
      '<span>' + escapeHtml(label) + '</span>',
      '<select name="' + escapeHtml(name) + '">',
      options.map(function (option) {
        var optionValue = Array.isArray(option) ? option[0] : option;
        var optionLabel = Array.isArray(option) ? option[1] : option;
        return '<option value="' + escapeHtml(optionValue) + '"' + selected(value, optionValue) + '>' + escapeHtml(optionLabel) + '</option>';
      }).join(''),
      '</select>',
      '</label>',
    ].join('');
  }

  function apifyKindOptions(platform) {
    return APIFY_SOCIAL_KIND_OPTIONS[platform] || APIFY_SOCIAL_KIND_OPTIONS.x;
  }

  function defaultApifyKind(platform) {
    return apifyKindOptions(platform)[0][0];
  }

  function updateApifyKindOptions(form, platform) {
    if (!form) return;
    var kind = form.querySelector('[name="kind"]');
    if (!kind) return;
    var options = apifyKindOptions(platform || 'x');
    var validValues = options.map(function (option) { return option[0]; });
    var nextValue = validValues.indexOf(kind.value) === -1 ? validValues[0] : kind.value;
    kind.innerHTML = options.map(function (option) {
      return '<option value="' + escapeHtml(option[0]) + '"' + selected(nextValue, option[0]) + '>' + escapeHtml(option[1]) + '</option>';
    }).join('');
  }

  function setConfigMessage(text, kind) {
    var el = document.getElementById('configMessage');
    el.textContent = text || '';
    el.className = 'config-message ' + (kind || '');
  }

  async function loadConfig(options) {
    var opts = options || {};
    if (!opts.silent) setConfigMessage('正在读取配置...', '');
    try {
      var response = await fetch('./api/config?ts=' + Date.now());
      var payload = await response.json();
      if (!response.ok) throw new Error(payload.error || ('HTTP ' + response.status));
      document.getElementById('configPath').textContent = payload.path || 'data/config.json';
      state.config = payload.config || {};
      state.envStatus = payload.env_status || [];
      syncConfigTagLibrary(state.config);
      if (opts.renderForms !== false) {
        renderEnvStatus(state.envStatus);
        renderConfigForms(state.config);
      }
      state.configLoaded = true;
      if (!opts.silent) setConfigMessage('配置已读取。通过表单提交后，后端会校验并保存。', 'ok');
    } catch (err) {
      if (!opts.silent) setConfigMessage('读取失败：' + err.message, 'error');
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
      syncConfigTagLibrary(state.config);
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
        apify_social: 'upsert_apify_social_subscription',
      };
      submitConfigAction(actionByType[type], payload);
      return;
    }

    submitConfigAction(form.dataset.action, formPayload(form));
  }

  function handleConfigFormClick(event) {
    var tagAddButton = event.target.closest('[data-tag-add]');
    if (tagAddButton) {
      var tagForm = tagAddButton.closest('form');
      var tagSelect = tagForm.querySelector('[data-tag-add-select]');
      var tagValue = tagSelect ? tagSelect.value : '';
      if (!tagValue) return;
      setTagLibraryTags(tagForm, getTagLibraryTags(tagForm).concat([tagValue]));
      return;
    }

    var tagRemoveButton = event.target.closest('[data-tag-remove]');
    if (tagRemoveButton) {
      var removeForm = tagRemoveButton.closest('form');
      var removeValue = tagRemoveButton.getAttribute('data-tag-remove');
      setTagLibraryTags(removeForm, getTagLibraryTags(removeForm).filter(function (tag) {
        return tag !== removeValue;
      }));
      return;
    }

    var customTagButton = event.target.closest('[data-tag-custom-add]');
    if (customTagButton) {
      var customForm = customTagButton.closest('form');
      var customInput = customForm.querySelector('[data-tag-custom-input]');
      var customValue = normalizeCustomTag(customInput ? customInput.value : '');
      if (!customValue) {
        setConfigMessage('标签不能为空，不能超过 32 个字符，也不能包含逗号、换行或特殊符号。', 'error');
        return;
      }
      setTagLibraryTags(customForm, getTagLibraryTags(customForm).concat([customValue]));
      if (customInput) customInput.value = '';
      setConfigMessage('自定义标签已加入待保存列表，点击“保存固定大类”后生效。', '');
      return;
    }

    var sourceTypeButton = event.target.closest('[data-source-type-option]');
    if (sourceTypeButton) {
      var sourceTypeForm = sourceTypeButton.closest('form');
      var nextType = sourceTypeButton.getAttribute('data-source-type-option') || 'rss';
      var sourceTypeSelect = sourceTypeForm.querySelector('[name="source_type"]');
      if (sourceTypeSelect) sourceTypeSelect.value = nextType;
      updateNewSourceFields(sourceTypeForm, nextType);
      return;
    }

    var testButton = event.target.closest('[data-test-source]');
    if (testButton) {
      var form = testButton.closest('form');
      var payload = formPayload(form);
      if (testButton.dataset.testSource === 'new') {
        payload.source_type = payload.source_type || 'rss';
      } else {
        payload.source_type = testButton.dataset.testSource;
      }
      if (payload.source_type === 'apify_social') {
        attachApifySocialSettings(payload);
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
      if (result.sample_image_url) detail += ' · 图片：' + result.sample_image_url;
      setConfigMessage('测试成功：' + (result.message || '订阅源可用。') + detail, 'ok');
    } catch (err) {
      setConfigMessage('测试失败：' + err.message, 'error');
    }
  }

  function handleConfigFormChange(event) {
    if (event.target.name === 'source_type') {
      updateNewSourceFields(event.target.closest('form'), event.target.value);
      return;
    }
    if (event.target.name === 'platform') {
      updateApifyKindOptions(event.target.closest('form'), event.target.value);
      return;
    }
    if (event.target.name === 'provider') {
      applyProviderDefaults(event.target.closest('form'), event.target.value);
    }
  }

  function attachApifySocialSettings(payload) {
    var apify = (((state.config || {}).sources || {}).apify_social) || {};
    var actors = apify.actors || {};
    var platform = payload.platform || 'x';
    var tokenEnvNames = apifyTokenEnvNames(apify);
    payload.token_env = tokenEnvNames[0] || 'APIFY_TOKEN';
    payload.token_envs = tokenEnvNames.join('\n');
    payload.timeout_seconds = apify.timeout_seconds || 120;
    if ((actors[platform] || {}).actor_id) {
      payload.actor_id = actors[platform].actor_id;
    }
  }

  function updateNewSourceFields(form, type) {
    if (!form) return;
    var fields = form.querySelector('[data-source-fields]');
    if (fields) {
      fields.setAttribute('data-source-fields', type);
      fields.innerHTML = newSourceFields(type);
    }
    form.querySelectorAll('[data-source-type-option]').forEach(function (button) {
      button.classList.toggle('active', button.getAttribute('data-source-type-option') === type);
    });
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
        fieldInput('tags', '固定标签大类，逗号分隔', '', 'text') +
        fieldCheckbox('enabled', '启用', true);
    }
    if (type === 'github_user') {
      return fieldInput('username', 'Username', '', 'text') +
        fieldInput('tags', '固定标签大类，逗号分隔', '', 'text') +
        fieldCheckbox('enabled', '启用', true);
    }
    if (type === 'reddit_subreddit') {
      return fieldInput('subreddit', 'Subreddit', '', 'text') +
        fieldSelect('sort', '排序', 'hot', ['hot', 'new', 'top', 'rising']) +
        fieldSelect('time_filter', '时间范围', 'day', ['hour', 'day', 'week', 'month', 'year', 'all']) +
        fieldInput('fetch_limit', '抓取数量', 20, 'number', '1', '1', '100') +
        fieldInput('min_score', '最低分数', 10, 'number', '1', '0') +
        fieldInput('tags', '固定标签大类，逗号分隔', '', 'text') +
        '<input type="hidden" name="reddit_enabled" value="true">' +
        fieldCheckbox('enabled', '启用', true);
    }
    if (type === 'telegram_channel') {
      return fieldInput('channel', 'Channel，不含 @', '', 'text') +
        fieldInput('fetch_limit', '抓取数量', 20, 'number', '1', '1', '100') +
        fieldInput('tags', '固定标签大类，逗号分隔', '', 'text') +
        '<input type="hidden" name="telegram_enabled" value="true">' +
        fieldCheckbox('enabled', '启用', true);
    }
    if (type === 'apify_social') {
      return fieldSelect('platform', '平台', 'x', ['x', 'instagram', 'facebook', 'telegram']) +
        fieldSelectOptions('kind', '类型', 'profile', apifyKindOptions('x')) +
        fieldInput('target', 'URL / handle / 关键词', '', 'text') +
        fieldInput('fetch_limit', '抓取数量', 20, 'number', '1', '1', '100') +
        fieldInput('tags', '固定标签大类，逗号分隔', '', 'text') +
        '<input type="hidden" name="apify_social_enabled" value="true">' +
        fieldCheckbox('enabled', '启用', true);
    }
    return fieldInput('name', 'RSS 名称', '', 'text') +
      fieldInput('url', 'RSS/Atom URL', '', 'url') +
      fieldInput('category', '分类', '', 'text') +
      fieldInput('tags', '固定标签大类，逗号分隔', '', 'text') +
      fieldCheckbox('enabled', '启用', true);
  }

  async function loadData() {
    document.getElementById('itemsList').innerHTML = '<div class="empty">正在读取数据...</div>';
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
      await loadConfig({ silent: true, renderForms: false });
      renderAll();
    } catch (err) {
      document.getElementById('metaLine').textContent = '未找到 radar-data.json';
      document.getElementById('itemsList').innerHTML = '<div class="empty">还没有生成数据。请先运行一次抓取任务。</div>';
      document.getElementById('readerPanel').innerHTML = '<div class="empty">暂无可读内容。</div>';
      document.getElementById('contextPanel').innerHTML = '';
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    applyReaderDensity();
    bindMediaErrorHandlers();
    bindEvents();
    loadData();
  });
})();
