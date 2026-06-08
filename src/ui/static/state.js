// Inteliscope static UI: state module.
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
  historyFilter: 'all',
  mediaIndexByItem: {},
  lightbox: null,
  auth: {
    auth_enabled: false,
    auth_configured: true,
    authenticated: true,
    username: '',
  },
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
