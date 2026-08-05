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

var AI_PROVIDER_OPTIONS = [
  ['openai', 'OpenAI'],
  ['deepseek', 'DeepSeek'],
  ['anthropic', 'Anthropic / Claude'],
  ['gemini', 'Google Gemini'],
  ['xiaomi', '小米 MiMo'],
  ['minimax', 'MiniMax'],
  ['ali', '阿里通义'],
  ['doubao', '豆包'],
  ['azure', 'Azure OpenAI'],
  ['ollama', 'Ollama'],
];

var AI_MODEL_OPTIONS = {
  openai: [
    ['gpt-4o-mini', 'gpt-4o-mini'],
    ['gpt-4o', 'gpt-4o'],
    ['gpt-4.1-mini', 'gpt-4.1-mini'],
    ['gpt-4.1', 'gpt-4.1'],
  ],
  deepseek: [
    ['deepseek-v4-flash', 'deepseek-v4-flash'],
    ['deepseek-v4-pro', 'deepseek-v4-pro'],
    ['deepseek-chat', 'deepseek-chat（旧兼容，2026-07-24 后弃用）'],
    ['deepseek-reasoner', 'deepseek-reasoner（旧兼容，2026-07-24 后弃用）'],
  ],
  anthropic: [
    ['claude-3-5-sonnet-latest', 'claude-3-5-sonnet-latest'],
    ['claude-3-7-sonnet-latest', 'claude-3-7-sonnet-latest'],
    ['claude-sonnet-4-5', 'claude-sonnet-4-5'],
  ],
  gemini: [
    ['gemini-3.5-flash', 'gemini-3.5-flash'],
    ['gemini-2.5-flash', 'gemini-2.5-flash'],
    ['gemini-2.5-pro', 'gemini-2.5-pro'],
  ],
  xiaomi: [
    ['mimo-v2.5-pro', 'mimo-v2.5-pro'],
  ],
  minimax: [
    ['MiniMax-Text-01', 'MiniMax-Text-01'],
  ],
  ali: [
    ['qwen-plus', 'qwen-plus'],
    ['qwen-max', 'qwen-max'],
    ['qwen-turbo', 'qwen-turbo'],
  ],
  doubao: [
    ['doubao-1-5-pro-32k-250115', 'doubao-1-5-pro-32k-250115'],
  ],
  azure: [
    ['your-deployment-name', 'your-deployment-name'],
  ],
  ollama: [
    ['llama3.1', 'llama3.1'],
    ['qwen2.5', 'qwen2.5'],
  ],
};

function defaultAiModel(provider) {
  var options = AI_MODEL_OPTIONS[provider] || [];
  return options.length ? options[0][0] : '';
}

function aiModelOptions(provider, currentModel) {
  var current = String(currentModel || '').trim();
  var options = (AI_MODEL_OPTIONS[provider] || []).slice();
  if (current && !options.some(function (option) { return option[0] === current; })) {
    options.unshift([current, current + '（当前配置）']);
  }
  if (!options.length && current) {
    options.push([current, current]);
  }
  return options;
}

function renderConfigForms(config) {
  var forms = document.getElementById('configForms');
  forms.innerHTML = [
    renderSecretManager(state.secrets || []),
    renderCoreSettings(config),
    renderAdvancedSettings(config),
  ].join('');
}

function configUserIsAdmin() {
  var user = state.auth && state.auth.user;
  return !!user && ['owner', 'admin'].indexOf(user.role) >= 0;
}

function secretOptions(kind, provider) {
  return (state.secrets || []).filter(function (secret) {
    if (!secret || secret.kind !== kind || !secret.is_set) return false;
    return !provider || secret.provider === provider;
  }).map(function (secret) {
    return [secret.env_name, secret.name + ' · 已设置'];
  });
}

function fieldSecretSelect(name, label, kind, provider, current) {
  var options = secretOptions(kind, provider);
  var value = String(current || '');
  if (value && !options.some(function (option) { return option[0] === value; })) {
    options.unshift([value, value + ' · 未在密钥管理登记']);
  }
  options.unshift(['', '请选择已设置的 Key']);
  return fieldSelectOptions(name, label, value, options);
}

