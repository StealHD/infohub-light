from pathlib import Path
from datetime import datetime, timezone
import json
import re

from src.models import ContentItem, SourceType
from src.ui.site import build_site_payload, backfill_static_site_taxonomy


STATIC_DIR = Path("src/ui/static")
STATIC_ASSET_VERSION = "20260713-local-ai-secrets-v2"


def test_static_ui_exposes_reading_layout_contract():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert "<title>Inscope | Private &amp; Insights</title>" in html
    assert "<h1>Inscope</h1>" in html
    assert 'id="readingQueue"' in html
    assert 'id="readerPanel"' in html
    assert 'id="contextPanel"' in html
    assert 'id="densityToggleBtn"' in html
    assert 'id="refreshBtn"' in html
    assert '>获取新内容</button>' in html
    assert 'id="channelSelect"' in html
    assert 'id="configPanel"' in html
    assert 'id="articleGraphButton"' not in html
    assert 'id="articleGraphPanel"' not in html
    assert f'window.STATIC_ASSET_VERSION = "{STATIC_ASSET_VERSION}"' in html
    for css_name in ["base.css", "reader.css", "config.css", "media.css", "subscriptions.css"]:
        assert f"./{css_name}?v={STATIC_ASSET_VERSION}" in html
    for script_name in ["state.js", "utils.js", "media.js", "auth.js", "reader.js", "config.js", "subscriptions.js", "app.js"]:
        assert f"./{script_name}?v={STATIC_ASSET_VERSION}" in html
    asset_versions = re.findall(r'(?:href|src)="\./[^"?]+\?v=([^"]+)"', html)
    assert asset_versions
    assert set(asset_versions) == {STATIC_ASSET_VERSION}
    assert "article_graph.css" not in html
    assert "article_graph.js" not in html
    assert not (STATIC_DIR / "article_graph.css").exists()
    assert not (STATIC_DIR / "article_graph.js").exists()
    assert 'data-view="personal"' not in html
    assert ">个人关注<" not in html
    assert 'data-view="readLater"' in html


