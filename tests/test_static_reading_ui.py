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
    assert 'id="articleGraphButton"' in html
    assert 'id="articleGraphPanel"' in html
    assert "STATIC_ASSET_VERSION" in html
    for css_name in ["base.css", "reader.css", "config.css", "media.css", "article_graph.css"]:
        assert f"./{css_name}?v=" in html
    for script_name in ["state.js", "utils.js", "media.js", "auth.js", "reader.js", "config.js", "article_graph.js", "app.js"]:
        assert f"./{script_name}?v=" in html
    assert 'data-view="personal"' in html
    assert 'data-view="readLater"' in html


def test_static_ui_keeps_reader_state_and_render_functions():
    js_bundle = "\n".join(
        (STATIC_DIR / name).read_text(encoding="utf-8")
        for name in ["state.js", "utils.js", "media.js", "auth.js", "reader.js", "config.js", "article_graph.js", "app.js"]
    )

    for key in [
        "ai-radar-favorites",
        "ai-radar-read-later",
        "ai-radar-read-items",
        "ai-radar-reader-density",
    ]:
        assert key in js_bundle

    for function_name in [
        "getSelectedItem",
        "getAllKnownItems",
        "getReadLaterItems",
        "getHistoryBaseItems",
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
        "fieldPersonalTagSelect",
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
        "loadAuthStatus",
        "canUseConfig",
        "renderAuthGate",
        "handleAuthLoginSubmit",
        "handleAuthLogout",
        "handleConfigUnauthorized",
        "ensureArticleGraphLoaded",
        "openArticleGraph",
        "closeArticleGraph",
        "renderArticleGraphPanel",
        "renderArticleGraphGroups",
        "renderArticleGraphNodeDetail",
        "handleArticleGraphClick",
    ]:
        assert f"function {function_name}" in js_bundle

    assert "VIEW_OPTIONS" in js_bundle
    assert "'personal'" in js_bundle
    assert "historyFilter: 'all'" in js_bundle
    assert "URLSearchParams(window.location.search).get('view')" in js_bundle
    assert "envStatus: []" in js_bundle
    assert "auth_enabled" in js_bundle
    assert "HORIZON_AUTH_PASSWORD_HASH" in js_bundle
    assert "登录后台" in js_bundle
    assert "handleAuthLogout" in js_bundle
    assert "renderEnvStatus(state.envStatus || [])" in js_bundle
    assert "loadAuthStatus({ silent: true }).finally(loadData)" in js_bundle
    assert "./article-graph.json?ts=" in js_bundle
    assert "关联分析" in js_bundle
    assert "文章关系" in js_bundle
    assert "./api/article-graph" not in js_bundle
    assert "./api/auth/status" in js_bundle
    assert "./api/auth/login" in js_bundle
    assert "./api/auth/logout" in js_bundle
    assert "data-stat-action" in js_bundle
    assert "data-preview-url" in js_bundle
    assert "formatDate(item.published_at || item.fetched_at)" in js_bundle
    assert "storyMetaParts" in js_bundle
    assert 'data-stat-action="readLater"' in js_bundle
    assert 'data-stat-action="daily"' in js_bundle
    assert 'data-stat-action="personal"' in js_bundle
    assert 'data-stat-action="sources"' not in js_bundle
    assert "today_items" in js_bundle
    assert "today_total_items" in js_bundle
    assert "今日动态" in js_bundle
    assert "查看今日全部动态" in js_bundle
    assert "历史动态" in js_bundle
    assert "历史精选" in js_bundle
    assert "历史个人关注" in js_bundle
    assert "历史推送" in js_bundle
    assert "查看历史个人关注" in js_bundle
    assert "state.historyFilter = action" in js_bundle
    assert "state.historyFilter = 'all'" in js_bundle
    assert "最新动态" not in js_bundle
    assert "每日推送" in js_bundle
    assert "个人关注" in js_bundle
    assert "press-feedback" in js_bundle
    assert "pointerdown" in js_bundle
    assert "TAG_LIBRARY_OPTIONS" in js_bundle
    assert "personal_tags" in js_bundle
    assert "data-personal-tag-source-select" in js_bundle
    assert "不设置个人标签" in js_bundle
    assert "renderPersonalTagLibraryForm" in js_bundle
    assert "AI 固定大类" in js_bundle
    assert "个人标签" in js_bundle
    assert "data-tag-add" in js_bundle
    assert "data-personal-tag-custom-input" in js_bundle
    assert "data-tag-remove" in js_bundle
    assert "state.config && Array.isArray(state.config.tags)" in js_bundle
    assert "state.config && Array.isArray(state.config.personal_tags)" in js_bundle
    assert "data.tag_library" in js_bundle
    assert "data.personal_tag_library" in js_bundle
    assert "state.data.tag_library" in js_bundle
    assert "state.historyData.tag_library" in js_bundle
    assert "syncConfigTagLibrary(state.config)" in js_bundle
    assert "state.data.tag_library = tags.slice()" in js_bundle
    assert "filterKnownTags(state.data.tags || [], tags)" in js_bundle
    assert "chooseViewForTag(state.tag)" in js_bundle
    assert "state.view = 'history'" in js_bundle
    assert "loadConfig({ silent: true, renderForms: false })" in js_bundle
    assert "renderGroupedTagSelectOptions" in js_bundle
    assert "item.image_url" in js_bundle
    assert "item.media_urls" in js_bundle
    assert "article-media" in js_bundle
    assert "story-media" in js_bundle
    assert "article-media-thumbs" in js_bundle
    assert "media-lightbox" in js_bundle
    assert "data-open-media" in js_bundle
    assert "data-media-thumb" in js_bundle
    assert "data-lightbox-action" in js_bundle
    assert "推送 > " in js_bundle
    assert "当前不截断" in js_bundle
    assert "站内预览 ›" not in js_bundle
    assert "关联讨论" not in js_bundle
    assert "加入收藏') + ' ›" not in js_bundle
    assert "稍后读') + ' ›" not in js_bundle
    assert "data-source-type-option" in js_bundle
    assert "data-source-group" in js_bundle
    assert "data-source-state" in js_bundle
    assert "source-state-body" in js_bundle
    assert "已启用" in js_bundle
    assert "未启用" in js_bundle
    assert "暂无' + escapeHtml(label) + '信源" in js_bundle
    assert "source-group-body" in js_bundle
    assert "GitHub Releases" in js_bundle
    assert "Telegram 频道" in js_bundle
    assert "Apify 社交信源" in js_bundle
    assert "apify_social" in js_bundle
    assert "renderApifySocialCard" in js_bundle
    assert "analysis_mode" in js_bundle
    assert "personal_only" in js_bundle
    assert "X 关键词" in js_bundle
    assert "Instagram hashtag" in js_bundle
    assert "Facebook Group" in js_bundle
    assert "Telegram 频道（Apify）" in js_bundle
    assert "还没有稍后读内容" in js_bundle
    assert "移出只会取消标记" in js_bundle
    assert "已复制" in js_bundle
    assert "复制中" in js_bundle
    assert "复制失败" in js_bundle
    assert "阅读提示" not in js_bundle