function renderSecretManager(secrets) {
  if (!configUserIsAdmin()) return '';
  var rows = (secrets || []).map(function (secret) {
    var references = secret.used_by || [];
    var usage = references.map(function (item) { return item.name; }).join('、') || '未使用';
    var deleteState = references.length
      ? ' disabled aria-disabled="true" title="正在使用，不能删除"'
      : '';
    return [
      '<article class="source-card" data-secret-id="' + escapeHtml(secret.id) + '">',
      '<h4>' + escapeHtml(secret.name) + '</h4>',
      '<p class="form-help">' + escapeHtml(secret.kind + ' / ' + secret.provider) + ' · ' +
        (secret.is_set ? '已设置' : '未设置') + ' · ' + escapeHtml(usage) + '</p>',
      '<form data-secret-rotate-form="' + escapeHtml(secret.id) + '" class="config-grid">',
      fieldInput('value', '轮换 Key（写入后不回显）', '', 'password'),
      '<div class="form-actions"><button type="submit" data-secret-rotate="' + escapeHtml(secret.id) + '">轮换</button>' +
        '<button type="button" data-secret-delete="' + escapeHtml(secret.id) + '"' + deleteState + '>删除</button></div>',
      '</form>',
      '</article>',
    ].join('');
  }).join('');
  return [
    '<section class="config-card">',
    '<h3>密钥管理</h3>',
    '<p class="form-help">真实值仅写入本机密钥文件，保存后立即清空，页面永不回显。</p>',
    '<form id="secretCreateForm" class="config-grid">',
    fieldInput('name', 'Key 名称', '', 'text'),
    fieldSelectOptions('kind', '类型', 'ai', [['ai', 'AI'], ['apify', 'Apify']]),
    fieldSelectOptions('provider', 'Provider', 'gemini', [
      ['gemini', 'Gemini'], ['openai', 'OpenAI'], ['anthropic', 'Anthropic'], ['apify', 'Apify'],
    ]),
    fieldInput('env_name', '环境变量名', '', 'text'),
    fieldInput('value', '真实 Key（写入后不回显）', '', 'password'),
    '<div class="form-actions"><button type="submit">新增 Key</button></div>',
    '</form>',
    rows || '<p class="form-help">尚未登记 Key。</p>',
    '</section>',
  ].join('');
}

function renderCoreSettings(config) {
  config = config || {};
  return [
    renderAiForm(config.ai || {}),
    renderPersonalTagLibraryForm(config.personal_tags || []),
    renderHackerNewsForm((config.sources || {}).hackernews || {}),
    renderNewSourceForm({ includeCostSources: false }),
    renderExistingSources(config.sources || {}, { includeCostSources: false }),
  ].join('');
}

function renderAdvancedSettings(config) {
  config = config || {};
  return [
    '<details class="advanced-section">',
    '<summary><span>高级 / 可选能力</span><strong>默认关闭</strong></summary>',
    '<div class="advanced-section-body">',
    renderTagLibraryForm(config.tags || []),
    renderFilteringForm(config.filtering || {}),
    renderWebhookForm(config.webhook || {}),
    renderApifySocialSettings((config.sources || {}).apify_social || {}),
    renderNewSourceForm({ includeCostSources: true, advancedOnly: true }),
    renderExistingSources(config.sources || {}, { includeCostSources: true, costOnly: true }),
    '</div>',
    '</details>',
  ].join('');
}

