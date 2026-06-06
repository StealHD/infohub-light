from pathlib import Path


STATIC_DIR = Path("src/ui/static")


def test_static_ui_exposes_reading_layout_contract():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert "<title>Inteliscope</title>" in html
    assert "<h1>Inteliscope</h1>" in html
    assert 'id="readingQueue"' in html
    assert 'id="readerPanel"' in html
    assert 'id="contextPanel"' in html
    assert 'id="densityToggleBtn"' in html
    assert 'id="configPanel"' in html
    assert "./styles.css?v=20260606-personal-gallery" in html
    assert "./app.js?v=20260606-personal-gallery" in html
    assert 'data-view="personal"' in html
    assert 'data-view="readLater"' in html


def test_static_ui_keeps_reader_state_and_render_functions():
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    for key in [
        "ai-radar-favorites",
        "ai-radar-read-later",
        "ai-radar-read-items",
        "ai-radar-reader-density",
    ]:
        assert key in app_js

    for function_name in [
        "getSelectedItem",
        "getAllKnownItems",
        "getReadLaterItems",
        "findKnownItem",
        "renderQueue",
        "renderReader",
        "renderContext",
        "renderConfigView",
        "emptyMessage",
        "sourceTypeOptions",
        "renderTagLibraryChips",
        "renderTagAddOptions",
        "normalizeCustomTag",
        "getTagLibraryTags",
        "setTagLibraryTags",
        "updateNewSourceFields",
        "renderSourceGroup",
        "renderSourceStateGroup",
        "bindPressFeedback",
        "handleQueueStat",
        "toggleInlinePreview",
        "showCopyFeedback",
        "writeClipboardText",
        "writeClipboardTextFallback",
        "getTagFilterOptions",
        "renderItemMedia",
        "syncConfigTagLibrary",
        "getConfigTagLibrary",
        "filterKnownTags",
        "itemHasTag",
        "chooseViewForTag",
        "getInitialView",
        "getMediaUrls",
        "selectedMediaIndex",
        "setMediaIndex",
        "openLightbox",
        "renderLightbox",
        "moveLightbox",
        "closeLightbox",
    ]:
        assert f"function {function_name}" in app_js

    assert "VIEW_OPTIONS" in app_js
    assert "'personal'" in app_js
    assert "URLSearchParams(window.location.search).get('view')" in app_js
    assert "envStatus: []" in app_js
    assert "renderEnvStatus(state.envStatus || [])" in app_js
    assert "data-stat-action" in app_js
    assert "data-preview-url" in app_js
    assert "formatDate(item.published_at || item.fetched_at)" in app_js
    assert "storyMetaParts" in app_js
    assert 'data-stat-action="readLater"' in app_js
    assert 'data-stat-action="daily"' in app_js
    assert 'data-stat-action="personal"' in app_js
    assert 'data-stat-action="sources"' not in app_js
    assert "每日推送" in app_js
    assert "个人关注" in app_js
    assert "press-feedback" in app_js
    assert "pointerdown" in app_js
    assert "TAG_LIBRARY_OPTIONS" in app_js
    assert "data-tag-add" in app_js
    assert "data-tag-custom-input" in app_js
    assert "data-tag-custom-add" in app_js
    assert "自定义大类" in app_js
    assert "data-tag-remove" in app_js
    assert "state.config && Array.isArray(state.config.tags)" in app_js
    assert "data.tag_library" in app_js
    assert "state.data.tag_library" in app_js
    assert "state.historyData.tag_library" in app_js
    assert "syncConfigTagLibrary(state.config)" in app_js
    assert "state.data.tag_library = tags.slice()" in app_js
    assert "filterKnownTags(state.data.tags || [], tags)" in app_js
    assert "chooseViewForTag(state.tag)" in app_js
    assert "state.view = 'history'" in app_js
    assert "loadConfig({ silent: true, renderForms: false })" in app_js
    assert "renderSelectOptions(document.getElementById('tagSelect'), getTagFilterOptions(data), '全部标签')" in app_js
    assert "item.image_url" in app_js
    assert "item.media_urls" in app_js
    assert "article-media" in app_js
    assert "story-media" in app_js
    assert "article-media-thumbs" in app_js
    assert "media-lightbox" in app_js
    assert "data-open-media" in app_js
    assert "data-media-thumb" in app_js
    assert "data-lightbox-action" in app_js
    assert "推送 > " in app_js
    assert "当前不截断" in app_js
    assert "站内预览 ›" not in app_js
    assert "关联讨论" not in app_js
    assert "加入收藏') + ' ›" not in app_js
    assert "稍后读') + ' ›" not in app_js
    assert "data-source-type-option" in app_js
    assert "data-source-group" in app_js
    assert "data-source-state" in app_js
    assert "source-state-body" in app_js
    assert "已启用" in app_js
    assert "未启用" in app_js
    assert "暂无' + escapeHtml(label) + '信源" in app_js
    assert "source-group-body" in app_js
    assert "GitHub Releases" in app_js
    assert "Telegram 频道" in app_js
    assert "Apify 社交信源" in app_js
    assert "apify_social" in app_js
    assert "renderApifySocialCard" in app_js
    assert "X 关键词" in app_js
    assert "Instagram hashtag" in app_js
    assert "Facebook Group" in app_js
    assert "Telegram 频道（Apify）" in app_js
    assert "还没有稍后读内容" in app_js
    assert "移出只会取消标记" in app_js
    assert "已复制" in app_js
    assert "复制中" in app_js
    assert "复制失败" in app_js
    assert "阅读提示" not in app_js


def test_static_ui_uses_reader_layout_css():
    css = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")

    assert ".reader-shell" in css
    assert ".reading-queue" in css
    assert ".reader-panel" in css
    assert ".context-panel" in css
    assert ".inline-preview" in css
    assert ".copy-ok" in css
    assert ".copy-error" in css
    assert ".reading-actions" in css
    assert "justify-content: center" in css
    assert "min-width: 74px" in css
    assert "button.text-link" in css
    assert "appearance: none" in css
    assert ".press-feedback" in css
    assert "@keyframes press-pop" in css
    assert "prefers-reduced-motion: reduce" in css
    assert ".tag-editor" in css
    assert ".editable-tag" in css
    assert ".source-type-options" in css
    assert ".source-group" in css
    assert ".source-group-body" in css
    assert ".source-state-group" in css
    assert ".source-state-body" in css
    assert ".source-group > summary" in css
    assert ".source-state-group > summary" in css
    assert "summary::-webkit-details-marker" in css
    assert ".story-media" in css
    assert ".article-media" in css
    assert ".story-media-strip" in css
    assert ".article-media-thumbs" in css
    assert ".media-lightbox" in css
    assert ".media-lightbox-nav" in css
    assert "object-fit: cover" in css
    assert ".tabs::-webkit-scrollbar" in css
    assert "overflow-x: auto" in css
    assert "grid-template-columns: repeat(5, minmax(0, 1fr))" in css
    assert "margin-top: clamp(56px, 9vh, 112px)" in css
    assert "margin-top: 28px" in css
    assert "padding-top: 14px" in css
    assert "grid-template-columns: minmax(150px, 34vw) minmax(0, 1fr)" in css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in css
    assert "-webkit-line-clamp: 7" in css
    assert "#0071e3" in css