def test_static_ui_keeps_reader_state_and_render_functions():
    html = STATIC_DIR.joinpath("index.html").read_text(encoding="utf-8")
    js_bundle = "\n".join(
        (STATIC_DIR / name).read_text(encoding="utf-8")
        for name in ["state.js", "utils.js", "media.js", "auth.js", "reader.js", "config.js", "subscriptions.js", "app.js"]
    )

    for key in [
        "ai-radar-favorites",
        "ai-radar-read-later",
        "ai-radar-reader-density",
    ]:
        assert key in js_bundle
    assert "ai-radar-read-items" not in js_bundle

    for function_name in [
        "getSelectedItem",
        "getAllKnownItems",
        "getReadLaterItems",
        "getHistoryBaseItems",
        "findKnownItem",
        "renderQueue",
        "renderReader",
        "renderInsightBlocks",
        "renderContext",
        "renderConfigView",
        "emptyMessage",
        "sourceTypeOptions",
        "renderTagLibraryChips",
        "renderTagAddOptions",
        "normalizeCustomTag",
        "fieldPersonalTagSelect",
        "fieldAiModelSelect",
        "updateAiModelOptions",
        "getTagLibraryTags",
        "setTagLibraryTags",
        "updateNewSourceFields",
        "renderSourceGroup",
        "renderSourceStateGroup",
        "bindPressFeedback",
        "handleQueueStat",
        "showCopyFeedback",
        "writeClipboardText",
        "writeClipboardTextFallback",
        "getTagFilterOptions",
        "getChannelFilterOptions",
        "normalizeHubChannel",
        "itemChannel",
        "renderItemMedia",
        "syncConfigTagLibrary",
        "getConfigTagLibrary",
        "filterKnownTags",
        "itemHasTag",
        "chooseViewForTag",
        "getInitialView",
        "getMediaUrls",
        "plainText",
        "displayText",
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
    ]:
        assert f"function {function_name}" in js_bundle

    assert "VIEW_OPTIONS" in js_bundle
    assert "HUB_CHANNEL_OPTIONS" in js_bundle
    assert "VIEW_OPTIONS = ['featured', 'all', 'readLater', 'history', 'daily', 'subscriptions', 'config']" in js_bundle
    assert "VIEW_OPTIONS = ['featured', 'personal'" not in js_bundle
    assert "historyFilter: 'all'" in js_bundle
    assert "feedSchedule: null" in js_bundle
    assert "feedScheduleLoaded: false" in js_bundle
    assert "feedScheduleLoading: false" in js_bundle
    assert "sourceHealth: null" in js_bundle
    assert "sourceHealthLoading: false" in js_bundle
    assert "sourceHealthLoadToken: 0" in js_bundle
    assert "hideDismissed: false" in js_bundle
    assert "unreadFirst: false" in js_bundle
    assert "URLSearchParams(window.location.search).get('view')" in js_bundle
    assert "envStatus: []" in js_bundle
    assert "auth_enabled" in js_bundle
    assert "HORIZON_AUTH_PASSWORD_HASH" in js_bundle
    assert "登录后台" in js_bundle
    assert "handleAuthLogout" in js_bundle
    assert "renderEnvStatus(state.envStatus || [])" in js_bundle
    assert "function bootApp" in js_bundle
    assert "function formatFeedFreshness" in js_bundle
    assert "Feed 更新于 " in js_bundle
    assert "Feed 更新时间未知" in js_bundle
    assert "await loadFeedSchedule({ silent: true, isCurrent: isCurrent })" in js_bundle
    assert "function invalidateFeedDataLoads" in js_bundle
    assert "document.getElementById('refreshBtn').addEventListener('click', refreshMyFeed)" in js_bundle
    assert "document.getElementById('refreshBtn').addEventListener('click', loadData)" not in js_bundle
    assert "setInterval" not in js_bundle
    assert "loadAuthStatus({ silent: true }).then(bootApp)" in js_bundle
    assert "loadAuthStatus({ silent: true }).finally(loadData)" not in js_bundle
    assert "showLoginGate" in js_bundle
    assert "请先登录后查看信息流。" in js_bundle
    assert "/api/archive/graph" not in js_bundle
    assert "articleGraph" not in js_bundle
    assert "article_graph" not in html
    assert "关联分析" not in html
    assert "文章关系" not in html
    assert "./article-graph.json?ts=" not in js_bundle
    assert "./radar-data.json?ts=" not in js_bundle
    assert "./history-data.json?ts=" not in js_bundle
    assert "/api/feed/latest?ts=" in js_bundle
    assert "hide_dismissed=true" in js_bundle
    assert "unread_first=true" in js_bundle
    assert "/api/feed/history?ts=" in js_bundle
    assert "/api/config?ts=" in js_bundle
    assert "/api/me/item-state" in js_bundle
    assert "/api/me/items/" in js_bundle
    assert "/state" in js_bundle
    assert "user_state" in js_bundle
    assert "data-item-state-action" in js_bundle
    assert 'data-item-state-action="dismissed"' in js_bundle
    assert 'data-item-state-action="is_saved"' in js_bundle
    assert 'data-item-state-action="is_later"' in js_bundle
    assert "加入收藏" in js_bundle
    assert "稍后读" in js_bundle
    assert "忽略" in js_bundle
    assert "submitItemFeedback" not in js_bundle
    assert "data-feedback-action" not in js_bundle
    assert "/feedback" not in js_bundle
    assert "更多类似" not in js_bundle
    assert "减少类似" not in js_bundle
    assert "不相关" not in js_bundle
    assert "function markRead" not in js_bundle
    assert "markRead(selectedItem)" not in js_bundle
    assert "hideDismissed" in js_bundle
    assert "unreadFirst" in js_bundle
    assert "隐藏已忽略" in html
    assert "未读优先" in html
    assert "state.hideDismissed" in js_bundle
    assert "state.unreadFirst" in js_bundle
    assert "item_state_counts" in js_bundle
    assert "dismissed_count" in js_bundle
    assert "/api/config/action" in js_bundle
    assert "/api/source/test" in js_bundle
    assert "/api/source/update" in js_bundle
    assert "./api/config?ts=" not in js_bundle
    assert "./api/config/action" not in js_bundle
    assert "./api/source/test" not in js_bundle
    assert "./api/source/update" not in js_bundle
    assert "unwrapApiPayload(rawPayload)" in js_bundle
    assert "source_id" in js_bundle
    assert "subscription_id" in js_bundle
    assert "scope" in js_bundle
    assert "任务已排队" in js_bundle
    assert "data.job_type" in js_bundle
    assert "normalizeAuthPayload" in js_bundle
    assert "payload.user.username" in js_bundle
    assert "/api/auth/status" in js_bundle
    assert "/api/auth/login" in js_bundle
    assert "/api/auth/logout" in js_bundle
    assert "./api/auth/status" not in js_bundle
    assert "./api/auth/login" not in js_bundle
    assert "./api/auth/logout" not in js_bundle
    assert "data-stat-action" in js_bundle
    assert "data-preview-url" not in js_bundle
    assert "inlinePreview" not in js_bundle
    assert "toggleInlinePreview" not in js_bundle
    assert "站内预览" not in js_bundle
    assert "原网页预览" not in js_bundle
    assert "打开原文" in js_bundle
    assert 'target="_blank" rel="noreferrer">打开原文</a>' in js_bundle
    assert "formatDate(item.published_at || item.fetched_at)" in js_bundle
    assert "storyMetaParts" in js_bundle
    assert "displayText(item.summary_zh || item.reason" not in js_bundle
    assert "displayText(item.summary_zh" in js_bundle
    assert "为什么值得读" not in js_bundle
    assert "推荐理由：" not in js_bundle
    assert 'data-stat-action="readLater"' in js_bundle
    assert 'data-stat-action="daily"' not in js_bundle
    assert 'data-stat-action="personal"' not in js_bundle
    assert 'data-stat-action="sources"' not in js_bundle
    assert "today_items" in js_bundle
    assert "today_total_items" in js_bundle
    assert "今日动态" in js_bundle
    assert "查看今日全部动态" in js_bundle
    assert "历史动态" in js_bundle
    assert "回看已经离开最新 Feed 的信息。" in js_bundle
    assert "历史累计内容按时间回看，适合复盘信息源质量。" not in js_bundle
    assert "历史精选" in js_bundle
    assert "历史个人关注" not in js_bundle
    assert "历史推送" not in js_bundle
    assert "查看历史个人关注" not in js_bundle
    assert "state.historyFilter = action" in js_bundle
    assert "state.historyFilter = 'all'" in js_bundle
    assert "最新动态" not in js_bundle
    assert "个人关注" not in js_bundle
    assert "state.view === 'personal'" not in js_bundle
    assert "press-feedback" in js_bundle
    assert "pointerdown" in js_bundle
    assert "TAG_LIBRARY_OPTIONS" in js_bundle
    assert "personal_tags" in js_bundle
    assert "data-personal-tag-source-select" in js_bundle
    assert "data-config-multi-select" in js_bundle
    assert "fieldHubChannelSelect" in js_bundle
    assert "fieldTopicMultiSelect" in js_bundle
    assert "fieldPersonalTagMultiSelect" in js_bundle
    assert "不设置个人标签" in js_bundle
    assert "renderPersonalTagLibraryForm" in js_bundle
    assert "阅读主题库" in js_bundle
    assert "fieldInput('topics'" not in js_bundle
    assert "fieldInput('channel', 'Hub 频道'" not in js_bundle
    assert "fieldInput('category', 'Hub 频道'" not in js_bundle
    assert "Hub 频道" in js_bundle
    assert "启用 AI 评分" in js_bundle
    assert "当前为无评分模式" in js_bundle
    assert "AI_PROVIDER_OPTIONS" in js_bundle
    assert "AI_MODEL_OPTIONS" in js_bundle
    assert "DeepSeek" in js_bundle
    assert "deepseek-v4-flash" in js_bundle
    assert "deepseek-v4-pro" in js_bundle
    assert "deepseek-chat" in js_bundle
    assert "deepseek-reasoner" in js_bundle
    assert "DEEPSEEK_API_KEY" in js_bundle
    assert "aiEnabled" in js_bundle
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
    assert "loadConfig({ silent: true, renderForms: false, isCurrent: isCurrent })" in js_bundle
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
    assert "Apify Key 环境变量名（可选）" not in js_bundle
    assert "fieldSecretSelect('token_env', 'Apify Key'" in js_bundle
    assert "renderSecretManager" in js_bundle
    assert "item.token_env || ''" in js_bundle
    assert "analysis_mode" in js_bundle
    assert "personal_only" in js_bundle
    assert "item.channel || item.category" in js_bundle
    assert "item.topics || item.tags" in js_bundle
    assert "state.channel" in js_bundle
    assert ".concat((data && data.categories)" not in js_bundle
    assert ".concat(HUB_CHANNEL_OPTIONS)\n      .concat((data && data.channels)" in js_bundle
    assert "countBy(items, 'category')" not in js_bundle
    assert "signal_strength" in js_bundle
    assert "signal_type" in js_bundle
    assert "entities" in js_bundle
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