function renderTagLibraryForm(tags) {
  var selectedTags = normalizeTagLibrary(tags || []);
  return [
    '<section class="config-card">',
    '<h3>阅读主题库</h3>',
    '<form data-action="set_tags" class="config-grid">',
    '<input type="hidden" name="tags" data-tag-library-value value="' + inputValue(selectedTags.join(', ')) + '">',
    '<div class="tag-editor">',
    '  <label class="config-field tag-add-field">',
    '    <span>添加预设主题</span>',
    '    <select data-tag-add-select>' + renderTagAddOptions(selectedTags) + '</select>',
    '  </label>',
    '  <button type="button" data-tag-add>添加预设</button>',
    '  <label class="config-field tag-add-field">',
    '    <span>新增自定义主题</span>',
    '    <input type="text" data-tag-custom-input placeholder="例如：价格监控">',
    '  </label>',
    '  <button type="button" data-tag-custom-add>添加主题</button>',
    '</div>',
    '<div class="tag-library-list" data-tag-library-list>' + renderTagLibraryChips(selectedTags) + '</div>',
    '<div class="form-actions"><button type="submit">保存阅读主题</button></div>',
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
  if (!tag || tag.length > 40) return '';
  if (/[,，\n\r\t<>$`{}]/.test(tag)) return '';
  return tag;
}

function renderTagAddOptions(selectedTags) {
  var available = TAG_LIBRARY_OPTIONS.filter(function (tag) {
    return selectedTags.indexOf(tag) === -1;
  });
  if (!available.length) return '<option value="">已添加全部预设主题</option>';
  return '<option value="">选择一个预设主题</option>' + available.map(function (tag) {
    return '<option value="' + escapeHtml(tag) + '">' + escapeHtml(tag) + '</option>';
  }).join('');
}

function renderTagLibraryChips(tags) {
  if (!tags.length) return '<div class="empty-inline">尚未选择阅读主题。</div>';
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
  var aiEnabled = ai.enabled !== false;
  var provider = ai.provider || 'openai';
  var keyField = configUserIsAdmin()
    ? fieldSecretSelect('api_key_env', 'API Key', 'ai', provider, ai.api_key_env || '')
    : '<p class="form-help">API Key 由管理员配置。</p>';
  return [
    '<section class="config-card' + (aiEnabled ? '' : ' muted') + '">',
    '<h3>AI 模型</h3>',
    aiEnabled ? '' : '<p class="form-help">当前为无评分模式：抓取和页面更新不调用模型，也不校验 API Key。</p>',
    '<form data-action="set_ai" class="config-grid">',
    fieldCheckbox('enabled', '启用 AI 评分', aiEnabled),
    fieldSelectOptions('provider', 'Provider', provider, AI_PROVIDER_OPTIONS),
    fieldAiModelSelect(provider, ai.model || ''),
    keyField,
    fieldInput('languages', '输出语言，逗号分隔', (ai.languages || ['zh']).join(','), 'text'),
    fieldInput('analysis_content_chars', '评分正文截断字符', ai.analysis_content_chars || 1000, 'number', '1', '100', '10000'),
    fieldInput('analysis_comments_chars', '评分评论截断字符', ai.analysis_comments_chars || 1500, 'number', '1', '0', '20000'),
    fieldInput('summary_max_chars', '单篇中文概括最多字符', ai.summary_max_chars || 200, 'number', '1', '100', '500'),
    fieldInput('analysis_max_output_tokens', '单篇分析最大输出 Token', ai.analysis_max_output_tokens || 800, 'number', '1', '256', '2048'),
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
    updateHoursField(),
    '<div class="form-actions"><button type="button" data-test-source="hackernews">测试订阅</button><button type="button" data-update-source="hackernews">立即更新</button><button type="submit">保存 HN 设置</button></div>',
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
    '<h3>Apify 社交信源 <span class="cost-badge">成本源</span></h3>',
    '<form data-action="set_apify_social_settings" class="config-grid">',
    fieldCheckbox('enabled', '启用 Apify 社交源', apifySocial.enabled !== false),
    (configUserIsAdmin()
      ? fieldSecretSelect('token_env', '默认 Apify Key', 'apify', 'apify', tokenEnvNames[0] || '')
      : '<p class="form-help">Apify Key 由管理员配置。</p>'),
    '<input type="hidden" name="token_envs" value="' + inputValue(tokenEnvNames.join(',')) + '">',
    fieldInput('timeout_seconds', 'Actor 超时秒数', apifySocial.timeout_seconds || 180, 'number', '1', '1', '900'),
    fieldInput('actor_x', 'X Actor ID', actorValue('x', 'xquik/x-tweet-scraper'), 'text'),
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

function sourceTypeChoices(includeCostSources) {
  var options = [
    ['rss', 'RSS / Atom'],
    ['github_release', 'GitHub Releases'],
    ['github_user', 'GitHub 用户动态'],
    ['reddit_subreddit', 'Reddit'],
    ['telegram_channel', 'Telegram 频道'],
  ];
  if (includeCostSources) {
    options.push(['apify_social', 'Apify 社交信源']);
  }
  return options;
}

function renderNewSourceForm(options) {
  options = options || {};
  var choices = sourceTypeChoices(options.includeCostSources === true);
  if (options.advancedOnly) {
    choices = choices.filter(function (option) { return option[0] === 'apify_social'; });
  }
  if (!choices.length) return '';
  var initialType = choices[0][0];
  var formId = options.advancedOnly ? 'advancedSourceForm' : 'newSourceForm';
  var title = options.advancedOnly ? '新增成本信源' : '新增信源';
  return [
    '<section class="config-card">',
    '<h3>' + title + (options.advancedOnly ? ' <span class="cost-badge">成本源</span>' : '') + '</h3>',
    '<form id="' + formId + '" data-new-source="true" class="config-grid">',
    fieldSelectOptions('source_type', '信源类型', initialType, choices),
    sourceTypeOptions(initialType, choices),
    '<div class="dynamic-fields" data-source-fields="' + initialType + '">',
    newSourceFields(initialType),
    '</div>',
    '<div class="form-actions"><button type="button" data-test-source="new">测试订阅</button><button type="submit">新增信源</button></div>',
    '</form>',
    '</section>',
  ].join('');
}

function sourceTypeOptions(selectedType, options) {
  options = options || sourceTypeChoices(true);
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

function renderExistingSources(sources, options) {
  options = options || {};
  var includeCostSources = options.includeCostSources !== false;
  var costOnly = options.costOnly === true;
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
  if (!costOnly) {
    addGroup('RSS / Atom', sources.rss || [], renderRssCard);
    addGroup('GitHub', sources.github || [], renderGithubCard);
    addGroup('Reddit', (((sources.reddit || {}).subreddits) || []), renderRedditCard);
    addGroup('Telegram', (((sources.telegram || {}).channels) || []), renderTelegramCard);
  }
  if (includeCostSources) {
    addGroup('Apify 社交信源（成本源，默认关闭）', ((((sources.apify_social || {}).subscriptions) || [])), renderApifySocialCard);
  }
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

function sourceMetaFields(item, index) {
  item = item || {};
  return [
    '<input type="hidden" name="index" value="' + inputValue(index) + '">',
    '<input type="hidden" name="source_id" value="' + inputValue(item.source_id || '') + '">',
    '<input type="hidden" name="subscription_id" value="' + inputValue(item.subscription_id || '') + '">',
    '<input type="hidden" name="scope" value="' + inputValue(item.scope || '') + '">',
  ].join('');
}

function deleteSourceButton(action, index, item) {
  item = item || {};
  return '<button type="button" data-delete-action="' + escapeHtml(action) + '" data-index="' + inputValue(index) + '" data-source-id="' + inputValue(item.source_id || '') + '" data-subscription-id="' + inputValue(item.subscription_id || '') + '">删除</button>';
}

function renderRssCard(item, index) {
  return [
    '<form data-action="upsert_rss" class="source-card">',
    sourceMetaFields(item, index),
    '<div class="source-card-head"><strong>RSS / Atom</strong>' + deleteSourceButton('delete_rss', index, item) + '</div>',
    fieldInput('name', '名称', item.name || '', 'text'),
    fieldInput('url', 'URL', item.url || '', 'url'),
    fieldHubChannelSelect('channel', 'Hub 频道', item.channel || item.category || ''),
    fieldTopicMultiSelect('topics', '阅读主题', item.topics || item.tags || []),
    fieldPersonalTagMultiSelect('personal_tags', '个人标签', item.personal_tags || []),
    fieldCheckbox('enabled', '启用', item.enabled !== false),
    updateHoursField(),
    '<div class="form-actions"><button type="button" data-test-source="rss">测试订阅</button><button type="button" data-update-source="rss">立即更新</button><button type="submit">保存</button></div>',
    '</form>',
  ].join('');
}

function renderGithubCard(item, index) {
  var isRelease = item.type === 'repo_releases';
  return [
    '<form data-action="' + (isRelease ? 'upsert_github_release' : 'upsert_github_user') + '" class="source-card">',
    sourceMetaFields(item, index),
    '<div class="source-card-head"><strong>' + (isRelease ? 'GitHub Release' : 'GitHub 用户动态') + '</strong>' + deleteSourceButton('delete_github', index, item) + '</div>',
    isRelease ? fieldInput('owner', 'Owner', item.owner || '', 'text') : fieldInput('username', 'Username', item.username || '', 'text'),
    isRelease ? fieldInput('repo', 'Repo', item.repo || '', 'text') : '',
    fieldHubChannelSelect('channel', 'Hub 频道', item.channel || item.category || ''),
    fieldTopicMultiSelect('topics', '阅读主题', item.topics || item.tags || []),
    fieldPersonalTagMultiSelect('personal_tags', '个人标签', item.personal_tags || []),
    fieldCheckbox('enabled', '启用', item.enabled !== false),
    updateHoursField(),
    '<div class="form-actions"><button type="button" data-test-source="' + (isRelease ? 'github_release' : 'github_user') + '">测试订阅</button><button type="button" data-update-source="github">立即更新</button><button type="submit">保存</button></div>',
    '</form>',
  ].join('');
}

function renderRedditCard(item, index) {
  return [
    '<form data-action="upsert_reddit_subreddit" class="source-card">',
    sourceMetaFields(item, index),
    '<div class="source-card-head"><strong>Reddit Subreddit</strong>' + deleteSourceButton('delete_reddit_subreddit', index, item) + '</div>',
    fieldInput('subreddit', 'Subreddit', item.subreddit || '', 'text'),
    fieldSelect('sort', '排序', item.sort || 'hot', ['hot', 'new', 'top', 'rising']),
    fieldSelect('time_filter', '时间范围', item.time_filter || 'day', ['hour', 'day', 'week', 'month', 'year', 'all']),
    fieldInput('fetch_limit', '抓取数量', item.fetch_limit || 20, 'number', '1', '1', '100'),
    fieldInput('min_score', '最低分数', item.min_score || 10, 'number', '1', '0'),
    fieldHubChannelSelect('channel', 'Hub 频道', item.channel || item.category || ''),
    fieldTopicMultiSelect('topics', '阅读主题', item.topics || item.tags || []),
    fieldPersonalTagMultiSelect('personal_tags', '个人标签', item.personal_tags || []),
    fieldCheckbox('enabled', '启用', item.enabled !== false),
    '<input type="hidden" name="reddit_enabled" value="true">',
    updateHoursField(),
    '<div class="form-actions"><button type="button" data-test-source="reddit_subreddit">测试订阅</button><button type="button" data-update-source="reddit_subreddit">立即更新</button><button type="submit">保存</button></div>',
    '</form>',
  ].join('');
}

function renderTelegramCard(item, index) {
  return [
    '<form data-action="upsert_telegram_channel" class="source-card">',
    sourceMetaFields(item, index),
    '<div class="source-card-head"><strong>Telegram 公共频道</strong>' + deleteSourceButton('delete_telegram_channel', index, item) + '</div>',
    fieldInput('channel', 'Channel，不含 @', item.channel || '', 'text'),
    fieldInput('fetch_limit', '抓取数量', item.fetch_limit || 20, 'number', '1', '1', '100'),
    fieldHubChannelSelect('category', 'Hub 频道', item.hub_channel || item.category || ''),
    fieldTopicMultiSelect('topics', '阅读主题', item.topics || item.tags || []),
    fieldPersonalTagMultiSelect('personal_tags', '个人标签', item.personal_tags || []),
    fieldCheckbox('enabled', '启用', item.enabled !== false),
    '<input type="hidden" name="telegram_enabled" value="true">',
    updateHoursField(),
    '<div class="form-actions"><button type="button" data-test-source="telegram_channel">测试订阅</button><button type="button" data-update-source="telegram_channel">立即更新</button><button type="submit">保存</button></div>',
    '</form>',
  ].join('');
}

function renderApifySocialCard(item, index) {
  var platform = item.platform || 'x';
  var kind = item.kind || defaultApifyKind(platform);
  return [
    '<form data-action="upsert_apify_social_subscription" class="source-card" data-apify-social-form="true">',
    sourceMetaFields(item, index),
    '<div class="source-card-head"><strong>Apify 社交信源 <span class="cost-badge">成本源</span></strong>' + deleteSourceButton('delete_apify_social_subscription', index, item) + '</div>',
    fieldSelect('platform', '平台', platform, ['x', 'instagram', 'facebook', 'telegram']),
    fieldSelectOptions('kind', '类型', kind, apifyKindOptions(platform)),
    fieldInput('target', 'URL / handle / 关键词', item.target || '', 'text'),
    (configUserIsAdmin()
      ? fieldSecretSelect('token_env', 'Apify Key', 'apify', 'apify', item.token_env || '')
      : '<p class="form-help">Apify Key 由管理员配置。</p>'),
    fieldInput('fetch_limit', '抓取数量', item.fetch_limit || 20, 'number', '1', '1', '100'),
    fieldHubChannelSelect('channel', 'Hub 频道', item.channel || item.category || ''),
    fieldTopicMultiSelect('topics', '阅读主题', item.topics || item.tags || []),
    fieldPersonalTagMultiSelect('personal_tags', '个人标签', item.personal_tags || []),
    fieldSelectOptions('analysis_mode', '分析模式', item.analysis_mode || 'full', [['full', 'AI 评分'], ['personal_only', '只归档（跳过 AI）']]),
    fieldCheckbox('enabled', '启用', item.enabled !== false),
    '<input type="hidden" name="apify_social_enabled" value="true">',
    updateHoursField(),
    '<div class="form-actions"><button type="button" data-test-source="apify_social">测试订阅</button><button type="button" data-update-source="apify_social">立即更新</button><button type="submit">保存</button></div>',
    '</form>',
  ].join('');
}

function defaultUpdateHours() {
  return ((((state.config || {}).filtering || {}).time_window_hours) || 24);
}

function updateHoursField() {
  return fieldInput('update_hours', '补抓小时数', defaultUpdateHours(), 'number', '1', '1', '720');
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

function fieldAiModelSelect(provider, value) {
  var current = String(value || '').trim() || defaultAiModel(provider);
  return fieldSelectOptions('model', 'Model', current, aiModelOptions(provider, current));
}

function fieldHubChannelSelect(name, label, value) {
  var current = String(value || '').trim();
  var channelOptions = current && HUB_CHANNEL_OPTIONS.indexOf(current) === -1
    ? [current].concat(HUB_CHANNEL_OPTIONS)
    : HUB_CHANNEL_OPTIONS.slice();
  return fieldSelectOptions(
    name,
    label,
    current,
    [['', '不设置频道']].concat(channelOptions.map(function (option) {
      return [option, option];
    }))
  );
}

function selectionValues(values) {
  if (Array.isArray(values)) {
    return values.map(function (value) { return String(value || '').trim(); }).filter(Boolean);
  }
  return String(values || '')
    .split(/[,，\n]|\\n/)
    .map(function (value) { return value.trim(); })
    .filter(Boolean);
}

function fieldConfigMultiSelect(name, label, values, options, emptyLabel, selectAttrs) {
  var selectedValues = uniqueValues(selectionValues(values));
  var choices = uniqueValues((options || []).concat(selectedValues));
  var size = Math.min(Math.max(choices.length || 1, 3), 7);
  return [
    '<label class="config-field config-field-multi">',
    '<span>' + escapeHtml(label) + '</span>',
    '<input type="hidden" name="' + escapeHtml(name) + '" data-config-multi-value="' + escapeHtml(name) + '" value="' + inputValue(selectedValues.join(', ')) + '">',
    '<select multiple size="' + size + '" data-config-multi-select="' + escapeHtml(name) + '"' + (selectAttrs || '') + '>',
    choices.length ? choices.map(function (option) {
      return '<option value="' + escapeHtml(option) + '"' + (selectedValues.indexOf(option) >= 0 ? ' selected' : '') + '>' + escapeHtml(option) + '</option>';
    }).join('') : '<option value="" disabled>' + escapeHtml(emptyLabel || '暂无可选项') + '</option>',
    '</select>',
    '</label>',
  ].join('');
}

function fieldTopicMultiSelect(name, label, values) {
  var topics = getConfigTagLibrary();
  if (!topics.length) topics = TAG_LIBRARY_OPTIONS.slice();
  return fieldConfigMultiSelect(name, label, values, topics, '先在阅读主题库添加主题');
}

function fieldPersonalTagMultiSelect(name, label, values) {
  return fieldConfigMultiSelect(
    name,
    label,
    values,
    getConfigPersonalTagLibrary(),
    '不设置个人标签',
    ' data-personal-tag-source-select'
  );
}

function fieldPersonalTagSelect(name, label, values) {
  return fieldPersonalTagMultiSelect(name, label, values);
}

function syncConfigMultiSelect(select) {
  var name = select.getAttribute('data-config-multi-select');
  if (!name) return;
  var form = select.closest('form');
  var hidden = form ? form.querySelector('[data-config-multi-value="' + name + '"]') : null;
  if (!hidden) return;
  hidden.value = Array.from(select.selectedOptions || [])
    .map(function (option) { return option.value; })
    .filter(Boolean)
    .join(', ');
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

async function loadAdminSecrets() {
  if (!configUserIsAdmin()) {
    state.secrets = [];
    return [];
  }
  var response = await fetch('/api/admin/secrets?ts=' + Date.now());
  var rawPayload = await response.json();
  if (!response.ok) throw new Error(apiErrorMessage(rawPayload, '密钥状态读取失败'));
  var payload = unwrapApiPayload(rawPayload) || {};
  state.secrets = payload.secrets || [];
  return state.secrets;
}

async function secretAdminRequest(path, options) {
  var response = await fetch(path, options || {});
  var rawPayload = await response.json();
  if (!response.ok) throw new Error(apiErrorMessage(rawPayload, '密钥操作失败'));
  return unwrapApiPayload(rawPayload);
}

async function createAdminSecret(form) {
  if (!configUserIsAdmin() || !form) return false;
  try {
    await secretAdminRequest('/api/admin/secrets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: String(form.elements.name.value || '').trim(),
        kind: String(form.elements.kind.value || '').trim(),
        provider: String(form.elements.provider.value || '').trim(),
        env_name: String(form.elements.env_name.value || '').trim(),
        value: String(form.elements.value.value || ''),
      }),
    });
    form.reset();
    setConfigMessage('Key 已保存，真实值不会回显。', 'ok');
    await loadConfig({ silent: true });
    return true;
  } catch (err) {
    if (form.elements.value) form.elements.value.value = '';
    setConfigMessage('Key 保存失败：' + err.message, 'error');
    return false;
  }
}

async function rotateAdminSecret(form, secretId) {
  if (!configUserIsAdmin() || !form || !secretId) return false;
  var value = String((form.elements.value && form.elements.value.value) || '');
  try {
    await secretAdminRequest('/api/admin/secrets/' + encodeURIComponent(secretId) + '/value', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value: value }),
    });
    form.reset();
    setConfigMessage('Key 已轮换并立即生效。', 'ok');
    await loadConfig({ silent: true });
    return true;
  } catch (err) {
    if (form.elements.value) form.elements.value.value = '';
    setConfigMessage('Key 轮换失败：' + err.message, 'error');
    return false;
  }
}

async function deleteAdminSecret(secretId) {
  if (!configUserIsAdmin() || !secretId) return false;
  try {
    await secretAdminRequest('/api/admin/secrets/' + encodeURIComponent(secretId), { method: 'DELETE' });
    setConfigMessage('未引用的 Key 已删除。', 'ok');
    await loadConfig({ silent: true });
    return true;
  } catch (err) {
    setConfigMessage('Key 删除失败：' + err.message, 'error');
    return false;
  }
}

async function loadConfig(options) {
  var opts = options || {};
  var isCurrent = typeof opts.isCurrent === 'function' ? opts.isCurrent : function () { return true; };
  if (!canUseConfig()) {
    state.configLoaded = false;
    if (opts.renderForms !== false || state.view === 'config') {
      renderAuthGate();
    }
    return false;
  }
  if (!opts.silent) setConfigMessage('正在读取配置...', '');
  try {
    var response = await fetch('/api/config?ts=' + Date.now());
    var rawPayload = await response.json();
    if (!isCurrent()) return false;
    var payload = unwrapApiPayload(rawPayload);
    if (!response.ok) {
      if ((response.status === 401 || response.status === 503) && await handleConfigUnauthorized(apiErrorMessage(rawPayload, '登录已失效，请重新登录后台。'))) return;
      throw new Error(apiErrorMessage(rawPayload, 'HTTP ' + response.status));
    }
    if (!isCurrent()) return false;
    document.getElementById('configPath').textContent = payload.path || 'data/config.json';
    state.config = payload.config || {};
    state.envStatus = payload.env_status || [];
    await loadAdminSecrets();
    if (!isCurrent()) return false;
    syncConfigTagLibrary(state.config);
    if (opts.renderForms !== false) {
      renderEnvStatus(state.envStatus);
      renderConfigForms(state.config);
    }
    state.configLoaded = true;
    if (!opts.silent) setConfigMessage('配置已读取。通过表单提交后，后端会校验并保存。', 'ok');
    return true;
  } catch (err) {
    if (!isCurrent()) return false;
    if (!opts.silent) setConfigMessage('读取失败：' + err.message, 'error');
    return false;
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
    var response = await fetch('/api/config/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: action, payload: payload }),
    });
    var rawResult = await response.json();
    var result = unwrapApiPayload(rawResult);
    if (!response.ok) {
      if ((response.status === 401 || response.status === 503) && await handleConfigUnauthorized(apiErrorMessage(rawResult, '登录已失效，请重新登录后台。'))) return;
      throw new Error(apiErrorMessage(rawResult, 'HTTP ' + response.status));
    }
    state.config = result.config || state.config;
    syncConfigTagLibrary(state.config);
    renderEnvStatus(result.env_status || []);
    renderConfigForms(state.config);
    setConfigMessage('设置成功。旧配置已备份为 config.json.bak。可点击对应信源的“立即更新”补抓数据。', 'ok');
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

  if (form.id === 'secretCreateForm') {
    createAdminSecret(form);
    return;
  }

  if (form.hasAttribute('data-secret-rotate-form')) {
    rotateAdminSecret(form, form.getAttribute('data-secret-rotate-form'));
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
  var secretDeleteButton = event.target.closest('[data-secret-delete]');
  if (secretDeleteButton) {
    deleteAdminSecret(secretDeleteButton.getAttribute('data-secret-delete'));
    return;
  }
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

  var customTopicButton = event.target.closest('[data-tag-custom-add]');
  if (customTopicButton) {
    var customTopicForm = customTopicButton.closest('form');
    var customTopicInput = customTopicForm.querySelector('[data-tag-custom-input]');
    var customTopicValue = normalizeCustomTag(customTopicInput ? customTopicInput.value : '');
    if (!customTopicValue) {
      setConfigMessage('主题不能为空，不能超过 40 个字符，也不能包含逗号、换行或特殊符号。', 'error');
      return;
    }
    setTagLibraryTags(customTopicForm, getTagLibraryTags(customTopicForm).concat([customTopicValue]));
    if (customTopicInput) customTopicInput.value = '';
    setConfigMessage('阅读主题已加入待保存列表，点击“保存阅读主题”后生效。', '');
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

  var updateButton = event.target.closest('[data-update-source]');
  if (updateButton) {
    var updateForm = updateButton.closest('form');
    var updatePayload = sourceUpdatePayload(updateForm, updateButton.dataset.updateSource);
    updateSource(updatePayload);
    return;
  }

  var button = event.target.closest('[data-delete-action]');
  if (!button) return;
  submitConfigAction(button.dataset.deleteAction, {
    index: button.dataset.index,
    source_id: button.dataset.sourceId || '',
    subscription_id: button.dataset.subscriptionId || '',
  });
}

async function testSource(payload) {
  if (!canUseConfig()) {
    renderAuthGate('请先登录后台再测试订阅源。');
    return;
  }
  setConfigMessage('正在测试订阅源...', '');
  try {
    var response = await fetch('/api/source/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    var rawResult = await response.json();
    var data = unwrapApiPayload(rawResult);
    if (!response.ok) {
      if ((response.status === 401 || response.status === 503) && await handleConfigUnauthorized(apiErrorMessage(rawResult, '登录已失效，请重新登录后台。'))) return;
      throw new Error(apiErrorMessage(rawResult, 'HTTP ' + response.status));
    }
    if (data.job_type) {
      setConfigMessage('任务已排队：' + data.job_type + ' · ' + data.id, 'ok');
      return;
    }
    var detail = data.sample_title
      ? ' 示例：' + data.sample_title + (data.sample_url ? ' · ' + data.sample_url : '')
      : '';
    if (data.sample_image_url) detail += ' · 图片：' + data.sample_image_url;
    setConfigMessage('测试成功：' + (data.message || '订阅源可用。') + detail, 'ok');
  } catch (err) {
    setConfigMessage('测试失败：' + err.message, 'error');
  }
}

function sourceUpdatePayload(form, sourceType) {
  var payload = formPayload(form);
  var hours = payload.update_hours || defaultUpdateHours();
  var result = {
    source_type: sourceType,
    hours: hours,
    source_id: payload.source_id || '',
    subscription_id: payload.subscription_id || '',
  };
  if (sourceType !== 'hackernews') {
    result.index = payload.index;
  }
  return result;
}

async function updateSource(payload) {
  if (!canUseConfig()) {
    renderAuthGate('请先登录后台再更新信源。');
    return;
  }
  setConfigMessage('正在更新单个信源...', '');
  try {
    var response = await fetch('/api/source/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    var rawResult = await response.json();
    var data = unwrapApiPayload(rawResult);
    if (!response.ok) {
      if ((response.status === 401 || response.status === 503) && await handleConfigUnauthorized(apiErrorMessage(rawResult, '登录已失效，请重新登录后台。'))) return;
      throw new Error(apiErrorMessage(rawResult, 'HTTP ' + response.status));
    }
    if (data.job_type) {
      setConfigMessage('任务已排队：' + data.job_type + ' · ' + data.id, 'ok');
      return;
    }
    setConfigMessage(
      '更新完成：' + (data.source_ref || payload.source_type) +
      '，新增写入 ' + (data.fetched || 0) + ' 条' +
      '，已跳过 ' + (data.skipped_existing || 0) + ' 条历史内容' +
      '，AI 分析 ' + (data.analyzed || 0) + ' 条。',
      'ok'
    );
  } catch (err) {
    setConfigMessage('更新失败：' + err.message, 'error');
  }
}

function handleConfigFormChange(event) {
  if (event.target.hasAttribute('data-config-multi-select')) {
    syncConfigMultiSelect(event.target);
    return;
  }
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
  var preferredTokenEnv = String(payload.token_env || '').trim();
  if (preferredTokenEnv) {
    payload.token_env = preferredTokenEnv;
    payload.token_envs = preferredTokenEnv;
  } else {
    delete payload.token_env;
    payload.token_envs = tokenEnvNames.join('\n');
  }
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
  var apiKeyEnv = form.querySelector('[name="api_key_env"]');
  var defaults = {
    openai: { model: 'gpt-4o-mini', env: 'OPENAI_API_KEY' },
    anthropic: { model: 'claude-3-5-sonnet-latest', env: 'ANTHROPIC_API_KEY' },
    gemini: { model: 'gemini-3.5-flash', env: 'GOOGLE_API_KEY' },
    xiaomi: { model: 'mimo-v2.5-pro', env: 'XIAOMI_API_KEY' },
    deepseek: { model: 'deepseek-v4-flash', env: 'DEEPSEEK_API_KEY' },
    minimax: { model: 'MiniMax-Text-01', env: 'MINIMAX_API_KEY' },
    ali: { model: 'qwen-plus', env: 'DASHSCOPE_API_KEY' },
    doubao: { model: 'doubao-1-5-pro-32k-250115', env: 'DOUBAO_API_KEY' },
    azure: { model: 'your-deployment-name', env: 'AZURE_OPENAI_API_KEY' },
    ollama: { model: 'llama3.1', env: 'OLLAMA_API_KEY' },
  };
  var next = defaults[provider];
  if (!next) return;
  updateAiModelOptions(form, provider, next.model);
  if (apiKeyEnv) apiKeyEnv.value = next.env;
}

function updateAiModelOptions(form, provider, preferredModel) {
  var model = form ? form.querySelector('[name="model"]') : null;
  if (!model) return;
  var nextModel = String(preferredModel || '').trim() || defaultAiModel(provider) || model.value;
  model.innerHTML = aiModelOptions(provider, nextModel).map(function (option) {
    var optionValue = Array.isArray(option) ? option[0] : option;
    var optionLabel = Array.isArray(option) ? option[1] : option;
    return '<option value="' + escapeHtml(optionValue) + '"' + selected(nextModel, optionValue) + '>' + escapeHtml(optionLabel) + '</option>';
  }).join('');
  model.value = nextModel;
}

function newSourceFields(type) {
  if (type === 'github_release') {
    return fieldInput('owner', 'Owner', '', 'text') +
      fieldInput('repo', 'Repo', '', 'text') +
      fieldHubChannelSelect('channel', 'Hub 频道', '') +
      fieldTopicMultiSelect('topics', '阅读主题', []) +
      fieldPersonalTagMultiSelect('personal_tags', '个人标签', []) +
      fieldCheckbox('enabled', '启用', true);
  }
  if (type === 'github_user') {
    return fieldInput('username', 'Username', '', 'text') +
      fieldHubChannelSelect('channel', 'Hub 频道', '') +
      fieldTopicMultiSelect('topics', '阅读主题', []) +
      fieldPersonalTagMultiSelect('personal_tags', '个人标签', []) +
      fieldCheckbox('enabled', '启用', true);
  }
  if (type === 'reddit_subreddit') {
    return fieldInput('subreddit', 'Subreddit', '', 'text') +
      fieldSelect('sort', '排序', 'hot', ['hot', 'new', 'top', 'rising']) +
      fieldSelect('time_filter', '时间范围', 'day', ['hour', 'day', 'week', 'month', 'year', 'all']) +
      fieldInput('fetch_limit', '抓取数量', 20, 'number', '1', '1', '100') +
      fieldInput('min_score', '最低分数', 10, 'number', '1', '0') +
      fieldHubChannelSelect('channel', 'Hub 频道', '') +
      fieldTopicMultiSelect('topics', '阅读主题', []) +
      fieldPersonalTagMultiSelect('personal_tags', '个人标签', []) +
      '<input type="hidden" name="reddit_enabled" value="true">' +
      fieldCheckbox('enabled', '启用', true);
  }
  if (type === 'telegram_channel') {
    return fieldInput('channel', 'Channel，不含 @', '', 'text') +
      fieldInput('fetch_limit', '抓取数量', 20, 'number', '1', '1', '100') +
      fieldHubChannelSelect('category', 'Hub 频道', '') +
      fieldTopicMultiSelect('topics', '阅读主题', []) +
      fieldPersonalTagMultiSelect('personal_tags', '个人标签', []) +
      '<input type="hidden" name="telegram_enabled" value="true">' +
      fieldCheckbox('enabled', '启用', true);
  }
  if (type === 'apify_social') {
    return fieldSelect('platform', '平台', 'x', ['x', 'instagram', 'facebook', 'telegram']) +
      fieldSelectOptions('kind', '类型', 'profile', apifyKindOptions('x')) +
      fieldInput('target', 'URL / handle / 关键词', '', 'text') +
      (configUserIsAdmin()
        ? fieldSecretSelect('token_env', 'Apify Key', 'apify', 'apify', '')
        : '<p class="form-help">Apify Key 由管理员配置。</p>') +
      fieldInput('fetch_limit', '抓取数量', 20, 'number', '1', '1', '100') +
      fieldHubChannelSelect('channel', 'Hub 频道', '') +
      fieldTopicMultiSelect('topics', '阅读主题', []) +
      fieldPersonalTagMultiSelect('personal_tags', '个人标签', []) +
      fieldSelectOptions('analysis_mode', '分析模式', 'full', [['full', 'AI 评分'], ['personal_only', '只归档（跳过 AI）']]) +
      '<input type="hidden" name="apify_social_enabled" value="true">' +
      fieldCheckbox('enabled', '启用', true);
  }
  return fieldInput('name', 'RSS 名称', '', 'text') +
    fieldInput('url', 'RSS/Atom URL', '', 'url') +
    fieldHubChannelSelect('channel', 'Hub 频道', '') +
    fieldTopicMultiSelect('topics', '阅读主题', []) +
    fieldPersonalTagMultiSelect('personal_tags', '个人标签', []) +
    fieldCheckbox('enabled', '启用', true);
}
