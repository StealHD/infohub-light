import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.models import Config, ContentItem, SourceType
from src.services.article_features import extract_article_features
from src.services.article_graph import build_article_graph_snapshot, write_article_graph_snapshot
from src.services.fulltext import clean_html_to_text
from src.storage.article_store import ArticleStore, content_hash, normalize_url


def _item(
    item_id: str,
    title: str,
    *,
    url: str = "https://example.com/post",
    content: str = "",
    score: float = 9.0,
    tags: list[str] | None = None,
    category: str = "AI Agent",
    published: str = "2026-06-08T08:00:00+00:00",
) -> ContentItem:
    item = ContentItem(
        id=item_id,
        source_type=SourceType.RSS,
        title=title,
        url=url,
        content=content or title,
        author="Example",
        published_at=datetime.fromisoformat(published),
        fetched_at=datetime.fromisoformat(published),
        metadata={"feed_name": "Example Feed", "tags": tags or [category]},
    )
    item.ai_score = score
    item.ai_summary_zh = content or title
    item.ai_reason = "来源可靠，值得测试。"
    item.ai_category = category
    item.ai_tags = tags or [category]
    item.ai_is_featured = score >= 7.5
    return item


def test_article_graph_config_defaults_are_disabled():
    config = Config.model_validate(
        {
            "ai": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "api_key_env": "OPENAI_API_KEY",
            },
            "sources": {"hackernews": {"enabled": False}},
            "filtering": {},
        }
    )

    assert config.premium_analysis.enabled is False
    assert config.article_graph.enabled is False
    assert config.premium_analysis.max_full_fetch_per_run == 10
    assert config.article_graph.premium_score_threshold == 8.5


def test_article_graph_config_accepts_custom_values():
    config = Config.model_validate(
        {
            "ai": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "api_key_env": "OPENAI_API_KEY",
            },
            "sources": {"hackernews": {"enabled": False}},
            "filtering": {},
            "premium_analysis": {
                "enabled": True,
                "full_fetch_score_threshold": 8.8,
                "max_full_fetch_per_run": 4,
                "max_full_text_chars": 6000,
            },
            "article_graph": {
                "enabled": True,
                "premium_score_threshold": 8.8,
                "relation_top_k": 2,
                "min_relation_score": 0.4,
            },
        }
    )

    assert config.premium_analysis.enabled is True
    assert config.premium_analysis.full_fetch_score_threshold == 8.8
    assert config.premium_analysis.max_full_fetch_per_run == 4
    assert config.article_graph.enabled is True
    assert config.article_graph.relation_top_k == 2
    assert config.article_graph.min_relation_score == 0.4


def test_article_store_initializes_and_upserts_light_items_idempotently(tmp_path: Path):
    store = ArticleStore(tmp_path)
    item = _item(
        "rss:item:1",
        "OpenAI launches new Codex agent workflow",
        url="https://www.example.com/path/?b=2&a=1#section",
        tags=["AI 编程"],
        category="AI 编程",
    )
    item.ai_channel = "AI"
    item.ai_topics = ["Codex", "AI 编程"]
    item.ai_signal_strength = "strong"
    item.ai_signal_type = "release"
    item.ai_entities = ["OpenAI", "Codex"]

    store.initialize()
    assert store.upsert_articles_light([item]) == 1
    assert store.upsert_articles_light([item]) == 1

    rows = store.load_articles_light(min_score=8.5)
    assert len(rows) == 1
    assert rows[0]["id"] == "rss:item:1"
    assert rows[0]["normalized_url"] == "example.com/path?b=2&a=1"
    assert rows[0]["channel"] == "AI"
    assert rows[0]["topics"] == ["Codex", "AI 编程"]
    assert rows[0]["signal_strength"] == "strong"
    assert rows[0]["signal_type"] == "release"
    assert rows[0]["entities"] == ["OpenAI", "Codex"]
    assert rows[0]["category"] == "AI"
    assert rows[0]["tags"] == ["Codex", "AI 编程"]


