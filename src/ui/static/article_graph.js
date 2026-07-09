// Inteliscope static UI: article graph panel.
'use strict';

function graphNodesById() {
  var graph = state.articleGraph || {};
  var nodes = graph.nodes || [];
  var byId = {};
  nodes.forEach(function (node) {
    byId[node.id] = node;
  });
  return byId;
}

function ensureArticleGraphLoaded() {
  if (state.articleGraphLoaded || state.articleGraphLoading) {
    return Promise.resolve(state.articleGraph);
  }
  state.articleGraphLoading = true;
  return fetch('/api/archive/graph?ts=' + Date.now())
    .then(function (response) {
      if (!response.ok) throw new Error('HTTP ' + response.status);
      return response.json();
    })
    .then(function (payload) {
      payload = unwrapApiPayload(payload);
      state.articleGraph = payload;
      state.articleGraphLoaded = true;
      return payload;
    })
    .catch(function (err) {
      state.articleGraph = {
        version: 'article-graph-v1',
        stats: { nodes: 0, edges: 0, groups: 0 },
        nodes: [],
        edges: [],
        groups: [],
        error: String(err && err.message ? err.message : err),
      };
      state.articleGraphLoaded = true;
      return state.articleGraph;
    })
    .finally(function () {
      state.articleGraphLoading = false;
    });
}

function openArticleGraph() {
  state.articleGraphOpen = true;
  var panel = document.getElementById('articleGraphPanel');
  if (panel) {
    panel.classList.remove('hidden');
    panel.innerHTML = '<div class="graph-card graph-loading">正在读取文章关系...</div>';
  }
  ensureArticleGraphLoaded().then(renderArticleGraphPanel);
}

function closeArticleGraph() {
  state.articleGraphOpen = false;
  var panel = document.getElementById('articleGraphPanel');
  if (panel) panel.classList.add('hidden');
}

function renderArticleGraphPanel() {
  var panel = document.getElementById('articleGraphPanel');
  if (!panel || !state.articleGraphOpen) return;
  var graph = state.articleGraph || {};
  var stats = graph.stats || {};
  var nodes = graph.nodes || [];
  var edges = graph.edges || [];
  var groups = graph.groups || [];

  if (!nodes.length || !edges.length) {
    panel.innerHTML = [
      '<div class="graph-panel-shell">',
      '  <div class="graph-panel-head">',
      '    <div><strong>文章关系</strong><span>关联分析</span></div>',
      '    <button type="button" data-graph-action="close" aria-label="关闭">×</button>',
      '  </div>',
      '  <div class="graph-empty">',
      graph.error
        ? '还没有生成 article-graph.json。管理员开启 article_graph 后，下一轮抓取会生成。'
        : '当前没有达到分析阈值的文章关系。',
      '  </div>',
      '</div>',
    ].join('');
    return;
  }

  if (!state.selectedGraphNodeId && nodes[0]) {
    state.selectedGraphNodeId = nodes[0].id;
  }

  panel.innerHTML = [
    '<div class="graph-panel-shell">',
    '  <div class="graph-panel-head">',
    '    <div><strong>文章关系</strong><span>关联分析 · ' + escapeHtml(graph.generated_at ? formatDate(graph.generated_at) : '未生成') + '</span></div>',
    '    <button type="button" data-graph-action="close" aria-label="关闭">×</button>',
    '  </div>',
    '  <div class="graph-stats">',
    '    <span><strong>' + escapeHtml(stats.nodes || nodes.length) + '</strong>文章</span>',
    '    <span><strong>' + escapeHtml(stats.edges || edges.length) + '</strong>关系</span>',
    '    <span><strong>' + escapeHtml(stats.groups || groups.length) + '</strong>分组</span>',
    '  </div>',
    renderArticleGraphGroups(groups, edges),
    renderArticleGraphNodeDetail(),
    '</div>',
  ].join('');
}

function renderArticleGraphGroups(groups, edges) {
  if (!groups.length) {
    return '<div class="graph-empty">暂无关系分组。</div>';
  }
  var edgeByKey = {};
  edges.forEach(function (edge) {
    edgeByKey[edge.source + '->' + edge.target + ':' + edge.relation_type] = edge;
  });
  return [
    '<div class="graph-groups">',
    groups.slice(0, 6).map(function (group) {
      var groupEdges = (group.edge_ids || []).map(function (edgeId) {
        return edgeByKey[edgeId];
      }).filter(Boolean);
      return [
        '<section class="graph-card">',
        '  <div class="graph-card-head"><strong>' + escapeHtml(group.title || '关系分组') + '</strong><span>' + scoreText(group.score || 0) + '</span></div>',
        '  <p>' + escapeHtml(group.reason || '') + '</p>',
        groupEdges.slice(0, 3).map(function (edge) {
          return [
            '<button class="graph-edge-card" type="button" data-graph-node="' + escapeHtml(edge.source) + '">',
            '  <span>' + escapeHtml(edge.relation_type) + '</span>',
            '  <strong>' + escapeHtml(edge.reason || '存在关联') + '</strong>',
            '</button>',
          ].join('');
        }).join(''),
        '</section>',
      ].join('');
    }).join(''),
    '</div>',
  ].join('');
}

function renderArticleGraphNodeDetail() {
  var graph = state.articleGraph || {};
  var nodesById = graphNodesById();
  var selected = nodesById[state.selectedGraphNodeId] || (graph.nodes || [])[0];
  if (!selected) return '';
  var relatedEdges = (graph.edges || []).filter(function (edge) {
    return edge.source === selected.id || edge.target === selected.id;
  }).slice(0, 6);
  return [
    '<section class="graph-card graph-detail">',
    '  <div class="graph-card-head"><strong>当前文章</strong><span>' + escapeHtml(scoreText(selected.score || 0)) + '</span></div>',
    '  <h3>' + escapeHtml(selected.title || '') + '</h3>',
    '  <p>' + escapeHtml(selected.summary_zh || '暂无摘要') + '</p>',
    '  <div class="graph-tags">' + (selected.tags || []).slice(0, 5).map(function (tag) { return '<span>' + escapeHtml(tag) + '</span>'; }).join('') + '</div>',
    relatedEdges.length ? [
      '  <div class="graph-related">',
      relatedEdges.map(function (edge) {
        var otherId = edge.source === selected.id ? edge.target : edge.source;
        var other = nodesById[otherId] || {};
        return [
          '<button class="graph-related-item" type="button" data-graph-node="' + escapeHtml(otherId) + '">',
          '  <strong>' + escapeHtml(other.title || otherId) + '</strong>',
          '  <span>' + escapeHtml(edge.reason || '存在关联') + '</span>',
          '</button>',
        ].join('');
      }).join(''),
      '  </div>',
    ].join('') : '<div class="graph-empty small">暂无相关文章。</div>',
    selected.url ? '  <a class="graph-open-link" href="' + escapeHtml(selected.url) + '" target="_blank" rel="noreferrer">打开原文</a>' : '',
    '</section>',
  ].join('');
}

function handleArticleGraphClick(event) {
  var action = event.target.closest('[data-graph-action]');
  if (action && action.getAttribute('data-graph-action') === 'close') {
    closeArticleGraph();
    return;
  }
  var node = event.target.closest('[data-graph-node]');
  if (node) {
    state.selectedGraphNodeId = node.getAttribute('data-graph-node') || '';
    renderArticleGraphPanel();
  }
}