def test_static_ui_uses_reader_layout_css():
    css = "\n".join(
        (STATIC_DIR / name).read_text(encoding="utf-8")
        for name in ["base.css", "reader.css", "config.css", "media.css", "article_graph.css"]
    )

    assert ".reader-shell" in css
    assert ".reading-queue" in css
    assert ".reader-panel" in css
    assert ".context-panel" in css
    assert ".inline-preview" in css
    assert ".copy-ok" in css
    assert ".copy-error" in css
    assert ".reading-actions" in css
    assert ".queue-stat.active" in css
    assert "justify-content: center" in css
    assert "min-width: 74px" in css
    assert "button.text-link" in css
    assert "appearance: none" in css
    assert ".press-feedback" in css
    assert "@keyframes press-pop" in css
    assert "prefers-reduced-motion: reduce" in css
    assert ".tag-editor" in css
    assert ".editable-tag" in css
    assert ".auth-card" in css
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
    assert ".article-graph-fab" in css
    assert ".article-graph-panel" in css
    assert ".graph-edge-card" in css
    assert ".media-lightbox-nav" in css
    assert "object-fit: cover" in css
    assert ".tabs::-webkit-scrollbar" in css
    assert "overflow-x: auto" in css
    assert "grid-template-columns: repeat(5, minmax(0, 1fr))" in css
    assert "margin-top: clamp(56px, 9vh, 112px)" in css
    assert "margin-top: 28px" in css
    assert "padding-top: 14px" in css
    assert "grid-template-columns: minmax(150px, 34vw) minmax(0, 1fr)" in css
    assert "grid-column: 2" in css
    assert "font-size: 15px" in css
    assert "-webkit-line-clamp: 7" in css
    assert "#0071e3" in css
