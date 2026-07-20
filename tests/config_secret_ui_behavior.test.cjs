const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'src', 'ui', 'static', 'config.js'),
  'utf8'
);

function loadConfig(overrides = {}) {
  const context = {
    console,
    FormData,
    HUB_CHANNEL_OPTIONS: ['AI', '工作/项目'],
    TAG_LIBRARY_OPTIONS: ['AI 编程', '行业动态'],
    APIFY_SOCIAL_KIND_OPTIONS: { x: [['profile', 'X 账号'], ['keyword', 'X 关键词']] },
    state: {
      auth: { user: { id: 'owner-id', role: 'owner' } },
      secrets: [
        { id: 'secret-google', name: 'Gemini Primary', kind: 'ai', provider: 'gemini', env_name: 'GOOGLE_API_KEY', is_set: true, used_by: [] },
        { id: 'secret-apify', name: 'Apify Primary', kind: 'apify', provider: 'apify', env_name: 'APIFY_TOKEN', is_set: true, used_by: [] },
      ],
      config: {},
    },
    document: { getElementById() { return { innerHTML: '', textContent: '', className: '' }; } },
    escapeHtml(value) {
      return String(value == null ? '' : value).replace(/[&<>"']/g, (character) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
      })[character]);
    },
    normalizeTagLibrary(value) { return value; },
    normalizePersonalTagLibrary(value) { return value; },
    getConfigTagLibrary() { return ['AI 编程', '行业动态']; },
    getConfigPersonalTagLibrary() { return []; },
    uniqueValues(values) { return Array.from(new Set(values)); },
    canUseConfig() { return true; },
    ...overrides,
  };
  vm.createContext(context);
  vm.runInContext(source, context, { filename: 'config.js' });
  return context;
}

test('owner key manager renders metadata and write-only controls without secret values', () => {
  const context = loadConfig();

  const html = context.renderSecretManager(context.state.secrets);

  assert.match(html, /密钥管理/);
  assert.match(html, /Gemini Primary/);
  assert.match(html, /Apify Primary/);
  assert.match(html, /name="value" type="password"/);
  assert.match(html, /data-secret-rotate="secret-google"/);
  assert.match(html, /data-secret-delete="secret-apify"/);
  assert.doesNotMatch(html, /private-|AIza|apify_api_/);
});

test('key manager disables delete for referenced keys', () => {
  const context = loadConfig();
  context.state.secrets[0].used_by = [{ name: 'gemini' }];

  const html = context.renderSecretManager(context.state.secrets);

  assert.match(html, /data-secret-delete="secret-google"[^>]*disabled/);
  assert.doesNotMatch(html, /data-secret-delete="secret-apify"[^>]*disabled/);
});

test('member cannot render key manager or secret selectors', () => {
  const context = loadConfig({
    state: { auth: { user: { id: 'member-id', role: 'member' } }, secrets: [], config: {} },
  });

  assert.equal(context.renderSecretManager([]), '');
  assert.doesNotMatch(context.renderAiForm({ provider: 'gemini', model: 'gemini-2.5-flash' }), /name="api_key_env"/);
});

test('AI form selects registered provider key and exposes summary and token limits', () => {
  const context = loadConfig();

  const html = context.renderAiForm({
    enabled: true,
    provider: 'gemini',
    model: 'gemini-2.5-flash',
    api_key_env: 'GOOGLE_API_KEY',
    summary_max_chars: 200,
    analysis_max_output_tokens: 800,
  });

  assert.match(html, /<select name="api_key_env"/);
  assert.match(html, /Gemini Primary/);
  assert.match(html, /name="summary_max_chars"[^>]*value="200"/);
  assert.match(html, /name="analysis_max_output_tokens"[^>]*value="800"/);
});

test('Gemini provider defaults to the current stable Flash model', () => {
  const context = loadConfig();

  assert.equal(context.defaultAiModel('gemini'), 'gemini-3.5-flash');
});

test('Apify source fields use registered Apify key selector instead of free text', () => {
  const context = loadConfig();

  const html = context.newSourceFields('apify_social');

  assert.match(html, /<select name="token_env"/);
  assert.match(html, /Apify Primary/);
  assert.doesNotMatch(html, /Apify Key 环境变量名/);
});

test('owner loads secret metadata separately while member never requests admin secrets', async () => {
  const requests = [];
  const context = loadConfig({
    fetch: async (url) => {
      requests.push(url);
      return {
        ok: true,
        async json() {
          return { ok: true, data: { secrets: [{ id: 'secret-new', name: 'New', kind: 'ai', provider: 'gemini', env_name: 'NEW_KEY', is_set: true, used_by: [] }] } };
        },
      };
    },
    unwrapApiPayload(payload) { return payload.data; },
    apiErrorMessage(_payload, fallback) { return fallback; },
  });

  await context.loadAdminSecrets();
  assert.equal(requests.length, 1);
  assert.match(requests[0], /^\/api\/admin\/secrets/);
  assert.equal(context.state.secrets[0].env_name, 'NEW_KEY');

  context.state.auth.user.role = 'member';
  await context.loadAdminSecrets();
  assert.equal(requests.length, 1);
  assert.equal(context.state.secrets.length, 0);
});

test('creating a secret submits the value once, clears the form, and reloads metadata', async () => {
  const requests = [];
  let reset = false;
  let reloaded = false;
  const context = loadConfig({
    fetch: async (url, options) => {
      requests.push({ url, options });
      return {
        ok: true,
        async json() { return { ok: true, data: { id: 'secret-created', is_set: true } }; },
      };
    },
    unwrapApiPayload(payload) { return payload.data; },
    apiErrorMessage(_payload, fallback) { return fallback; },
  });
  context.loadConfig = async () => { reloaded = true; return true; };
  const form = {
    elements: {
      name: { value: 'Gemini Primary' }, kind: { value: 'ai' }, provider: { value: 'gemini' },
      env_name: { value: 'GOOGLE_API_KEY' }, value: { value: 'one-time-private-value' },
    },
    reset() { reset = true; this.elements.value.value = ''; },
  };

  await context.createAdminSecret(form);

  assert.equal(requests[0].url, '/api/admin/secrets');
  assert.equal(requests[0].options.method, 'POST');
  assert.equal(JSON.parse(requests[0].options.body).value, 'one-time-private-value');
  assert.equal(reset, true);
  assert.equal(form.elements.value.value, '');
  assert.equal(reloaded, true);
});
