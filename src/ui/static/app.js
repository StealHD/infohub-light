// Inteliscope static UI: app module.
async function loadData() {
  if (!canUseConfig()) {
    showLoginGate('请先登录后查看信息流。');
    return;
  }
  document.getElementById('itemsList').innerHTML = '<div class="empty">正在读取数据...</div>';
  try {
    var feedUrl = '/api/feed/latest?ts=' + Date.now();
    if (state.hideDismissed) feedUrl += '&hide_dismissed=true';
    if (state.unreadFirst) feedUrl += '&unread_first=true';
    var response = await fetch(feedUrl);
    var rawPayload = await response.json();
    if (!response.ok) {
      if (response.status === 401) {
        await handleConfigUnauthorized(apiErrorMessage(rawPayload, '请先登录后查看信息流。'));
        showLoginGate('请先登录后查看信息流。');
        return;
      }
      throw new Error(apiErrorMessage(rawPayload, 'HTTP ' + response.status));
    }
    state.data = unwrapApiPayload(rawPayload);
    if (state.data && state.data.ai_enabled === false && state.view === 'featured') {
      state.view = 'all';
    }
    if (state.data && state.data.ai_enabled === false && state.view === 'daily') {
      state.view = 'all';
    }
    state.historyData = null;
    try {
      var historyResponse = await fetch('/api/feed/history?ts=' + Date.now());
      if (historyResponse.ok) state.historyData = unwrapApiPayload(await historyResponse.json());
    } catch (historyErr) {
      state.historyData = null;
    }
    syncUserItemStateFromFeed();
    try {
      await refreshUserItemStates();
    } catch (stateErr) {
      /* keep feed rendering even if item state refresh fails */
    }
    await loadConfig({ silent: true, renderForms: false });
    renderAll();
  } catch (err) {
    document.getElementById('metaLine').textContent = '未找到 /api/feed/latest';
    document.getElementById('itemsList').innerHTML = '<div class="empty">还没有生成数据。请先运行一次抓取任务。</div>';
    document.getElementById('readerPanel').innerHTML = '<div class="empty">暂无可读内容。</div>';
    document.getElementById('contextPanel').innerHTML = '';
  }
}

async function bootApp() {
  if (!canUseConfig()) {
    showLoginGate('请先登录后查看信息流。');
    return;
  }
  await loadData();
}

document.addEventListener('DOMContentLoaded', function () {
  applyReaderDensity();
  bindMediaErrorHandlers();
  bindEvents();
  loadAuthStatus({ silent: true }).then(bootApp);
});
