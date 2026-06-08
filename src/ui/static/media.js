// Inteliscope static UI: media module.
function getMediaUrls(item) {
  if (!item) return [];
  return uniqueValues([item.image_url].concat(Array.isArray(item.media_urls) ? item.media_urls : []));
}

function mediaAlt(item, index, total) {
  var suffix = total > 1 ? '（' + (index + 1) + '/' + total + '）' : '';
  return (item && item.title ? item.title : '图片') + suffix;
}

function selectedMediaIndex(item) {
  var urls = getMediaUrls(item);
  if (!item || !item.id || !urls.length) return 0;
  var index = Number(state.mediaIndexByItem[item.id]) || 0;
  if (index < 0) index = 0;
  if (index >= urls.length) index = urls.length - 1;
  return index;
}

function setMediaIndex(itemId, index) {
  var item = findKnownItem(itemId);
  var urls = getMediaUrls(item);
  if (!item || !urls.length) return;
  var next = Number(index) || 0;
  if (next < 0) next = 0;
  if (next >= urls.length) next = urls.length - 1;
  state.mediaIndexByItem[itemId] = next;
}

function renderItemMedia(item, mode) {
  var urls = getMediaUrls(item);
  if (!urls.length) return '';
  if (mode === 'story') {
    if (urls.length === 1) {
      return '<img class="story-media" src="' + escapeHtml(urls[0]) + '" alt="' + escapeHtml(mediaAlt(item, 0, 1)) + '" loading="lazy" referrerpolicy="no-referrer" data-media-image>';
    }
    return [
      '<div class="story-media-strip" aria-label="共 ' + urls.length + ' 张图片">',
      urls.map(function (url, index) {
        return '<img class="story-media story-media-thumb" src="' + escapeHtml(url) + '" alt="' + escapeHtml(mediaAlt(item, index, urls.length)) + '" loading="lazy" referrerpolicy="no-referrer" data-media-image>';
      }).join(''),
      '<span class="media-count">' + urls.length + ' 图</span>',
      '</div>',
    ].join('');
  }

  var selectedIndex = selectedMediaIndex(item);
  var selectedUrl = urls[selectedIndex];
  var itemId = item && item.id ? item.id : '';
  return [
    '<figure class="article-media-wrap" data-media-gallery="' + escapeHtml(itemId) + '">',
    '  <button class="article-media-button" type="button" data-open-media="' + escapeHtml(itemId) + '" data-media-index="' + selectedIndex + '" aria-label="查看大图">',
    '    <img class="article-media" src="' + escapeHtml(selectedUrl) + '" alt="' + escapeHtml(mediaAlt(item, selectedIndex, urls.length)) + '" loading="lazy" referrerpolicy="no-referrer" data-media-image>',
    urls.length > 1 ? '    <span class="article-media-count">' + (selectedIndex + 1) + '/' + urls.length + '</span>' : '',
    '  </button>',
    '  <div class="media-fallback" hidden>图片加载失败，建议打开原文查看。</div>',
    urls.length > 1 ? [
      '  <div class="article-media-thumbs" aria-label="图片缩略图">',
      urls.map(function (url, index) {
        return [
          '<button class="article-media-thumb' + (index === selectedIndex ? ' active' : '') + '" type="button" data-media-thumb="' + escapeHtml(itemId) + '" data-media-index="' + index + '" aria-label="切换到第 ' + (index + 1) + ' 张图片">',
          '  <img src="' + escapeHtml(url) + '" alt="' + escapeHtml(mediaAlt(item, index, urls.length)) + '" loading="lazy" referrerpolicy="no-referrer" data-media-image>',
          '</button>',
        ].join('');
      }).join(''),
      '  </div>',
    ].join('') : '',
    '</figure>',
  ].join('');
}

function bindMediaErrorHandlers() {
  document.addEventListener('error', function (event) {
    var target = event.target;
    if (!target || !target.matches || !target.matches('[data-media-image]')) return;
    target.classList.add('is-broken');
    var wrap = target.closest ? target.closest('.article-media-wrap') : null;
    if (wrap) {
      wrap.classList.add('is-broken');
      var fallback = wrap.querySelector('.media-fallback');
      if (fallback) fallback.hidden = false;
    }
  }, true);
}