def test_subscription_console_static_contract():
    html = STATIC_DIR.joinpath("index.html").read_text(encoding="utf-8")
    subscription_js_path = STATIC_DIR.joinpath("subscriptions.js")
    subscription_css_path = STATIC_DIR.joinpath("subscriptions.css")

    assert 'data-view="subscriptions"' in html
    assert 'id="subscriptionPanel"' in html
    assert 'id="feedActivityBanner"' in html
    assert "./subscriptions.js?v=" in html
    assert "./subscriptions.css?v=" in html
    assert subscription_js_path.exists()
    assert subscription_css_path.exists()

    subscriptions_js = subscription_js_path.read_text(encoding="utf-8")
    subscriptions_css = subscription_css_path.read_text(encoding="utf-8")
    for function_name in [
        "loadSubscriptionConsole",
        "renderSubscriptionConsole",
        "subscribeToSource",
        "unsubscribeFromSource",
        "toggleSubscription",
        "refreshMyFeed",
        "loadJobsPreview",
        "createPrivateSource",
        "renderAdvancedSourceForm",
        "createAdvancedSource",
        "importConfigSources",
        "renderMemberManagement",
        "createMember",
        "updateMember",
        "pollJobUntilTerminal",
        "resumeActiveFeedJobPoll",
        "loadFeedSchedule",
        "saveFeedSchedule",
        "renderFeedScheduleCard",
        "feedScheduleSkipReason",
        "updateFeedRefreshButtons",
        "loadSourceHealth",
        "renderSourceHealthSummary",
        "renderSourceHealthDetails",
        "loadFeedActivity",
        "renderSourceEditor",
        "renderSubscriptionEditor",
        "saveSourceEditor",
        "saveSubscriptionEditor",
        "sourceEditorPayload",
        "subscriptionEditorPayload",
    ]:
        assert f"function {function_name}" in subscriptions_js
    assert "/api/dashboard/summary" in subscriptions_js
    assert "/api/catalog/sources" in subscriptions_js
    assert "/api/catalog/source-types" in subscriptions_js
    assert "/api/catalog/import-config-sources" in subscriptions_js
    assert "/api/me/subscriptions" in subscriptions_js
    assert "/api/me/feed-schedule" in subscriptions_js
    assert "/api/me/source-health" in subscriptions_js
    assert "/api/jobs/user-feed-refresh" in subscriptions_js
    assert "/api/jobs" in subscriptions_js
    assert "/api/feed/history" in subscriptions_js
    assert "/api/archive/source-quality" not in subscriptions_js
    assert "/api/users" in subscriptions_js
    assert "renderApiStatus" in subscriptions_js
    assert "API 状态" in subscriptions_js
    assert "用户作用域 Feed / 历史" in subscriptions_js
    assert "feed / archive" not in subscriptions_js
    assert "最新 snapshot" in subscriptions_js
    assert "失败任务" in subscriptions_js
    assert "Worker" in subscriptions_js
    assert "sourceQuality" not in subscriptions_js
    assert "percentText" not in subscriptions_js
    assert "subscription-quality-list" not in subscriptions_js
    assert "还没有用户作用域归档数据" not in subscriptions_js
    assert "成员管理" in subscriptions_js
    assert "memberManagementForm" in subscriptions_js
    assert "data-member-update" in subscriptions_js
    assert "重置密码" in subscriptions_js
    assert "owner/admin" in subscriptions_js
    assert "2000" in subscriptions_js
    assert "180000" in subscriptions_js
    assert "consecutiveFailures" in subscriptions_js
    assert "worker_status" in subscriptions_js
    assert "await loadData({ isCurrent: isCurrent })" in subscriptions_js
    assert "function reloadFeedForTerminalJob" in subscriptions_js
    assert "任务仍在后台运行" in subscriptions_js
    assert "任务已排队但暂不会执行" in subscriptions_js
    assert "自动更新信息流" in subscriptions_js
    assert "allowed_intervals" in subscriptions_js
    assert "interval_minutes" in subscriptions_js
    assert "last_enqueued_at" in subscriptions_js
    assert "next_run_at" in subscriptions_js
    assert "last_skip_reason" in subscriptions_js
    assert "active_job" in subscriptions_js
    assert "deduplicated" in subscriptions_js
    assert "已有刷新任务" in subscriptions_js
    assert "Worker stale" not in subscriptions_js  # rendered from the response value
    assert 'scope: "private"' in subscriptions_js or 'scope:"private"' in subscriptions_js
    assert "state.auth.user.role === 'viewer'" in subscriptions_js
    assert "viewer 只读，不能执行写操作" in subscriptions_js
    assert "secret_env" in subscriptions_js
    assert "订阅" in subscriptions_js
    assert "公共源市场" in subscriptions_js
    assert "我的订阅" in subscriptions_js
    assert "来源健康" in subscriptions_js
    assert "需关注" in subscriptions_js
    assert "连续失败" in subscriptions_js
    assert "尚未抓取" in subscriptions_js
    assert "重新抓取" in subscriptions_js
    assert "私有 RSS 源" in subscriptions_js
    assert "高级源测试" in subscriptions_js
    assert "source_type" in subscriptions_js
    assert "advancedSourceForm" in subscriptions_js
    assert ".subscription-console" in subscriptions_css
    assert ".subscription-card" in subscriptions_css
    assert ".subscription-api-status" in subscriptions_css
    assert ".advanced-source-form" in subscriptions_css
    assert ".feed-schedule-card" in subscriptions_css
    assert ".feed-schedule-form" in subscriptions_css
    assert ".feed-schedule-status" in subscriptions_css
    assert ".feed-schedule-warning" in subscriptions_css
    assert ".source-health-summary" in subscriptions_css
    assert ".source-health-badge" in subscriptions_css
    assert ".source-health-diagnostics" in subscriptions_css
    assert ".feed-activity-banner" in subscriptions_css
    assert ".source-editor" in subscriptions_css
    assert ".subscription-editor" in subscriptions_css
    assert ".source-test-result" in subscriptions_css
    assert ".source-health-summary button" in subscriptions_css
    assert ".subscription-quality-list" not in subscriptions_css


