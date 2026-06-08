// Inteliscope static UI: config module.
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
    renderPersonalTagLibraryForm(config.personal_tags || []),
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
    '<h3>AI 固定大类</h3>',
    '<form data-action="set_tags" class="config-grid">',
    '<input type="hidden" name="tags" data-tag-library-value value="' + inputValue(selectedTags.join(', ')) + '">',
    '<div class="tag-editor">',
    '  <label class="config-field tag-add-field">',
    '    <span>添加大类</span>',
    '    <select data-tag-add-select>' + renderTagAddOptions(selectedTags) + '</select>',
    '  </label>',
    '  <button type="button" data-tag-add>添加预设</button>',
    '</div>',
    '<div class="tag-library-list" data-tag-library-list>' + renderTagLibraryChips(selectedTags) + '</div>',
    '<div class="form-actions"><button type="submit">保存 AI 大类</button></div>',
    '</form>',
    '</section>',
  ].join('');
}

function renderPersonalTagLibraryForm(tags) {
  var selectedTags = normalizePersonalTagLibrary(tags || []);
  return [
    '<section class="config-card">',
    '<h3>个人标签</h3>',
    '<form data-action="set_personal_tags" class="config-grid">',
    '<input type="hidden" name="personal_tags" data-personal-tag-library-value value="' + inputValue(selectedTags.join(', ')) + '">',
    '<div class="tag-editor">',
    '  <label class="config-field tag-add-field">',
    '    <span>新增个人标签</span>',
    '    <input type="text" data-personal-tag-custom-input placeholder="例如：价格监控">',
    '  </label>',
    '  <button type="button" data-personal-tag-custom-add>添加个人标签</button>',
    '</div>',
    '<div class="tag-library-list" data-personal-tag-library-list>' + renderPersonalTagLibraryChips(selectedTags) + '</div>',
    '<div class="form-actions"><button type="submit">保存个人标签</button></div>',
    '</form>',
    '</section>',
  ].join('');
}

function normalizeTagLibrary(tags) {
  var seen = {};
  return (tags || []).map(normalizeCustomTag).filter(function (tag) {
    if (TAG_LIBRARY_OPTIONS.indexOf(tag) === -1) return false;
    if (!tag || seen[tag]) return false;
    seen[tag] = true;
    return true;
  });
}

function normalizePersonalTagLibrary(tags) {
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
  if (!tags.length) return '<div class="empty-inline">尚未选择 AI 大类。</div>';
  return tags.map(function (tag) {
    return [
      '<span class="tag editable-tag">',
      escapeHtml(tag),
      '<button type="button" aria-label="移除 ' + escapeHtml(tag) + '" data-tag-remove="' + escapeHtml(tag) + '">×</button>',
      '</span>',
    ].join('');
  }).join('');
}

