// Inteliscope static UI: admin auth module.
async function loadAuthStatus(options) {
  try {
    var response = await fetch('./api/auth/status?ts=' + Date.now());
    var payload = await response.json();
    if (!response.ok) throw new Error(payload.error || ('HTTP ' + response.status));
    state.auth = {
      auth_enabled: !!payload.auth_enabled,
      auth_configured: payload.auth_configured !== false,
      authenticated: payload.auth_enabled ? !!payload.authenticated : true,
      username: payload.username || '',
    };
  } catch (err) {
    if (!options || !options.silent) {
      setConfigMessage('读取登录状态失败：' + err.message, 'error');
    }
    state.auth = {
      auth_enabled: false,
      auth_configured: true,
      authenticated: true,
      username: '',
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
    '<p>未登录可以阅读信息流，但不能查看、测试或修改配置。</p>',
    '<form id="authLoginForm" class="config-grid">',
    fieldInput('username', '用户名', state.auth.username || 'admin', 'text'),
    fieldInput('password', '密码', '', 'password'),
    '<div class="form-actions"><button type="submit">登录后台</button></div>',
    '</form>',
    '</section>',
  ].join('');
  setConfigMessage(message || '请输入后台账号密码。', '');
}

async function handleAuthLoginSubmit(event) {
  event.preventDefault();
  var form = event.target.closest('form');
  var payload = formPayload(form);
  setConfigMessage('正在登录...', '');
  try {
    var response = await fetch('./api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: payload.username || '',
        password: payload.password || '',
      }),
    });
    var result = await response.json();
    if (!response.ok) throw new Error(result.error || ('HTTP ' + response.status));
    if (result.auth) state.auth = result.auth;
    state.configLoaded = false;
    applyAuthUi();
    await loadConfig();
  } catch (err) {
    setConfigMessage('登录失败：' + err.message, 'error');
  }
}

async function handleAuthLogout() {
  setConfigMessage('正在退出后台...', '');
  try {
    var response = await fetch('./api/auth/logout', { method: 'POST' });
    var result = await response.json();
    if (!response.ok) throw new Error(result.error || ('HTTP ' + response.status));
    if (result.auth) state.auth = result.auth;
    state.config = null;
    state.envStatus = [];
    state.configLoaded = false;
    applyAuthUi();
    renderAuthGate('已退出后台。');
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