def test_feed_activity_and_editor_static_contract():
    state_js = STATIC_DIR.joinpath("state.js").read_text(encoding="utf-8")
    utils_js = STATIC_DIR.joinpath("utils.js").read_text(encoding="utf-8")
    reader_js = STATIC_DIR.joinpath("reader.js").read_text(encoding="utf-8")
    subscriptions_js = STATIC_DIR.joinpath("subscriptions.js").read_text(encoding="utf-8")

    for state_field in [
        "feedActivity: null",
        "feedActivityLoaded: false",
        "feedActivityLoading: false",
        "feedActivityLoadToken: 0",
        "feedActivityLoadUserId: null",
        "subscriptionActionGeneration: 0",
        "sourceHealthFilter: ''",
    ]:
        assert state_field in state_js
    assert "function safeExternalUrl" in utils_js
    assert "function renderFeedActivityBanner" in reader_js
    assert "function viewFailedSourceHealth" in reader_js
    assert "function invalidateSubscriptionActions" in subscriptions_js
    assert "function subscriptionActionIsCurrent" in subscriptions_js
    assert "data-retry-feed-activity" in reader_js
    assert "data-view-failed-sources" in reader_js
    for canonical_key in [
        "input_type",
        "required",
        "default",
        "options",
        "min",
        "max",
        "help",
    ]:
        assert canonical_key in subscriptions_js
    assert "data-source-health-filter" in subscriptions_js
    assert "data-health-job" in subscriptions_js
    assert "source_outcomes" in subscriptions_js
    assert "sample_title" in subscriptions_js
    assert "sample_url" in subscriptions_js
    assert "noopener noreferrer" in subscriptions_js