function renderPersonalTagLibraryChips(tags) {
  if (!tags.length) return '<div class="empty-inline">尚未添加个人标签。</div>';
  return tags.map(function (tag) {
    return [
      '<span class="tag editable-tag personal-tag">',
      escapeHtml(tag),
      '<button type="button" aria-label="移除 ' + escapeHtml(tag) + '" data-personal-tag-remove="' + escapeHtml(tag) + '">×</button>',
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

function getPersonalTagLibraryTags(form) {
  var input = form.querySelector('[data-personal-tag-library-value]');
  if (!input || !input.value.trim()) return [];
  return normalizePersonalTagLibrary(input.value.split(',').map(function (tag) { return tag.trim(); }));
}

function setPersonalTagLibraryTags(form, tags) {
  var nextTags = normalizePersonalTagLibrary(tags);
  var input = form.querySelector('[data-personal-tag-library-value]');
  var list = form.querySelector('[data-personal-tag-library-list]');
  if (input) input.value = nextTags.join(', ');
  if (list) list.innerHTML = renderPersonalTagLibraryChips(nextTags);
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
    fieldInput('analysis_content_chars', '评分正文截断字符', ai.analysis_content_chars || 1000, 'number', '1', '100', '10000'),
    fieldInput('analysis_comments_chars', '评分评论截断字符', ai.analysis_comments_chars || 1500, 'number', '1', '0', '20000'),
    fieldInput('enrichment_content_chars', '补充分析截断字符', ai.enrichment_content_chars || 4000, 'number', '1', '500', '30000'),
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
    fieldInput('recent_item_limit', '历史预览条数', filtering.recent_item_limit || 20, 'number', '1', '1', '200'),
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
    fieldInput('tags', 'AI 大类，逗号分隔', '', 'text'),
    fieldInput('personal_tags', '个人标签，逗号分隔', '', 'text'),
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
    fieldInput('tags', 'AI 大类，逗号分隔', (item.tags || []).join(', '), 'text'),
    fieldInput('personal_tags', '个人标签，逗号分隔', (item.personal_tags || []).join(', '), 'text'),
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
    fieldInput('tags', 'AI 大类，逗号分隔', (item.tags || []).join(', '), 'text'),
    fieldInput('personal_tags', '个人标签，逗号分隔', (item.personal_tags || []).join(', '), 'text'),
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
    fieldInput('tags', 'AI 大类，逗号分隔', (item.tags || []).join(', '), 'text'),
    fieldInput('personal_tags', '个人标签，逗号分隔', (item.personal_tags || []).join(', '), 'text'),
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
    fieldInput('tags', 'AI 大类，逗号分隔', (item.tags || []).join(', '), 'text'),
    fieldInput('personal_tags', '个人标签，逗号分隔', (item.personal_tags || []).join(', '), 'text'),
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
    fieldInput('tags', 'AI 大类，逗号分隔', (item.tags || []).join(', '), 'text'),
    fieldPersonalTagSelect('personal_tags', '个人标签', item.personal_tags || []),
    fieldSelectOptions('analysis_mode', '分析模式', item.analysis_mode || 'full', [['full', 'AI 评分'], ['personal_only', '个人关注（跳过 AI）']]),
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

function fieldPersonalTagSelect(name, label, values) {
  var selectedTags = normalizePersonalTagLibrary(
    Array.isArray(values)
      ? values
      : String(values || '').split(',').map(function (tag) { return tag.trim(); })
  );
  var current = selectedTags[0] || '';
  var options = uniqueValues(getConfigPersonalTagLibrary().concat(selectedTags));
  return [
    '<label class="config-field">',
    '<span>' + escapeHtml(label) + '</span>',
    '<select name="' + escapeHtml(name) + '" data-personal-tag-source-select>',
    '<option value="">不设置个人标签</option>',
    options.map(function (option) {
      return '<option value="' + escapeHtml(option) + '"' + selected(current, option) + '>' + escapeHtml(option) + '</option>';
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
  if (!canUseConfig()) {
    state.configLoaded = false;
    if (opts.renderForms !== false || state.view === 'config') {
      renderAuthGate();
    }
    return;
  }
  if (!opts.silent) setConfigMessage('正在读取配置...', '');
  try {
    var response = await fetch('./api/config?ts=' + Date.now());
    var payload = await response.json();
    if (!response.ok) {
      if ((response.status === 401 || response.status === 503) && await handleConfigUnauthorized(payload.error)) return;
      throw new Error(payload.error || ('HTTP ' + response.status));
    }
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
  if (!canUseConfig()) {
    renderAuthGate('请先登录后台再修改配置。');
    return;
  }
  setConfigMessage('正在提交...', '');
  try {
    var response = await fetch('./api/config/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: action, payload: payload }),
    });
    var result = await response.json();
    if (!response.ok) {
      if ((response.status === 401 || response.status === 503) && await handleConfigUnauthorized(result.error)) return;
      throw new Error(result.error || ('HTTP ' + response.status));
    }
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

  if (form.id === 'authLoginForm') {
    handleAuthLoginSubmit(event);
    return;
  }

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

  var personalTagRemoveButton = event.target.closest('[data-personal-tag-remove]');
  if (personalTagRemoveButton) {
    var personalRemoveForm = personalTagRemoveButton.closest('form');
    var personalRemoveValue = personalTagRemoveButton.getAttribute('data-personal-tag-remove');
    setPersonalTagLibraryTags(personalRemoveForm, getPersonalTagLibraryTags(personalRemoveForm).filter(function (tag) {
      return tag !== personalRemoveValue;
    }));
    return;
  }

  var customTagButton = event.target.closest('[data-personal-tag-custom-add]');
  if (customTagButton) {
    var customForm = customTagButton.closest('form');
    var customInput = customForm.querySelector('[data-personal-tag-custom-input]');
    var customValue = normalizeCustomTag(customInput ? customInput.value : '');
    if (!customValue) {
      setConfigMessage('标签不能为空，不能超过 32 个字符，也不能包含逗号、换行或特殊符号。', 'error');
      return;
    }
    setPersonalTagLibraryTags(customForm, getPersonalTagLibraryTags(customForm).concat([customValue]));
    if (customInput) customInput.value = '';
    setConfigMessage('个人标签已加入待保存列表，点击“保存个人标签”后生效。', '');
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
  if (!canUseConfig()) {
    renderAuthGate('请先登录后台再测试订阅源。');
    return;
  }
  setConfigMessage('正在测试订阅源...', '');
  try {
    var response = await fetch('./api/source/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    var result = await response.json();
    if (!response.ok) {
      if ((response.status === 401 || response.status === 503) && await handleConfigUnauthorized(result.error)) return;
      throw new Error(result.error || ('HTTP ' + response.status));
    }
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
      fieldInput('tags', 'AI 大类，逗号分隔', '', 'text') +
      fieldInput('personal_tags', '个人标签，逗号分隔', '', 'text') +
      fieldCheckbox('enabled', '启用', true);
  }
  if (type === 'github_user') {
    return fieldInput('username', 'Username', '', 'text') +
      fieldInput('tags', 'AI 大类，逗号分隔', '', 'text') +
      fieldInput('personal_tags', '个人标签，逗号分隔', '', 'text') +
      fieldCheckbox('enabled', '启用', true);
  }
  if (type === 'reddit_subreddit') {
    return fieldInput('subreddit', 'Subreddit', '', 'text') +
      fieldSelect('sort', '排序', 'hot', ['hot', 'new', 'top', 'rising']) +
      fieldSelect('time_filter', '时间范围', 'day', ['hour', 'day', 'week', 'month', 'year', 'all']) +
      fieldInput('fetch_limit', '抓取数量', 20, 'number', '1', '1', '100') +
      fieldInput('min_score', '最低分数', 10, 'number', '1', '0') +
      fieldInput('tags', 'AI 大类，逗号分隔', '', 'text') +
      fieldInput('personal_tags', '个人标签，逗号分隔', '', 'text') +
      '<input type="hidden" name="reddit_enabled" value="true">' +
      fieldCheckbox('enabled', '启用', true);
  }
  if (type === 'telegram_channel') {
    return fieldInput('channel', 'Channel，不含 @', '', 'text') +
      fieldInput('fetch_limit', '抓取数量', 20, 'number', '1', '1', '100') +
      fieldInput('tags', 'AI 大类，逗号分隔', '', 'text') +
      fieldInput('personal_tags', '个人标签，逗号分隔', '', 'text') +
      '<input type="hidden" name="telegram_enabled" value="true">' +
      fieldCheckbox('enabled', '启用', true);
  }
  if (type === 'apify_social') {
    return fieldSelect('platform', '平台', 'x', ['x', 'instagram', 'facebook', 'telegram']) +
      fieldSelectOptions('kind', '类型', 'profile', apifyKindOptions('x')) +
      fieldInput('target', 'URL / handle / 关键词', '', 'text') +
      fieldInput('fetch_limit', '抓取数量', 20, 'number', '1', '1', '100') +
      fieldInput('tags', 'AI 大类，逗号分隔', '', 'text') +
      fieldPersonalTagSelect('personal_tags', '个人标签', []) +
      fieldSelectOptions('analysis_mode', '分析模式', 'full', [['full', 'AI 评分'], ['personal_only', '个人关注（跳过 AI）']]) +
      '<input type="hidden" name="apify_social_enabled" value="true">' +
      fieldCheckbox('enabled', '启用', true);
  }
  return fieldInput('name', 'RSS 名称', '', 'text') +
    fieldInput('url', 'RSS/Atom URL', '', 'url') +
    fieldInput('category', '分类', '', 'text') +
    fieldInput('tags', 'AI 大类，逗号分隔', '', 'text') +
    fieldInput('personal_tags', '个人标签，逗号分隔', '', 'text') +
    fieldCheckbox('enabled', '启用', true);
}
