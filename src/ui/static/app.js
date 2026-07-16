// Inteliscope static UI: app module.
function currentFeedDataUserId() {
  return state.auth && state.auth.user && state.auth.user.id
    ? state.auth.user.id
    : null;
}

function invalidateFeedDataLoads() {
  state.feedDataLoadToken = (state.feedDataLoadToken || 0) + 1;
  state.feedDataLoadUserId = null;
}

async function loadData(options) {
  options = options || {};
  if (!canUseConfig()) {
    showLoginGate('请先登录后查看信息流。');
    return false;
  }
  var loadToken = (state.feedDataLoadToken || 0) + 1;
  var loadUserId = currentFeedDataUserId();
  state.feedDataLoadToken = loadToken;
  state.feedDataLoadUserId = loadUserId;
  var isCurrent = function () {
    return state.feedDataLoadToken === loadToken &&
      state.feedDataLoadUserId === loadUserId &&
      currentFeedDataUserId() === loadUserId &&
      (typeof options.isCurrent !== 'function' || options.isCurrent());
  };
  document.getElementById('itemsList').innerHTML = '<div class="empty">正在读取数据...</div>';
  try {
    var feedUrl = '/api/feed/latest?ts=' + Date.now();
    if (state.hideDismissed) feedUrl += '&hide_dismissed=true';
    if (state.unreadFirst) feedUrl += '&unread_first=true';
    var response = await fetch(feedUrl);
    var rawPayload = await response.json();
    if (!isCurrent()) return false;
    if (!response.ok) {
      if (response.status === 401) {
        await handleConfigUnauthorized(apiErrorMessage(rawPayload, '请先登录后查看信息流。'));
        if (isCurrent()) showLoginGate('请先登录后查看信息流。');
        return false;
      }
      throw new Error(apiErrorMessage(rawPayload, 'HTTP ' + response.status));
    }
    var nextData = unwrapApiPayload(rawPayload);
    var nextHistoryData = null;
    try {
      var historyResponse = await fetch('/api/feed/history?ts=' + Date.now());
      if (!isCurrent()) return false;
      if (historyResponse.ok) {
        var historyPayload = await historyResponse.json();
        if (!isCurrent()) return false;
        nextHistoryData = unwrapApiPayload(historyPayload);
      }
    } catch (historyErr) {
      if (!isCurrent()) return false;
      nextHistoryData = null;
    }
    if (!isCurrent()) return false;
    state.data = nextData;
    if (nextData && nextData.ai_enabled === false && state.view === 'featured') {
      state.view = 'all';
    }
    if (nextData && nextData.ai_enabled === false && state.view === 'daily') {
      state.view = 'all';
    }
    state.historyData = nextHistoryData;
    syncUserItemStateFromFeed();
    try {
      await refreshUserItemStates({ isCurrent: isCurrent });
    } catch (stateErr) {
      /* keep feed rendering even if item state refresh fails */
    }
    if (!isCurrent()) return false;
    await loadConfig({ silent: true, renderForms: false, isCurrent: isCurrent });
    if (!isCurrent()) return false;
    await loadFeedSchedule({ silent: true, isCurrent: isCurrent });
    if (!isCurrent()) return false;
    if (typeof loadFeedActivity === 'function') {
      await loadFeedActivity({ silent: true, render: false, isCurrent: isCurrent });
      if (!isCurrent()) return false;
    }
    renderAll();
    if (typeof startFeedScheduleWatcher === 'function') startFeedScheduleWatcher();
    return true;
  } catch (err) {
    if (!isCurrent()) return false;
    document.getElementById('metaLine').textContent = '信息流读取失败';
    document.getElementById('itemsList').innerHTML = '<div class="empty">信息流读取失败：' + escapeHtml(err.message || '未知错误') + '</div>';
    document.getElementById('readerPanel').innerHTML = '<div class="empty">暂无可读内容。</div>';
    document.getElementById('contextPanel').innerHTML = '';
    return false;
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