def test_subscription_console_job_controls_contract():
    subscriptions_js = STATIC_DIR.joinpath("subscriptions.js").read_text(encoding="utf-8")
    subscriptions_css = STATIC_DIR.joinpath("subscriptions.css").read_text(encoding="utf-8")

    assert "/api/jobs?limit=20" in subscriptions_js
    assert "/api/jobs/" in subscriptions_js
    assert "/cancel" in subscriptions_js
    assert "/retry" in subscriptions_js
    assert "cancelJob" in subscriptions_js
    assert "retryJob" in subscriptions_js
    assert "attempts" in subscriptions_js
    assert "max_attempts" in subscriptions_js
    assert "error_code" in subscriptions_js
    assert "error_message" in subscriptions_js
    assert "subscriptionJobSubmission" in subscriptions_js
    assert "beginJobSubmission" in subscriptions_js
    assert "pollJobUntilTerminal(job.id, job.job_type" in subscriptions_js
    assert ".subscription-job-actions" in subscriptions_css


def test_feed_load_error_is_visible_instead_of_disguised_as_empty_data():
    app_js = STATIC_DIR.joinpath("app.js").read_text(encoding="utf-8")

    assert "信息流读取失败" in app_js
    assert "err.message" in app_js


def test_site_payload_serializes_hub_taxonomy_without_promoting_topics_to_personal_tags():
    item = ContentItem(
        id="rss:item:taxonomy",
        source_type=SourceType.RSS,
        title="Codex creates a product opportunity",
        url="https://example.com/codex",
        published_at=datetime(2026, 7, 6, tzinfo=timezone.utc),
        metadata={
            "channel": "产品机会",
            "topics": ["自定义机会"],
            "personal_tags": ["能黄通"],
        },
    )
    item.ai_score = 8.6
    item.ai_channel = "AI"
    item.ai_topics = ["Codex", "自定义机会"]
    item.ai_signal_strength = "strong"
    item.ai_signal_type = "opportunity"
    item.ai_entities = ["OpenAI", "Codex"]
    item.ai_summary_zh = "Codex 相关能力带来新的产品机会。"
    item.ai_reason = "值得跟进。"

    payload = build_site_payload(
        all_items=[item],
        date="2026-07-06",
        total_fetched=1,
        featured_threshold=7.5,
        tag_library=["Codex", "自定义机会"],
    )
    row = payload["items"][0]

    assert row["channel"] == "AI"
    assert row["category"] == "AI"
    assert row["topics"] == ["Codex", "自定义机会"]
    assert row["tags"] == ["Codex", "自定义机会"]
    assert row["signal_strength"] == "strong"
    assert row["signal_type"] == "opportunity"
    assert row["entities"] == ["OpenAI", "Codex"]
    assert row["personal_tags"] == ["能黄通"]
    assert "自定义机会" not in row["personal_tags"]
    assert payload["channels"] == ["AI"]