def test_article_store_migrates_existing_light_table_taxonomy_columns(tmp_path: Path):
    db_path = tmp_path / "horizon.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE articles_light (
            id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            source TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            normalized_url TEXT NOT NULL,
            author TEXT,
            published_at TEXT,
            fetched_at TEXT,
            score REAL NOT NULL DEFAULT 0,
            reason TEXT,
            summary_zh TEXT,
            category TEXT,
            tags_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            content_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.close()

    store = ArticleStore(tmp_path)
    item = _item(
        "rss:item:migrated",
        "Anthropic ships a Claude Code update",
        tags=["Claude Code"],
        category="AI",
    )
    item.ai_channel = "AI"
    item.ai_topics = ["Claude Code"]
    item.ai_signal_strength = "developing"
    item.ai_signal_type = "release"
    item.ai_entities = ["Anthropic", "Claude Code"]

    store.initialize()
    columns = {row["name"] for row in store.connect().execute("PRAGMA table_info(articles_light)")}
    assert {"channel", "topics_json", "signal_strength", "signal_type", "entities_json"} <= columns

    assert store.upsert_articles_light([item]) == 1
    rows = store.load_articles_light(min_score=8.5)
    assert rows[0]["channel"] == "AI"
    assert rows[0]["topics"] == ["AI 编程"]
    assert rows[0]["entities"] == ["Anthropic", "Claude Code"]


def test_url_normalize_and_content_hash_are_stable():
    assert normalize_url("https://www.example.com/a/b/?q=1#top") == "example.com/a/b?q=1"
    assert normalize_url("http://example.com/a/b") == "example.com/a/b"
    assert content_hash("hello", "world") == content_hash("hello", "world")
    assert content_hash("hello", "world") != content_hash("hello", "World")


def test_clean_html_to_text_removes_chrome_and_truncates():
    html = """
    <html><head><style>.x{}</style><script>alert(1)</script></head>
    <body><nav>menu</nav><article><h1>Title</h1><p>Useful text here.</p></article><footer>footer</footer></body></html>
    """

    text = clean_html_to_text(html, max_chars=18)

    assert text == "Title Useful text "
    assert "alert" not in text
    assert "menu" not in text
    assert "footer" not in text


def test_extract_article_features_finds_topics_entities_and_keywords():
    item = _item(
        "rss:item:feature",
        "OpenAI Codex adds MCP tool use",
        content="OpenAI released a Codex update for MCP tool use and AI Agent workflows.",
        tags=["AI 编程", "RAG/MCP"],
        category="AI 编程",
    )

    features = extract_article_features(item)

    assert "AI 编程" in features["topics"]
    assert "RAG/MCP" in features["topics"]
    assert "OpenAI" in features["entities"]
    assert "Codex" in features["entities"]
    assert "mcp" in features["keywords"]


def test_build_article_graph_snapshot_generates_top_edges_and_groups():
    items = [
        _item(
            "rss:item:1",
            "OpenAI Codex adds MCP tool use",
            url="https://example.com/1",
            content="OpenAI released a Codex update for MCP tool use and AI Agent coding.",
            tags=["AI 编程", "RAG/MCP"],
            published="2026-06-08T08:00:00+00:00",
        ),
        _item(
            "rss:item:2",
            "Codex plugin workflow supports MCP servers",
            url="https://example.com/2",
            content="Developers discuss Codex plugin workflow and MCP servers from OpenAI.",
            tags=["AI 编程", "RAG/MCP"],
            published="2026-06-08T10:00:00+00:00",
        ),
        _item(
            "rss:item:3",
            "New image generation benchmark",
            url="https://example.com/3",
            content="A model release benchmark unrelated to Codex.",
            tags=["模型发布"],
            category="模型发布",
            published="2026-06-08T11:00:00+00:00",
        ),
    ]
    store = ArticleStore(Path(":memory:"))
    store.initialize()
    store.upsert_articles_light(items)

    snapshot = build_article_graph_snapshot(
        store,
        premium_score_threshold=8.5,
        relation_top_k=3,
        min_relation_score=0.4,
    )

    assert snapshot["version"] == "article-graph-v1"
    assert snapshot["stats"]["nodes"] == 3
    assert snapshot["stats"]["edges"] >= 1
    assert snapshot["stats"]["groups"] >= 1
    edge = snapshot["edges"][0]
    assert {edge["source"], edge["target"]} == {"rss:item:1", "rss:item:2"}
    assert edge["relation_type"] in {"topic", "entity", "timeline", "same_event"}
    assert "共同" in edge["reason"] or "发布时间" in edge["reason"]


def test_article_graph_snapshot_empty_and_write(tmp_path: Path):
    store = ArticleStore(tmp_path)
    store.initialize()

    snapshot = build_article_graph_snapshot(store)
    path = write_article_graph_snapshot(tmp_path / "site", snapshot)

    assert path.name == "article-graph.json"
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["stats"] == {"nodes": 0, "edges": 0, "groups": 0}
    assert written["nodes"] == []
    assert written["edges"] == []
