// Inteliscope static UI: app module.
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
  loadAuthStatus({ silent: true }).finally(loadData);
});