def test_site_payload_allows_only_known_explicit_retention_policy():
    def projected_policy(value: str) -> str:
        item = ContentItem(
            id=f"rss:item:{value}",
            source_type=SourceType.RSS,
            title="Profile update",
            url=f"https://example.com/{value}",
            published_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
            metadata={"retention_policy": value},
        )
        payload = build_site_payload(
            all_items=[item], date="2026-07-15", total_fetched=1
        )
        return payload["items"][0]["retention_policy"]

    assert projected_policy("latest_per_source") == "latest_per_source"
    assert projected_policy("untrusted_policy") == "time_window"


def test_backfill_static_site_taxonomy_updates_existing_site_payloads(tmp_path):
    site_dir = tmp_path / "site"
    history_dir = site_dir / "history"
    history_dir.mkdir(parents=True)
    old_payload = {
        "generated_at": "2026-07-06T00:00:00+00:00",
        "date": "2026-07-06",
        "items": [
            {
                "id": "rss:item:old",
                "title": "Old item",
                "category": "AI 编程",
                "tags": ["Codex", "价格监控"],
                "score": 8,
                "personal_tags": ["能黄通"],
            }
        ],
        "featured_items": [],
        "daily_push_items": [],
        "personal_items": [],
        "tag_library": ["Codex", "价格监控"],
        "personal_tag_library": ["能黄通"],
    }
    for name in ["radar-data.json", "today-data.json", "history-data.json"]:
        (site_dir / name).write_text(json.dumps(old_payload), encoding="utf-8")
    (history_dir / "20260706-000000.json").write_text(
        json.dumps(old_payload),
        encoding="utf-8",
    )

    changed = backfill_static_site_taxonomy(site_dir)

    assert changed == 4
    payload = json.loads((site_dir / "radar-data.json").read_text(encoding="utf-8"))
    item = payload["items"][0]
    assert item["channel"] == "AI"
    assert item["category"] == "AI"
    assert item["topics"] == ["Codex", "价格监控", "AI 编程"]
    assert item["tags"] == ["Codex", "价格监控", "AI 编程"]
    assert item["signal_strength"] == "strong"
    assert item["signal_type"] == "other"
    assert item["entities"] == []
    assert item["personal_tags"] == ["能黄通"]


