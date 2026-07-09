// Inteliscope static UI: admin auth module.
function normalizeAuthPayload(rawPayload) {
  var payload = unwrapApiPayload(rawPayload);
  if (payload && Object.prototype.hasOwnProperty.call(payload, 'authenticated')) {
    return {
      auth_enabled: true,
      auth_configured: true,
      authenticated: !!payload.authenticated,
      username: payload.user && payload.user.username ? payload.user.username : '',
      user: payload.user || null,
    };
  }
  return {
    auth_enabled: !!(payload && payload.auth_enabled),
    auth_configured: !payload || payload.auth_configured !== false,
    authenticated: payload && payload.auth_enabled ? !!payload.authenticated : true,
    username: (payload && payload.username) || '',
    user: payload && payload.user ? payload.user : null,
  };
}

async function loadAuthStatus(options) {
  try {
    var response = await fetch('/api/auth/status?ts=' + Date.now());
    var payload = await response.json();
    if (!response.ok) throw new Error(apiErrorMessage(payload, 'HTTP ' + response.status));
    state.auth = normalizeAuthPayload(payload);
  } catch (err) {
    if (!options || !options.silent) {
      setConfigMessage('读取登录状态失败：' + err.message, 'error');
    }
    state.auth = {
      auth_enabled: false,
      auth_configured: true,
      authenticated: true,
      username: '',
      user: null,
    };
  }
  applyAuthUi();
  return state.auth;
}

function canUseConfig() {
  return !state.auth.auth_enabled || state.auth.authenticated;
}

function applyAuthUi() {
  var logoutButton = document.getElementById('logoutBtn');
  if (logoutButton) {
    logoutButton.classList.toggle('hidden', !state.auth.auth_enabled || !state.auth.authenticated);
  }
  var configTab = document.querySelector('[data-view="config"]');
  if (configTab && state.auth.auth_enabled && !state.auth.authenticated) {
    configTab.title = '登录后才能进入配置后台';
  } else if (configTab) {
    configTab.removeAttribute('title');
  }
}

function renderAuthGate(message) {
  document.getElementById('configPath').textContent = state.auth.auth_enabled
    ? '后台需要登录'
    : 'data/config.json';
  document.getElementById('envStatus').innerHTML = '';
  state.configLoaded = false;

  if (state.auth.auth_enabled && !state.auth.auth_configured) {
    document.getElementById('configForms').innerHTML = [
      '<section class="config-card auth-card">',
      '<h3>后台鉴权未配置</h3>',
      '<p>服务端已启用鉴权，但还没有设置管理员密码。请在 .env 中设置 HORIZON_AUTH_PASSWORD 或 HORIZON_AUTH_PASSWORD_HASH 后重启。</p>',
      '</section>',
    ].join('');
    setConfigMessage(message || '后台暂时不可用：缺少管理员密码配置。', 'error');
    return;
  }

  document.getElementById('configForms').innerHTML = [
    '<section class="config-card auth-card">',
    '<h3>登录后台</h3>',
    '<p>请先登录后查看信息流、测试信源或修改配置。</p>',
    '<form id="authLoginForm" class="config-grid">',
    fieldInput('username', '用户名', state.auth.username || 'admin', 'text'),
    fieldInput('password', '密码', '', 'password'),
    '<div class="form-actions"><button type="submit">登录后台</button></div>',
    '</form>',
    '</section>',
  ].join('');
  setConfigMessage(message || '请输入后台账号密码。', '');
}

function showLoginGate(message) {
  state.view = 'config';
  state.data = null;
  state.historyData = null;
  document.getElementById('readingQueue').classList.add('hidden');
  document.getElementById('readerPanel').classList.add('hidden');
  document.getElementById('contextPanel').classList.add('hidden');
  var subscriptionPanel = document.getElementById('subscriptionPanel');
  if (subscriptionPanel) subscriptionPanel.classList.add('hidden');
  document.getElementById('configPanel').classList.remove('hidden');
  document.getElementById('readerShell').classList.add('config-mode');
  if (typeof updateActiveTab === 'function') updateActiveTab();
  renderAuthGate(message || '请先登录后查看信息流。');
}

async function handleAuthLoginSubmit(event) {
  event.preventDefault();
  var form = event.target.closest('form');
  var payload = formPayload(form);
  setConfigMessage('正在登录...', '');
  try {
    var response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: payload.username || '',
        password: payload.password || '',
      }),
    });
    var result = await response.json();
    if (!response.ok) throw new Error(apiErrorMessage(result, 'HTTP ' + response.status));
    state.auth = normalizeAuthPayload(result.auth || result);
    state.configLoaded = false;
    state.subscriptionConsoleLoaded = false;
    applyAuthUi();
    state.view = 'all';
    await loadData();
  } catch (err) {
    setConfigMessage('登录失败：' + err.message, 'error');
  }
}

async function handleAuthLogout() {
  setConfigMessage('正在退出后台...', '');
  try {
    var response = await fetch('/api/auth/logout', { method: 'POST' });
    var result = await response.json();
    if (!response.ok) throw new Error(apiErrorMessage(result, 'HTTP ' + response.status));
    state.auth = normalizeAuthPayload(result.auth || result);
    state.config = null;
    state.envStatus = [];
    state.configLoaded = false;
    state.subscriptionConsole = null;
    state.subscriptionConsoleLoaded = false;
    applyAuthUi();
    showLoginGate('已退出后台。');
  } catch (err) {
    setConfigMessage('退出失败：' + err.message, 'error');
  }
}

async function handleConfigUnauthorized(message) {
  await loadAuthStatus({ silent: true });
  if (state.auth.auth_enabled && !state.auth.authenticated) {
    renderAuthGate(message || '登录已失效，请重新登录后台。');
    return true;
  }
  return false;
}