def test_static_ui_has_no_score_mode_labels():
    utils_js = STATIC_DIR.joinpath("utils.js").read_text(encoding="utf-8")
    reader_js = STATIC_DIR.joinpath("reader.js").read_text(encoding="utf-8")
    app_js = STATIC_DIR.joinpath("app.js").read_text(encoding="utf-8")

    assert "function getEffectiveMinScore" in utils_js
    assert "全部动态" in utils_js
    assert "无评分模式" in reader_js
    assert "无评分模式：按发布时间和信源优先级阅读" in reader_js
    assert "state.view = 'all'" in app_js


def test_config_ui_groups_cost_features_as_advanced():
    config_js = STATIC_DIR.joinpath("config.js").read_text(encoding="utf-8")
    config_css = STATIC_DIR.joinpath("config.css").read_text(encoding="utf-8")

    assert "renderCoreSettings" in config_js
    assert "renderAdvancedSettings" in config_js
    assert "成本源" in config_js
    assert "高级 / 可选能力" in config_js
    assert ".advanced-section" in config_css
    assert ".cost-badge" in config_css
    assert ".config-field-multi" in config_css


def test_static_ui_uses_reader_layout_css():
    css = "\n".join(
        (STATIC_DIR / name).read_text(encoding="utf-8")
        for name in ["base.css", "reader.css", "config.css", "media.css"]
    )

    assert ".reader-shell" in css
    assert ".reading-queue" in css
    assert ".reader-panel" in css
    assert ".context-panel" in css
    assert ".inline-preview" not in css
    assert ".preview-open-link" not in css
    assert ".copy-ok" in css
    assert ".copy-error" in css
    assert ".reading-actions" in css
    assert ".article-note" in css
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
    assert ".article-graph-fab" not in css
    assert ".article-graph-panel" not in css
    assert ".graph-edge-card" not in css
    assert ".media-lightbox-nav" in css
    assert "object-fit: cover" in css
    assert ".tabs::-webkit-scrollbar" in css
    assert "overflow-x: auto" in css
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in css
    assert "margin-top: clamp(56px, 9vh, 112px)" in css
    assert "margin-top: 28px" in css
    assert "padding-top: 14px" in css
    assert "grid-template-columns: minmax(150px, 34vw) minmax(0, 1fr)" in css
    assert "grid-column: 2" in css
    assert "font-size: 15px" in css
    assert "-webkit-line-clamp: 7" in css
    assert "@media (max-width: 720px)" in css
    assert ".reader-panel {\n    order: 1;" in css
    assert ".reading-queue {\n    order: 2;" in css
    assert ".context-panel {\n    order: 3;" in css
    assert ".story-list {\n    max-height: 480px;" in css
    assert "#0071e3" in css
